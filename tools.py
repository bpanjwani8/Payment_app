"""
Tools — Exactly 2 tools. No verification tool (verification is pure Python).
"""

import os
import requests
from typing import Optional
import re  # noqa: E402  (used in process_payment above)
from dotenv import load_dotenv

load_dotenv()


def _base_url() -> str:
    url = os.getenv("BASE_URL", "").rstrip("/")
    if not url:
        raise EnvironmentError("BASE_URL is not set in environment.")
    return url


def lookup_account(account_id: str) -> dict:
    """
    POST /api/lookup-account
    Returns account data dict on success.
    Raises RuntimeError on HTTP / network errors with detailed error info.
    """
    url = f"{_base_url()}/api/lookup-account"
    try:
        resp = requests.post(url, json={"account_id": account_id}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        error_detail = ""
        
        # Try to extract error details from response
        if e.response is not None:
            try:
                error_body = e.response.json()
                error_code = error_body.get("error_code", "")
                if error_code == "account_not_found":
                    error_detail = "Account not found. Please verify the Account ID (case-sensitive) and try again."
                elif error_code:
                    error_detail = f"Error: {error_code}"
            except:
                pass
        
        if error_detail:
            raise RuntimeError(f"Account lookup failed: {error_detail}") from e
        else:
            raise RuntimeError(f"Account lookup failed (HTTP {status}). Please try again or contact support.") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error during account lookup. Please check your connection and try again.") from e


def process_payment(
    account_id: str,
    amount: float,
    cardholder_name: str,
    card_number: str,
    cvv: str,
    expiry_month: int,
    expiry_year: int,
) -> dict:
    """
    POST /api/process-payment
    Returns response dict with at least {"success": bool, "transaction_id": ..., "error_code": ...}.
    Raises RuntimeError on HTTP / network errors with detailed error messages.
    """
    url = f"{_base_url()}/api/process-payment"
    payload = {
        "account_id": account_id,
        "amount": amount,
        "payment_method": {
            "type": "card",
            "card": {
                "cardholder_name": cardholder_name,
                "card_number": re.sub(r"\s|-", "", card_number),
                "cvv": str(cvv),
                "expiry_month": int(expiry_month),
                "expiry_year": int(expiry_year),
            },
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        error_detail = ""
        error_code = ""
        
        # Try to extract detailed error from response
        if e.response is not None:
            try:
                error_body = e.response.json()
                error_code = error_body.get("error_code", "")
                
                # Map error codes to user-friendly messages
                error_messages = {
                    "account_not_found": "Account not found. Please verify your account details.",
                    "invalid_amount": "Invalid payment amount. Amount must be positive with max 2 decimal places.",
                    "insufficient_balance": "Payment amount exceeds your outstanding balance.",
                    "invalid_card": "Card number is invalid. Please check the card number and try again.",
                    "invalid_cvv": "CVV is invalid. Please provide a valid 3 or 4 digit CVV.",
                    "invalid_expiry": "Card expiry date is invalid or the card has expired.",
                }
                
                if error_code in error_messages:
                    error_detail = error_messages[error_code]
                elif error_code:
                    error_detail = f"Payment declined with error code: {error_code}"
            except:
                pass
        
        if error_detail:
            raise RuntimeError(f"Payment failed: {error_detail} You may retry with corrected information or contact your bank.") from e
        else:
            raise RuntimeError(f"Payment processing failed (HTTP {status}). Please try again or contact support.") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error during payment processing. Please check your connection and try again, or contact support if the issue persists.") from e
