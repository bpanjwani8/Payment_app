"""
agent.py — Payment Collection AI Agent
Strands agentic loop + state machine guards + prompt-driven flow.
"""

import os
from typing import Optional

import boto3
from dotenv import load_dotenv
from strands import Agent as StrandsAgent, tool
from strands.models import BedrockModel
from strands.hooks import BeforeToolCallEvent

from state_manager import StateManager
from tools import lookup_account, process_payment
from validators import (
    validate_account_id,
    validate_all_payment_fields,
    verify_identity,
)

load_dotenv()


# ── Tool factory ───────────────────────────────────────────────────────────

def _make_tools(sm: StateManager):
    """
    Return three @tool-decorated functions that close over the given
    StateManager instance.  New closures are created per Agent so that
    each conversation has its own isolated state.
    """

    @tool
    def do_lookup_account(account_id: str) -> str:
        """
        Look up a customer account by their Account ID.

        Call this tool as soon as the user provides any string that looks like
        an account identifier (alphanumeric, may contain hyphens or underscores).
        Normalize the account_id to uppercase before calling -- 'acc1001' and
        'ACC1001' refer to the same account.

        On success the account is found and the session advances to identity
        verification. On failure an error message is returned; relay it to the
        user and ask them to double-check their Account ID.

        Do NOT call this tool more than once per session.
        """
        # Collapse any internal whitespace ("ACC 1001" → "ACC1001") and normalise case
        account_id = "".join(account_id.split()).upper()

        ok, err = validate_account_id(account_id)
        if not ok:
            return f"ERROR: {err} Please ask the user to provide a valid Account ID (4-30 alphanumeric characters)."

        if sm.stage not in ("WAITING_FOR_ACCOUNT_ID",):
            return "ERROR: Account lookup already completed for this session."

        try:
            account_data = lookup_account(account_id)
        except RuntimeError as e:
            sm.increment_lookup_attempt()
            if sm.lookup_retries_exhausted():
                sm.transition("FAILED")
                return (
                    f"FAILED: Account lookup failed after 3 attempts: {e}. "
                    "Session terminated for security reasons. "
                    "Inform the user they must contact support to proceed."
                )
            attempts_left = sm.get("lookup", "max_attempts") - sm.get("lookup", "attempts")
            return f"ERROR: {e} {attempts_left} attempt(s) remaining. Ask the user to double-check their Account ID."

        if not account_data:
            sm.increment_lookup_attempt()
            if sm.lookup_retries_exhausted():
                sm.transition("FAILED")
                return (
                    "FAILED: Account not found after 3 attempts. "
                    "Session terminated for security reasons. "
                    "Inform the user they must contact support to proceed."
                )
            attempts_left = sm.get("lookup", "max_attempts") - sm.get("lookup", "attempts")
            return f"ERROR: No account found for that ID. {attempts_left} attempt(s) remaining. Ask the user to double-check their Account ID."

        sm.set_account_id(account_id)
        sm.set_account_data(account_data)
        sm.transition("ACCOUNT_FETCHED")
        sm.transition("VERIFYING")

        balance = account_data.get("balance", 0)
        return (
            f"SUCCESS: Account found. "
            f"Outstanding balance: {balance}. "
            "Now collect identity verification details: full name (case-sensitive, "
            "exactly as registered on the account), and at least one of: date of birth (YYYY-MM-DD), "
            "last 4 digits of Aadhaar, or 6-digit pincode."
        )

    @tool
    def do_verify_identity(
        full_name: str,
        dob: Optional[str] = None,
        aadhaar_last4: Optional[str] = None,
        pincode: Optional[str] = None,
    ) -> str:
        """
        Verify the customer identity by matching their details against the account.

        Call this tool once you have collected the customer full name AND at least
        one secondary field (date of birth, last 4 digits of Aadhaar, or pincode).
        You MUST call do_lookup_account first and be in the identity verification
        stage before calling this tool.

        full_name: Customer full name exactly as they provided it (case-sensitive).
        dob: Date of birth in YYYY-MM-DD format (optional).
        aadhaar_last4: Last 4 digits of Aadhaar number (optional).
        pincode: 6-digit pincode (optional).

        At least one of dob, aadhaar_last4, or pincode must be provided.
        Returns verification result and remaining attempts if failed.
        """
        if sm.stage != "VERIFYING":
            return "ERROR: Cannot verify identity at this stage. Ensure account lookup is done first."

        if not full_name or not full_name.strip():
            return "ERROR: full_name is required for identity verification."

        has_secondary = any([dob, aadhaar_last4, pincode])
        if not has_secondary:
            return "ERROR: At least one of dob, aadhaar_last4, or pincode must be provided."

        sm.update_user_input("full_name", full_name.strip())
        if dob:
            sm.update_user_input("dob", dob.strip())
        if aadhaar_last4:
            sm.update_user_input("aadhaar_last4", aadhaar_last4.strip())
        if pincode:
            sm.update_user_input("pincode", pincode.strip())

        account_data = sm.get("account_data")
        user_inputs = sm.get("user_inputs")

        sm.increment_verification_attempt()
        verified = verify_identity(account_data, user_inputs)

        if verified:
            sm.mark_verified()
            sm.transition("VERIFIED")
            balance = account_data.get("balance", 0)
            return (
                f"SUCCESS: Identity verified. Customer is authenticated. "
                f"Outstanding balance: {balance}. "
                "Now collect payment details: amount, cardholder name (name printed on card), "
                "full card number, CVV (3 or 4 digits), expiry month (1-12), expiry year (4-digit)."
            )

        if sm.retries_exhausted():
            sm.transition("FAILED")
            return (
                "FAILED: Identity verification failed after 3 attempts. "
                "Session terminated for security reasons. "
                "Inform the user they must contact support to proceed."
            )

        attempts_left = sm.get("verification", "max_attempts") - sm.get("verification", "attempts")
        return (
            f"FAILED: Identity verification failed. {attempts_left} attempt(s) remaining. "
            "The full name must match exactly (case-sensitive). "
            "Ask the user to try again with the correct full name and one matching secondary field."
        )

    @tool
    def do_process_payment(
        amount: float,
        card_number: str,
        cvv: str,
        expiry_month: int,
        expiry_year: int,
        cardholder_name: str,
    ) -> str:
        """
        Process a payment for the authenticated customer.

        Only call this tool AFTER do_verify_identity has returned SUCCESS and
        the customer is fully authenticated. You MUST have all six fields before
        calling this tool -- do not call with any field missing or estimated.

        amount: Payment amount exactly as stated by the user. Do NOT round or modify this value.
                Pass exactly what the user stated (e.g., if user said 1000.005, pass 1000.005).
                Must be > 0 and <= outstanding balance.
        card_number: Full card number (digits only, hyphens allowed).
        cvv: Card security code (3 or 4 digits).
        expiry_month: Card expiry month as integer 1-12.
        expiry_year: Card expiry year as 4-digit integer (e.g. 2027).
        cardholder_name: Name exactly as printed on the card (ask explicitly -- do NOT assume it equals the account holder name).

        Runs local validation (Luhn check, expiry, amount vs balance) before
        calling the payment API. Returns success with transaction ID or a
        specific error to relay to the user.
        """
        if sm.stage != "VERIFIED":
            return "ERROR: Cannot process payment -- identity verification must be completed first."

        sm.update_payment_field("amount", amount)
        sm.update_payment_field("card_number", card_number)
        sm.update_payment_field("cvv", cvv)
        sm.update_payment_field("expiry_month", expiry_month)
        sm.update_payment_field("expiry_year", expiry_year)
        sm.update_payment_field("cardholder_name", cardholder_name)

        payment = sm.get("payment")
        account_data = sm.get("account_data")
        balance = account_data.get("balance", float("inf"))
        errors = validate_all_payment_fields(payment, balance)

        if errors:
            error_list = "; ".join(errors)
            return (
                f"VALIDATION_ERROR: {error_list}. "
                "Do not retry the API call until the user provides corrected values."
            )

        sm.transition("PAYMENT_PROCESSING")
        card = payment["card_details"]

        try:
            result = process_payment(
                account_id=sm.get("account_id"),
                amount=float(payment["amount"]),
                cardholder_name=card["cardholder_name"],
                card_number=card["card_number"],
                cvv=card["cvv"],
                expiry_month=int(card["expiry_month"]),
                expiry_year=int(card["expiry_year"]),
            )
        except RuntimeError as e:
            sm.increment_payment_attempt()
            if sm.payment_retries_exhausted():
                sm.transition("FAILED")
                return (
                    f"FAILED: Payment processing failed after multiple attempts: {e}. "
                    "Session closed. Inform the user to contact support."
                )
            sm.transition("VERIFIED")
            attempts_left = sm.get("payment", "max_attempts") - sm.get("payment", "attempts")
            return (
                f"ERROR: Payment processing error: {e}. "
                f"{attempts_left} attempt(s) remaining. "
                "Ask the user if they want to retry or provide updated payment details."
            )

        if result.get("success"):
            txn_id = result.get("transaction_id")
            sm.set_payment_result("success", txn_id)
            sm.transition("COMPLETED")
            return (
                f"SUCCESS: Payment processed. Transaction ID: {txn_id}. "
                f"Amount: {payment['amount']}. Inform the user their payment is complete."
            )

        sm.increment_payment_attempt()
        error_code = result.get("error_code", "unknown")
        if sm.payment_retries_exhausted():
            sm.transition("FAILED")
            return (
                f"FAILED: Payment declined ({error_code}) after multiple attempts. "
                "Session closed. Inform the user to contact support or their bank."
            )
        sm.transition("VERIFIED")
        attempts_left = sm.get("payment", "max_attempts") - sm.get("payment", "attempts")
        return (
            f"DECLINED: Payment declined. Reason: {error_code}. "
            f"{attempts_left} attempt(s) remaining. "
            "Ask the user to provide updated payment details or try a different card."
        )

    return [do_lookup_account, do_verify_identity, do_process_payment]


# ── System prompt ──────────────────────────────────────────────────────────

def _build_system_prompt(sm: StateManager) -> str:
    """Build a state-aware system prompt for the Strands agent."""

    stage = sm.stage

    base = (
        "You are a professional payment collection agent for a financial services company. "
        "Your job is to help customers pay their outstanding balance securely and efficiently. "
        "Be polite, concise, and guide the customer step by step through the process.\n\n"
        "SECURITY RULES -- follow these at all times:\n"
        "- Never display full card numbers, CVV, full Aadhaar numbers, or date of birth back to the user.\n"
        "- The customer full name for identity verification is CASE-SENSITIVE -- collect it exactly.\n"
        "- Cardholder name on the card may differ from the account holder name -- always ask explicitly.\n"
        "- Never skip identity verification before payment.\n\n"
    )

    if stage in ("INIT", "WAITING_FOR_ACCOUNT_ID"):
        context = (
            "CURRENT STAGE: Account lookup.\n"
            "Greet the customer and ask for their Account ID to get started. "
            "Once they provide it, call do_lookup_account immediately."
        )

    elif stage in ("ACCOUNT_FETCHED", "VERIFYING"):
        account_data = sm.get("account_data") or {}
        balance = account_data.get("balance", "")
        attempts = sm.get("verification", "attempts") or 0
        max_attempts = sm.get("verification", "max_attempts") or 3
        remaining = max_attempts - attempts

        context = (
            f"CURRENT STAGE: Identity verification.\n"
            f"Account found. Outstanding balance: {balance}.\n"
            f"Verification attempts used: {attempts}/{max_attempts} ({remaining} remaining).\n"
            "Collect the customer full name (case-sensitive, exactly as registered on the account) "
            "AND at least one of: date of birth (YYYY-MM-DD), last 4 digits of Aadhaar, "
            "or 6-digit pincode.\n"
            "CRITICAL TOOL-CALLING RULES:\n"
            "- The moment you have BOTH a full name AND at least one secondary field available "
            "(from the current message OR any earlier message in this conversation), "
            "call do_verify_identity IMMEDIATELY -- do not ask for confirmation first.\n"
            "- Do NOT validate or pre-judge the data yourself; the tool handles all validation.\n"
            "- Pass exactly what the customer provided, even if it appears wrong or unlikely.\n"
            "- After a failed attempt, ask the customer to try again and call the tool again "
            "as soon as they provide name + secondary field.\n"
            "Do NOT call do_lookup_account again."
        )

    elif stage == "VERIFIED":
        account_data = sm.get("account_data") or {}
        balance = account_data.get("balance", "")
        payment = sm.get("payment") or {}
        card = payment.get("card_details") or {}

        collected = []
        missing = []
        if payment.get("amount") is not None:
            collected.append(f"amount={payment['amount']}")
        else:
            missing.append("amount")
        for field in ("cardholder_name", "card_number", "cvv", "expiry_month", "expiry_year"):
            if card.get(field) is not None:
                collected.append(field)
            else:
                missing.append(field)

        collected_str = ", ".join(collected) if collected else "none"
        missing_str = ", ".join(missing) if missing else "none"

        context = (
            f"CURRENT STAGE: Payment collection.\n"
            f"Customer is verified. Outstanding balance: {balance}.\n"
            f"Payment fields already collected: {collected_str}.\n"
            f"Payment fields still needed: {missing_str}.\n"
            "Collect any remaining fields, then call do_process_payment with ALL six fields. "
            "Do NOT assume cardholder_name equals the account holder name -- ask explicitly if not provided.\n"
            "CRITICAL: Pass the EXACT amount the user stated to do_process_payment -- do NOT round or modify it. "
            "For example, if the user says 1000.005, pass exactly 1000.005.\n"
            "Do NOT call do_lookup_account or do_verify_identity again."
        )

    elif stage == "PAYMENT_PROCESSING":
        context = (
            "CURRENT STAGE: Payment is being processed. "
            "Inform the user their payment is being processed and wait."
        )

    elif stage == "COMPLETED":
        txn = sm.get("payment", "transaction_id") or ""
        amount = sm.get("payment", "amount") or ""
        account_id = sm.get("account_id") or ""
        context = (
            f"CURRENT STAGE: Completed.\n"
            f"Payment was successful. Transaction ID: {txn}. Amount paid: {amount}. Account: {account_id}.\n"
            "Deliver a warm closing message that: (1) confirms payment success, (2) recaps the "
            "transaction ID and amount paid, (3) thanks the customer, and (4) closes the conversation. "
            "Do not call any tools."
        )

    elif stage == "FAILED":
        context = (
            "CURRENT STAGE: Session terminated.\n"
            "The session has ended due to repeated verification or payment failures. "
            "Politely inform the customer the session is closed and they should contact support. "
            "Do not call any tools."
        )

    else:
        context = "An unexpected state was reached. Apologize and suggest contacting support."

    return base + context


# ── Agent ──────────────────────────────────────────────────────────────────

class Agent:
    """
    Public interface: agent.next(user_input: str) -> {"message": str}
    """

    def __init__(self):
        self.sm = StateManager()
        self.sm.transition("WAITING_FOR_ACCOUNT_ID")

        model_id = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20251001-v1:0")
        region = os.getenv("AWS_REGION", "us-east-1")

        boto_session = boto3.Session(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=region,
        )

        bedrock_model = BedrockModel(
            model_id=model_id,
            boto_session=boto_session,
        )

        self._tools = _make_tools(self.sm)

        self._strands = StrandsAgent(
            model=bedrock_model,
            tools=self._tools,
            system_prompt=_build_system_prompt(self.sm),
            callback_handler=None,  # suppress streaming output to stdout
        )

        # ── Guardrail hook: enforce state order before any tool fires ──────
        sm_ref = self.sm

        def _state_guard(event: BeforeToolCallEvent):
            tool_name = event.tool_use["name"]
            stage = sm_ref.stage

            if tool_name == "do_lookup_account" and stage not in ("WAITING_FOR_ACCOUNT_ID",):
                event.cancel_tool = (
                    "Account lookup already completed for this session. "
                    "Do not call do_lookup_account again."
                )
            elif tool_name == "do_verify_identity" and stage != "VERIFYING":
                event.cancel_tool = (
                    f"Cannot verify identity in stage '{stage}'. "
                    "Ensure account lookup is done first."
                )
            elif tool_name == "do_process_payment" and stage != "VERIFIED":
                event.cancel_tool = (
                    f"Cannot process payment in stage '{stage}'. "
                    "Identity must be verified first."
                )

        # add_hook(callback, event_type) — type is inferred from the hint,
        # but we pass it explicitly to be unambiguous.
        self._strands.hooks.add_callback(BeforeToolCallEvent, _state_guard)

    # ── public ──────────────────────────────────────────────────────────────

    def next(self, user_input: str) -> dict:
        # Refresh system prompt to reflect current state before each turn
        self._strands.system_prompt = _build_system_prompt(self.sm)
        result = self._strands(user_input)
        return {"message": str(result)}
