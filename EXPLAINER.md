# Payment Collection AI Agent - Flow Explainer

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [State Machine](#state-machine)
4. [Happy Path Flow](#happy-path-flow)
5. [Error Handling & Retries](#error-handling--retries)
6. [Detailed Flow Diagrams](#detailed-flow-diagrams)
7. [Security & Validation](#security--validation)

---

## Overview

This is a **deterministic state machine-based AI agent** for collecting payments from customers. It uses:
- **AWS Bedrock LLM** (Claude Sonnet 4.5) for natural language understanding and response generation
- **Strands Agents SDK** to drive the agentic loop (LLM ↔ tool calls ↔ observations)
- **Python validators** for all business logic (no LLM-based validation)
- **External API tools** for account lookup and payment processing
- **Strict state transitions** to ensure predictable behavior
- **BeforeToolCallEvent guardrail hook** to enforce tool-call ordering at runtime

### Key Design Principles
- ✅ **Deterministic**: The LLM is used ONLY for extraction and response generation, never for decision-making
- ✅ **Secure**: All validation happens in Python code, not in LLM prompts
- ✅ **Transparent**: Clear state machine with explicit transitions
- ✅ **Retry-safe**: Built-in retry mechanisms for verification failures
- ✅ **Intelligent**: Supports both single-turn and multi-turn conversation flows
- ✅ **Context-aware**: Maintains conversation history for natural dialogue

---

## Architecture

### Component Breakdown

```
┌─────────────────────────────────────────────────────────────┐
│                         Agent (agent.py)                     │
│  - Orchestrates the conversation flow                        │
│  - Manages state transitions                                 │
│  - Calls LLM for extraction & response generation            │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
            ▼               ▼               ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────┐
│  StateManager    │ │  Validators  │ │    Tools     │
│ (state_manager)  │ │ (validators) │ │   (tools)    │
├──────────────────┤ ├──────────────┤ ├──────────────┤
│ - Stage tracking │ │ - Account ID │ │ - lookup_    │
│ - User inputs    │ │ - Identity   │ │   account()  │
│ - Verification   │ │ - Amount     │ │ - process_   │
│ - Payment data   │ │ - Card #     │ │   payment()  │
│ - Transitions    │ │ - CVV/Expiry │ │              │
└──────────────────┘ └──────────────┘ └──────────────┘
```

### File Responsibilities

| File | Purpose |
|------|---------|
| `agent.py` | Main orchestrator; Strands setup, tool closures, guardrail hook, system prompt builder |
| `app.py` | Streamlit web UI (`streamlit run app.py`); each browser tab gets an isolated `Agent` instance stored in `st.session_state` |
| `state_manager.py` | Single source of truth for conversation state |
| `validators.py` | Pure Python validation logic (account, identity, payment) |
| `tools.py` | API calls to external services (account lookup, payment processing) |
| `Run_from_terminal.py` | Interactive terminal interface |

---

## State Machine

### All States

```
INIT                   → Initial state when agent is created
WAITING_FOR_ACCOUNT_ID → Awaiting user's account ID
ACCOUNT_FETCHED        → Account found, ready to verify
VERIFYING              → Collecting identity verification info
VERIFIED               → Identity confirmed, ready for payment
PAYMENT_PROCESSING     → Payment being processed
COMPLETED              → Payment successful
FAILED                 → Terminal failure (lookup, verification, or payment)
```

### Allowed Transitions

```
INIT                   → WAITING_FOR_ACCOUNT_ID
WAITING_FOR_ACCOUNT_ID → ACCOUNT_FETCHED, WAITING_FOR_ACCOUNT_ID (retry), FAILED (3 lookup errors)
ACCOUNT_FETCHED        → VERIFYING
VERIFYING              → VERIFIED, VERIFYING (retry), FAILED (3 attempts)
VERIFIED               → PAYMENT_PROCESSING, VERIFIED (retry for payment errors)
PAYMENT_PROCESSING     → COMPLETED, VERIFIED (retry), FAILED (3 attempts)
COMPLETED              → (terminal)
FAILED                 → (terminal)
```

**Multi-Stage Transitions**

When a user provides all information in a single message, the Strands agentic loop calls tools sequentially within one turn, advancing through multiple state transitions before returning a response.

```
Single Turn Flow Example:
User provides: Account ID + Verification Info + Payment Details
→ WAITING_FOR_ACCOUNT_ID → ACCOUNT_FETCHED → VERIFYING → VERIFIED → PAYMENT_PROCESSING → COMPLETED

Traditional Flow (still supported):
Turn 1: Account ID → ACCOUNT_FETCHED
Turn 2: Verification Info → VERIFIED
Turn 3: Payment Details → COMPLETED
```

---

## Happy Path Flow

### Step-by-Step: Successful Payment (Multi-Stage Single Turn)

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. INIT → WAITING_FOR_ACCOUNT_ID → ACCOUNT_FETCHED → VERIFYING   │
├──────────────────────────────────────────────────────────────────┤
│ User:  "My account ID is ACC-12345, I'm John Doe born 1990-05-15,│
│         Aadhaar last 4 is 1234, pincode 400001, paying 5000 with │
│         card 4532-1234-5678-9010, CVV 123, exp 12/2027,         │
│         cardholder John Doe"                                      │
│                                                                   │
│ ✓ LLM extracts ALL fields in one pass                           │
│ ✓ Account lookup: lookup_account("ACC-12345") → success         │
│ ✓ Verification: name + DOB match → VERIFIED                     │
│ ✓ Payment validation: all fields valid, Luhn check passed       │
│ ✓ Payment processing: process_payment(...) → success            │
│                                                                   │
│ Agent: "Payment successful! Transaction ID: TXN-789. Thank you!" │
│                                                                   │
│ Final State: COMPLETED                                           │
│ Total Turns: 1 (vs traditional 4-5 turns)                       │
└──────────────────────────────────────────────────────────────────┘
```

### Step-by-Step: Successful Payment (Traditional Incremental Flow)

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. INIT → WAITING_FOR_ACCOUNT_ID                                 │
├──────────────────────────────────────────────────────────────────┤
│ Agent: "Hello! May I have your Account ID to get started?"       │
│ User:  "My account ID is ACC-12345"                              │
│                                                                   │
│ ✓ LLM extracts: {"account_id": "ACC-12345"}                     │
│ ✓ Validator checks: 4-30 alphanumeric chars ✓                   │
│ ✓ Tool calls: lookup_account("ACC-12345")                       │
│ ✓ Returns: {full_name, dob, aadhaar_last4, pincode, balance}   │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ 2. ACCOUNT_FETCHED → VERIFYING                                   │
├──────────────────────────────────────────────────────────────────┤
│ Agent: "Account found! For verification, please provide your     │
│         full name, date of birth, last 4 digits of Aadhaar,      │
│         and pincode."                                             │
│ User:  "John Doe, 1990-05-15, 1234, 400001"                      │
│                                                                   │
│ ✓ LLM extracts: {                                                │
│     "full_name": "John Doe",                                     │
│     "dob": "1990-05-15",                                         │
│     "aadhaar_last4": "1234",                                     │
│     "pincode": "400001"                                          │
│   }                                                               │
│ ✓ Validator verifies: full_name matches EXACTLY +                │
│                        at least 1 secondary field matches        │
│ ✓ Identity verified!                                             │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ 3. VERIFIED → PAYMENT_PROCESSING                                 │
├──────────────────────────────────────────────────────────────────┤
│ Agent: "Verified! Your outstanding balance is ₹10,000. Please    │
│         provide payment amount, cardholder name, card number,    │
│         CVV, and expiry (month/year)."                           │
│ User:  "5000, John Doe, 4532-1234-5678-9010, 123, 12, 2027"      │
│                                                                   │
│ ✓ LLM extracts: {                                                │
│     "amount": 5000,                                              │
│     "cardholder_name": "John Doe",                               │
│     "card_number": "4532-1234-5678-9010",                        │
│     "cvv": "123",                                                │
│     "expiry_month": 12,                                          │
│     "expiry_year": 2027                                          │
│   }                                                               │
│ ✓ Validators check:                                              │
│   - Amount > 0 and <= balance ✓                                  │
│   - Card number passes Luhn check ✓                              │
│   - CVV is 3-4 digits ✓                                          │
│   - Expiry is in the future ✓                                    │
│ ✓ Tool calls: process_payment(...)                              │
│ ✓ Returns: {status: "success", transaction_id: "TXN-789"}       │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ 4. PAYMENT_PROCESSING → COMPLETED                                │
├──────────────────────────────────────────────────────────────────┤
│ Agent: "Payment successful! Transaction ID: TXN-789. Thank you!" │
│                                                                   │
│ ✓ State saved with transaction ID                                │
│ ✓ Conversation ends                                              │
└──────────────────────────────────────────────────────────────────┘
```

### Timeline Summary
1. **Multi-Stage Flow**: 1-2 turns total when all info provided upfront
2. **Traditional Flow**: 3-5 turns with incremental disclosure
3. **Identity Verification**: ~1-3 turns (may retry up to 3 times)
4. **Payment Collection**: ~1-2 turns (may ask for missing fields)
5. **Processing**: Instant

---

## Error Handling & Retries

### 1. Account Lookup Failures

#### Invalid Account ID Format
```
User:  "My ID is XYZ"
Agent: "That account ID is invalid. It must be 4-30 alphanumeric 
        characters. Please try again."

State: WAITING_FOR_ACCOUNT_ID (format errors do NOT count toward retry limit)
```

#### Account Not Found / API Error (Up to 3 Retries)
```
User:  "ACC-NOTFOUND"
Tool:  lookup_account() → HTTP 404

Agent: "Account not found. 2 attempt(s) remaining. Please double-check 
        your Account ID and try again."

State: WAITING_FOR_ACCOUNT_ID (attempts: 1/3)
```

#### Lookup Retry Exhaustion
```
After 3rd failed lookup (account not found or API error):

Agent: "Account lookup failed after 3 attempts. For security reasons, 
        this session has been terminated. Please contact our support team."

State: FAILED (terminal)
```

> **Note:** The lookup retry counter (`lookup.attempts`) is tracked separately from the identity verification counter (`verification.attempts`).

---

### 2. Verification Failures

#### Wrong Name (Case Sensitive)
```
User:  "john doe, 1990-05-15, 4321"
Expected: "John Doe" (exact case match)

Agent: "Identity verification failed. You have 2 attempt(s) remaining. 
        Please try again with correct full name (case sensitive) and one 
        of: DOB, Aadhaar last 4, or pincode."

State: VERIFYING (attempts: 1/3)
```

#### No Secondary Field Match
```
User:  "John Doe, 1985-01-01, 9999"
Expected: At least one of dob/aadhaar_last4/pincode must match

Agent: "Identity verification failed. You have 1 attempt(s) remaining..."

State: VERIFYING (attempts: 2/3)
```

#### Retry Exhaustion
```
After 3rd failed attempt:

Agent: "Verification failed after 3 attempts. For security reasons, this 
        session has been terminated. Please contact our support team."

State: FAILED (terminal — no further interaction allowed)
```

---

### 3. Payment Validation Failures

#### Invalid Card Number (Luhn Check)
```
User:  "500, John Doe, 1234-5678-9012-3456, 123, 12, 2027"

Validator: Luhn algorithm fails

Agent: "The following validation errors were found: Card number is invalid 
        (failed Luhn check). Please correct these and provide updated information."

State: VERIFIED (stays in same state, can provide corrected info)
Note: API is NEVER called with invalid card number
```

#### Expired Card
```
User:  "500, John Doe, 4532-1234-5678-9010, 123, 05, 2024"

Validator: expiry_date < current_date

Agent: "The following validation errors were found: Card has expired. 
        Please correct these and provide updated information."

State: VERIFIED (can retry with valid card)
```

#### Amount Exceeds Balance
```
User:  "10000, John Doe, 4532-1234-5678-9010, 123, 12, 2027"
Balance: 1250.75

Validator: amount > balance

Agent: "The following validation errors were found: Amount exceeds your 
        available balance of 1250.75. Please correct these and provide 
        updated information."

State: VERIFIED (can provide lower amount)
```

---

### 4. Payment Processing Failures

#### Payment Declined by API
```
Tool: process_payment(...) → {success: false, error_code: "insufficient_funds"}

Agent: "Payment was declined. Reason: Insufficient balance - amount exceeds 
        outstanding balance. Please enter a lower amount within your 
        outstanding balance. You have 2 attempt(s) remaining."

State: VERIFIED (returned from PAYMENT_PROCESSING for retry)
Payment attempts: 1/3
```

#### Network Error
```
Tool: process_payment(...) → Network timeout

Agent: "Network error during payment processing. Please check your connection 
        and try again, or contact support if the issue persists."

State: VERIFIED (can retry)
Payment attempts: 1/3
```

#### Payment Retry Exhaustion
```
After 3rd payment failure:

Agent: "Payment was declined after multiple attempts. Final reason: [error]. 
        This session has been closed. Please contact our support team or 
        try again later with a different payment method."

State: FAILED (terminal)
```

---

### 5. Context-Aware Error Recovery

#### User Corrects Information Mid-Flow
```
Turn 1:
User:  "ACC1001, John Smith, 1990-05-14"
Agent: "Verification failed. 2 attempts remaining..."

Turn 2:
User:  "Sorry, I meant John Doe"
Agent: "Identity verified successfully! Your outstanding balance is..."

State: VERIFIED (name correction accepted)
Note: Agent doesn't ask for DOB again (already in state)
```

#### Out-of-Order Information Handling
```
Turn 1:
User:  "I want to pay 500 with card 4532-1234-5678-9010"
Agent: "Thank you for providing payment information. However, I need 
        your Account ID first to proceed."

Turn 2:
User:  "ACC1001"
Agent: "I found your account. For security, please provide verification..."

Turn 3:
User:  "John Doe, 1990-05-14"
Agent: "Verified! I still need: CVV, expiry month, expiry year, and 
        cardholder name to complete your payment of 500."

Note: Card number from Turn 1 is remembered and reused
```

---
        Account ID and try again."

State: WAITING_FOR_ACCOUNT_ID (stays in same state)
```

#### Network/Server Error
```
Tool:  lookup_account() → Network timeout

Agent: "We're experiencing technical difficulties. Please try again 
        later or contact support."

State: WAITING_FOR_ACCOUNT_ID (can retry indefinitely)
```

---

### 2. Identity Verification Failures

#### Retry Flow (Max 3 Attempts)

```
┌────────────────────────────────────────────────────────────┐
│ Attempt 1: Wrong DOB                                        │
├────────────────────────────────────────────────────────────┤
│ User:  "John Doe, 1995-01-01, 1234, 400001"                │
│ Verify: full_name ✓, dob ✗, aadhaar_last4 ?, pincode ?    │
│ Result: FAILED (dob doesn't match)                          │
│                                                              │
│ Agent: "Verification failed. You have 2 attempts remaining. │
│         Please provide your correct full name and at least  │
│         one matching detail."                               │
│                                                              │
│ State: VERIFYING (attempts: 1/3)                            │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ Attempt 2: Correct Aadhaar                                  │
├────────────────────────────────────────────────────────────┤
│ User:  "John Doe, aadhaar last 4 is 1234"                  │
│ Verify: full_name ✓, aadhaar_last4 ✓                       │
│ Result: SUCCESS                                             │
│                                                              │
│ Agent: "Identity verified! Your balance is ₹10,000..."     │
│                                                              │
│ State: VERIFYING → VERIFIED                                │
└────────────────────────────────────────────────────────────┘
```

#### Terminal Failure (3 Strikes)

```
┌────────────────────────────────────────────────────────────┐
│ Attempt 3: Still Wrong                                      │
├────────────────────────────────────────────────────────────┤
│ User:  "Jane Smith, 1990-05-15, 5678, 400002"              │
│ Verify: full_name ✗ (doesn't match "John Doe")             │
│ Result: FAILED (attempts exhausted)                         │
│                                                              │
│ Agent: "Verification failed after 3 attempts. For security  │
│         reasons, this session has been terminated. Please   │
│         contact support."                                   │
│                                                              │
│ State: VERIFYING → FAILED (terminal)                        │
└────────────────────────────────────────────────────────────┘
```

#### Verification Rules
- ✅ **Must match**: `full_name` (exact, case-sensitive)
- ✅ **Must match at least ONE of**: `dob`, `aadhaar_last4`, or `pincode`
- ⚠️ **No fuzzy matching**: "John Doe" ≠ "john doe"
- ⚠️ **No partial credit**: All-or-nothing per attempt

---

### 3. Payment Validation Failures

#### Missing Fields (Re-prompt)
```
User:  "I want to pay 5000"

Agent: "The following payment details are still needed: 
        card number, cvv, expiry month, expiry year, cardholder name.
        Please provide them."

State: VERIFIED (stays, no retry count)
```

#### Validation Errors (Re-prompt with Specific Errors)
```
User:  "5000, John Doe, 1234-5678-9012-3456, 12, 3, 2025"

Validators check:
  ✗ Card number fails Luhn check
  ✗ CVV is 2 digits (needs 3-4)
  ✗ Expiry 03/2025 is in the past (current: 04/2026)

Agent: "The following validation errors were found:
        - Card number is invalid (failed Luhn check)
        - CVV must be 3 or 4 digits
        - Card has expired
        Please correct these and try again."

State: VERIFIED (stays, can retry indefinitely with corrections)
```

#### Amount Exceeds Balance
```
User:  "I want to pay 50000"
Balance: 10000

Validator: Amount (50000) > balance (10000)

Agent: "Amount exceeds your available balance of 10000. 
        Please enter a valid amount."

State: VERIFIED (stays)
```

---

### 4. Payment Processing Failures

#### API Rejection
```
Tool: process_payment() → {status: "declined", reason: "Insufficient funds"}

Agent: "Payment declined. Reason: Insufficient funds. Please contact 
        your bank or try a different card."

State: PAYMENT_PROCESSING → FAILED (terminal)
```

#### Network Error During Processing
```
Tool: process_payment() → RuntimeError("Network timeout")

Agent: "Payment processing failed: Network timeout. We apologize for 
        the inconvenience. Please contact support or try again later."

State: PAYMENT_PROCESSING → FAILED (terminal)
```

---

## Detailed Flow Diagrams

### Complete State Transition Diagram

```
                    ┌──────┐
                    │ INIT │
                    └───┬──┘
                        │
                        ▼
            ┌───────────────────────┐
            │ WAITING_FOR_ACCOUNT_ID│◄─────┐
            └───┬───────────────────┘      │
                │ ✓ Valid account          │ ✗ Invalid/retry (attempts < 3)
                ▼                           │
         ┌──────────────┐                  │
         │ACCOUNT_FETCHED│                  │
         └───┬──────────┘        ✗ 3 lookup failures
             │                              │
             ▼                              ▼
        ┌──────────┐                  ┌────────┐
        │VERIFYING │◄─────────────┐   │ FAILED │
        └───┬──────┘  ✗ Retry     │   └────────┘
            │          (< 3)      │        ▲
            ├─► ✗ 3 failed ───────┼────────┘
            │                     │
            │ ✓ Identity verified │
            ▼                     │
       ┌──────────┐               │
       │ VERIFIED │◄──────────────┘
       └───┬──────┘  Missing/invalid fields
           │
           ▼
   ┌──────────────────┐
   │PAYMENT_PROCESSING│
   └───┬──────────────┘
       │
       ├─► ✗ API error/declined ──► FAILED (after 3 attempts)
       │
       │ ✓ Payment success
       ▼
  ┌───────────┐
  │ COMPLETED │
  └───────────┘
```

### Data Flow per Stage

#### Stage 1: Account Lookup
```
User Input (raw text)
    │
    ▼
LLM Extraction → {"account_id": "..."}
    │
    ▼
Validator (validate_account_id)
    │
    ├─► ✗ Invalid format → Re-prompt
    │
    ▼ ✓ Valid format
API Call (lookup_account)
    │
    ├─► ✗ Not found → Re-prompt
    │
    ▼ ✓ Found
StateManager.set_account_data({
    full_name: "...",
    dob: "...",
    aadhaar_last4: "...",
    pincode: "...",
    balance: ...
})
    │
    ▼
Transition: ACCOUNT_FETCHED → VERIFYING
```

#### Stage 2: Identity Verification
```
User Input (raw text)
    │
    ▼
LLM Extraction → {
    "full_name": "...",
    "dob": "...",
    "aadhaar_last4": "...",
    "pincode": "..."
}
    │
    ▼
StateManager.update_user_input(field, value) [for each field]
    │
    ▼
Check: full_name present? ───► ✗ → Re-prompt
    │ ✓
    ▼
Check: ≥1 secondary field? ──► ✗ → Re-prompt
    │ ✓
    ▼
Validator (verify_identity)
    │
    ├─► ✗ Mismatch → Increment attempts
    │       │
    │       ├─► attempts < 3 → Re-prompt
    │       └─► attempts = 3 → FAILED
    │
    ▼ ✓ Match
StateManager.mark_verified()
    │
    ▼
Transition: VERIFIED
```

#### Stage 3: Payment Collection
```
User Input (raw text)
    │
    ▼
LLM Extraction → {
    "amount": ...,
    "cardholder_name": "...",
    "card_number": "...",
    "cvv": "...",
    "expiry_month": ...,
    "expiry_year": ...
}
    │
    ▼
StateManager.update_payment_field(field, value) [for each]
    │
    ▼
Check: all fields present? ──► ✗ → Re-prompt with missing
    │ ✓
    ▼
Validators (validate_all_payment_fields)
  ├─ validate_amount(amount, balance)
  ├─ validate_card_number(card_number) [Luhn check]
  ├─ validate_cvv(cvv)
  ├─ validate_expiry(month, year)
  └─ Check cardholder_name non-empty
    │
    ├─► ✗ Errors → Re-prompt with specific errors
    │
    ▼ ✓ All valid
API Call (process_payment)
    │
    ├─► ✗ API error → FAILED
    ├─► ✗ Declined → FAILED
    │
    ▼ ✓ Success
StateManager.set_payment_result(status, txn_id)
    │
    ▼
Transition: COMPLETED
```

---

## Security & Validation

### Security Measures

#### 1. No Sensitive Data in LLM Prompts
- ✅ Account verification data (name, DOB, Aadhaar, pincode) is **never injected into the LLM context** — the LLM only sees the balance and stage guidance
- ✅ The expected customer name is withheld from the system prompt and tool responses; the LLM cannot "cheat" by comparing the user's input against the injected ground truth
- ✅ Verification logic runs entirely in Python (`verify_identity`), comparing against `account_data` stored in the state manager
- ✅ Card validation uses a local Luhn algorithm — no card data sent to additional services

#### 2. Exact Matching for Identity
- ✅ Case-sensitive name matching
- ✅ No fuzzy logic (prevents social engineering)
- ✅ Multi-factor: name + 1 secondary field

#### 3. Retry Limits
- ✅ 3-attempt limit on **account lookup** (API errors / not-found) before session terminates
- ✅ 3-attempt limit on **identity verification** prevents brute force
- ✅ 3-attempt limit on **payment processing** failures
- ✅ Terminal FAILED state requires contacting support

#### 4. Exact Amount Forwarding
- ✅ The payment amount is passed to the API **exactly as stated by the user**
- ✅ The LLM tool definition and system prompt explicitly prohibit rounding or modifying the value
- ✅ Example: if the user says `1000.005`, the API receives `1000.005`

#### 5. Input Sanitization
- ✅ Card numbers stripped of spaces/hyphens before processing
- ✅ CVV converted to string for validation
- ✅ Expiry parsed as integers

### Validation Checklist

| Field | Validation Rules |
|-------|------------------|
| **account_id** | 4-30 alphanumeric chars (hyphens/underscores OK) |
| **full_name** | Exact match (case-sensitive) |
| **dob** | Format: YYYY-MM-DD; exact match |
| **aadhaar_last4** | Exactly 4 digits; exact match |
| **pincode** | Exactly 6 digits; exact match |
| **amount** | Number > 0; ≤ account balance |
| **card_number** | 13-19 digits; passes Luhn check |
| **cvv** | 3 or 4 digits |
| **expiry_month** | Integer 1-12 |
| **expiry_year** | 4-digit integer; must be future date |
| **cardholder_name** | Non-empty string |

---

## Common Scenarios

### Scenario 1: User Provides All Info at Once
```
User: "Hi, my account is ACC-12345, I'm John Doe born 1990-05-15, 
       aadhaar 1234, pincode 400001, I want to pay 5000 with card 
       4532123456789010, cvv 123, expires 12/2027"

Flow:
1. Extract account_id → validate → lookup → ✓
2. Extract identity fields → verify → ✓
3. Extract payment fields → validate → process → ✓

Result: Payment completes in 1 turn! (Still goes through all states)
```

### Scenario 2: Incremental Information
```
Turn 1:
  User:  "My account is ACC-12345"
  Agent: "Account found. Please provide your verification details..."

Turn 2:
  User:  "John Doe"
  Agent: "We also need your DOB, Aadhaar last 4, or pincode..."

Turn 3:
  User:  "Aadhaar 1234"
  Agent: "Verified! Outstanding balance is ₹10,000..."

Turn 4:
  User:  "Pay 5000"
  Agent: "Please provide your card details..."

Turn 5:
  User:  "Card 4532123456789010, cvv 123, expires 12/2027, John Doe"
  Agent: "Payment successful! Transaction ID: TXN-789"
```

### Scenario 3: Typos and Corrections
```
User:  "My account is AC-123" [too short]
Agent: "Account ID must be 4-30 characters..."

User:  "ACC-12345"
Agent: "Account found..."

User:  "Jon Doe" [typo in name]
Agent: "Verification failed. 2 attempts remaining..."

User:  "John Doe, aadhaar 1234"
Agent: "Verified!..."
```

---

## Troubleshooting Guide

### Agent Stuck in WAITING_FOR_ACCOUNT_ID
**Cause**: User not providing recognizable account ID
**Fix**: LLM should extract any alphanumeric string; check extraction prompt

### Verification Always Fails
**Cause**: Case sensitivity or whitespace issues
**Fix**: Check account_data exactly matches user input (case-sensitive)

### Payment Validation Rejects Valid Card
**Cause**: Luhn algorithm implementation or expiry date comparison
**Fix**: Verify card number passes online Luhn checker; check system date

### LLM Not Extracting Fields
**Cause**: Extraction prompt too strict or LLM model issue
**Fix**: Review EXTRACTION_SYSTEM prompt; verify Bedrock model ID

---

## Multi-Stage Processing Architecture

### Overview

Multi-stage processing is an emergent property of the **Strands agentic loop** — there is no custom orchestration code. When a user provides complete information in a single message, the LLM calls tools sequentially within one `Agent.next()` call, advancing through all applicable state transitions before returning a final response.

### How It Works

Within a single `Agent.next()` call, Strands drives the following loop:

```
1. System prompt rebuilt (reflects current stage + partial state)
2. LLM reads user message and decides to call do_lookup_account
3. Tool fires → StateManager advances WAITING_FOR_ACCOUNT_ID → VERIFYING
4. Tool return message guides LLM to call do_verify_identity
5. Tool fires → StateManager advances VERIFYING → VERIFIED
6. Tool return message guides LLM to call do_process_payment
7. Tool fires → StateManager advances VERIFIED → COMPLETED
8. LLM produces final consolidated response
```

If any tool fails or fields are missing, the LLM stops and returns a response asking for the missing information.

### Benefits

#### 1. Dramatically Reduced Conversation Length
- **Traditional**: 3-5 turns for complete payment
- **Multi-Stage**: 1-2 turns when full info provided upfront

#### 2. Backward Compatibility
- Incremental disclosure still fully supported
- Agent adapts naturally to the user's information-sharing style

#### 3. Maintains Security
- Every tool includes its own stage check
- `BeforeToolCallEvent` guardrail provides a second layer
- No shortcuts in verification or payment validation

### Example Comparison

#### Traditional Flow (3 turns):
```
Turn 1: "ACC1001" → "Account found, please verify identity"
Turn 2: "John Doe, 1990-05-14" → "Verified! Provide payment details"
Turn 3: "500, John Doe, 4532..., 123, 12/2027" → "Payment successful!"
```

#### Multi-Stage Flow (1 turn):
```
Turn 1: "ACC1001, John Doe, 1990-05-14, pay 500, card 4532...,
         CVV 123, exp 12/2027, John Doe" → "Payment successful!"
```

### Edge Cases

#### Case 1: Partial Multi-Stage
```
User provides: Account ID + Verification (no payment details)

✓ Account lookup succeeds
✓ Verification succeeds
✗ Payment tool not called (LLM stops, asks for payment details)

Response: "Verified! Please provide payment details..."
State: VERIFIED (2 stages completed in 1 turn)
```

#### Case 2: Invalid Identity
```
User provides: Account ID + Wrong Name + Payment Details

✓ Account lookup succeeds
✗ Verification fails (name mismatch)
→ Payment tool never called

Response: "Verification failed. 2 attempts remaining..."
State: VERIFYING
```

#### Case 3: Payment Validation Failure
```
User provides: Everything, but card fails Luhn check

✓ Account lookup succeeds
✓ Verification succeeds
✗ do_process_payment returns VALIDATION_ERROR before calling API

Response: "Card number is invalid (failed Luhn check)..."
State: VERIFIED (can provide corrected card info)
```

---

## Future Enhancements

### Potential Additions
1. **Session timeout**: Auto-fail after 30 minutes
2. **Partial payments**: Allow multiple payment methods
3. **Receipt generation**: Email transaction confirmation
4. **Multi-language**: Support regional languages
5. **Voice input**: Integrate with speech-to-text
6. **Audit logging**: Track all state transitions for compliance
7. **Smart retry logic**: Distinguish user errors from system errors
8. **Payment modification**: Allow users to update amount before final confirmation

---

## Summary

This agent follows a **strict state machine** where:
- ✅ Each stage has clear entry/exit criteria
- ✅ LLM handles only extraction and response generation
- ✅ All logic is deterministic Python code
- ✅ Retries are bounded to prevent infinite loops
- ✅ Security is enforced via validators, not prompts
- ✅ **NEW**: Multi-stage processing for efficient single-turn completions
- ✅ **NEW**: Context-aware extraction for natural conversations

**Key Insight**: By separating extraction (LLM) from validation (code), we get the benefits of natural language understanding WITHOUT the unpredictability of LLM-based decision making. The multi-stage processing enhancement adds efficiency without compromising on security or determinism.
