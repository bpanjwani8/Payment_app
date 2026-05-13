"""
State Manager — Single source of truth for the agent's state machine.
"""

from copy import deepcopy
from typing import Any, Optional


VALID_STAGES = {
    "INIT",
    "WAITING_FOR_ACCOUNT_ID",
    "ACCOUNT_FETCHED",
    "VERIFYING",
    "VERIFIED",
    "PAYMENT_PROCESSING",
    "COMPLETED",
    "FAILED",
}

TRANSITIONS = {
    "INIT":                  ["WAITING_FOR_ACCOUNT_ID"],
    "WAITING_FOR_ACCOUNT_ID":["ACCOUNT_FETCHED", "WAITING_FOR_ACCOUNT_ID", "FAILED"],
    "ACCOUNT_FETCHED":       ["VERIFYING"],
    "VERIFYING":             ["VERIFIED", "VERIFYING", "FAILED"],
    "VERIFIED":              ["PAYMENT_PROCESSING", "VERIFIED"],  # Can return to VERIFIED for retry
    "PAYMENT_PROCESSING":    ["COMPLETED", "VERIFIED", "FAILED"],  # Can return to VERIFIED for retry
    "COMPLETED":             [],
    "FAILED":                [],
}


def _initial_state() -> dict:
    return {
        "stage": "INIT",
        "account_id": None,
        "account_data": None,
        "lookup": {
            "attempts": 0,
            "max_attempts": 3,
        },
        "user_inputs": {
            "full_name": None,
            "dob": None,
            "aadhaar_last4": None,
            "pincode": None,
        },
        "verification": {
            "is_verified": False,
            "attempts": 0,
            "max_attempts": 3,
        },
        "payment": {
            "amount": None,
            "card_details": {
                "cardholder_name": None,
                "card_number": None,
                "cvv": None,
                "expiry_month": None,
                "expiry_year": None,
            },
            "status": None,
            "transaction_id": None,
            "attempts": 0,
            "max_attempts": 3,
        },
    }


class StateManager:
    def __init__(self):
        self._state: dict = _initial_state()

    # ── read ───────────────────────────────────────────────────────────────
    @property
    def stage(self) -> str:
        return self._state["stage"]

    def get(self, *keys) -> Any:
        """Drill into nested keys: get('payment', 'amount')"""
        node = self._state
        for k in keys:
            if not isinstance(node, dict):
                return None
            node = node.get(k)
        return node

    def snapshot(self) -> dict:
        return deepcopy(self._state)

    # ── write ──────────────────────────────────────────────────────────────
    def transition(self, new_stage: str) -> None:
        if new_stage not in VALID_STAGES:
            raise ValueError(f"Unknown stage: {new_stage}")
        allowed = TRANSITIONS.get(self._state["stage"], [])
        if new_stage not in allowed:
            raise ValueError(
                f"Illegal transition: {self._state['stage']} → {new_stage}"
            )
        self._state["stage"] = new_stage

    def set_account_id(self, account_id: str) -> None:
        self._state["account_id"] = account_id

    def set_account_data(self, data: dict) -> None:
        self._state["account_data"] = deepcopy(data)

    def update_user_input(self, field: str, value: Any) -> None:
        if field not in self._state["user_inputs"]:
            raise KeyError(f"Unknown user_input field: {field}")
        self._state["user_inputs"][field] = value

    def increment_lookup_attempt(self) -> None:
        self._state["lookup"]["attempts"] += 1

    def lookup_retries_exhausted(self) -> bool:
        lu = self._state["lookup"]
        return lu["attempts"] >= lu["max_attempts"]

    def increment_verification_attempt(self) -> None:
        self._state["verification"]["attempts"] += 1

    def mark_verified(self) -> None:
        self._state["verification"]["is_verified"] = True

    def update_payment_field(self, field: str, value: Any) -> None:
        if field == "amount":
            self._state["payment"]["amount"] = value
        elif field in self._state["payment"]["card_details"]:
            self._state["payment"]["card_details"][field] = value
        else:
            raise KeyError(f"Unknown payment field: {field}")

    def set_payment_result(self, status: str, transaction_id: Optional[str]) -> None:
        self._state["payment"]["status"] = status
        self._state["payment"]["transaction_id"] = transaction_id

    def increment_payment_attempt(self) -> None:
        self._state["payment"]["attempts"] += 1

    def payment_retries_exhausted(self) -> bool:
        p = self._state["payment"]
        return p["attempts"] >= p["max_attempts"]

    # ── helpers ────────────────────────────────────────────────────────────
    def retries_exhausted(self) -> bool:
        v = self._state["verification"]
        return v["attempts"] >= v["max_attempts"]

    def is_verified(self) -> bool:
        return self._state["verification"]["is_verified"]

    def missing_user_inputs(self) -> list[str]:
        return [k for k, v in self._state["user_inputs"].items() if v is None]

    def missing_payment_fields(self) -> list[str]:
        missing = []
        if self._state["payment"]["amount"] is None:
            missing.append("amount")
        for k, v in self._state["payment"]["card_details"].items():
            if v is None:
                missing.append(k)
        return missing
