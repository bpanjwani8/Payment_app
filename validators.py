"""
Validators — All validation logic lives here. No business logic in the LLM.
"""

import re
from datetime import date
from typing import Optional


# ── Account ────────────────────────────────────────────────────────────────

def validate_account_id(account_id: str) -> tuple[bool, str]:
    """Account ID must be a non-empty alphanumeric string (6–20 chars)."""
    if not account_id:
        return False, "Account ID cannot be empty."
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,30}", account_id):
        return False, "Account ID must be 4–30 alphanumeric characters (hyphens/underscores allowed)."
    return True, ""


# ── Identity Verification ──────────────────────────────────────────────────

def verify_identity(account_data: dict, user_inputs: dict) -> bool:
    """
    Verified IFF:
      full_name matches EXACTLY (case-sensitive, no fuzzy)
      AND at least ONE of: dob | aadhaar_last4 | pincode matches EXACTLY.
    """
    expected_name = account_data.get("full_name", "")
    if user_inputs.get("full_name") != expected_name:
        return False

    secondary_fields = {
        "dob":          account_data.get("dob"),
        "aadhaar_last4":account_data.get("aadhaar_last4"),
        "pincode":      account_data.get("pincode"),
    }
    for field, expected in secondary_fields.items():
        if expected is not None and user_inputs.get(field) == expected:
            return True
    return False


# ── Payment ────────────────────────────────────────────────────────────────

def validate_amount(amount, balance: float) -> tuple[bool, str]:
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return False, "Amount must be a valid number."
    if amount <= 0:
        return False, "Amount must be greater than 0."
    if amount > balance:
        return False, f"Amount exceeds your available balance of {balance}."
    return True, ""


def _luhn_check(card_number: str) -> bool:
    digits = [int(d) for d in card_number if d.isdigit()]
    if len(digits) not in (13, 15, 16, 19):
        return False
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_card_number(card_number: str) -> tuple[bool, str]:
    digits_only = re.sub(r"\s|-", "", card_number)
    if not digits_only.isdigit():
        return False, "Card number must contain only digits."
    if not _luhn_check(digits_only):
        return False, "Card number is invalid (failed Luhn check)."
    return True, ""


def validate_cvv(cvv: str) -> tuple[bool, str]:
    if not re.fullmatch(r"\d{3,4}", str(cvv)):
        return False, "CVV must be 3 or 4 digits."
    return True, ""


def validate_expiry(expiry_month: Optional[int], expiry_year: Optional[int]) -> tuple[bool, str]:
    try:
        month = int(expiry_month)
        year  = int(expiry_year)
    except (TypeError, ValueError):
        return False, "Expiry month and year must be integers."
    if not (1 <= month <= 12):
        return False, "Expiry month must be between 1 and 12."
    today = date.today()
    # Card is valid through the last day of the expiry month
    if (year, month) < (today.year, today.month):
        return False, "Card has expired."
    return True, ""


def validate_all_payment_fields(payment: dict, balance: float) -> list[str]:
    """Return list of human-readable error strings (empty = all valid)."""
    errors = []

    ok, msg = validate_amount(payment.get("amount"), balance)
    if not ok:
        errors.append(msg)

    card = payment.get("card_details", {})
    ok, msg = validate_card_number(card.get("card_number", ""))
    if not ok:
        errors.append(msg)

    ok, msg = validate_cvv(card.get("cvv", ""))
    if not ok:
        errors.append(msg)

    ok, msg = validate_expiry(card.get("expiry_month"), card.get("expiry_year"))
    if not ok:
        errors.append(msg)

    if not card.get("cardholder_name", "").strip():
        errors.append("Cardholder name is required.")

    return errors
