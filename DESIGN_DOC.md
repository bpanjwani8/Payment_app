# Payment Collection AI Agent - Design Document

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Key Design Decisions](#key-design-decisions)
3. [System Components](#system-components)
4. [Multi-Stage Processing](#multi-stage-processing)
5. [Conversation Flow](#conversation-flow)
6. [Security & Validation](#security--validation)
7. [Tradeoffs & Limitations](#tradeoffs--limitations)
8. [Future Improvements](#future-improvements)

---

## 1. Architecture Overview

### High-Level Design Philosophy

This payment collection agent is built on a **hybrid architecture** that combines:
- **Deterministic state machine** for business logic and decision-making
- **LLM (AWS Bedrock)** exclusively for natural language understanding and response generation
- **Pure Python validators** for all critical business rules

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Input (Natural Language)                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              Strands Agent (strands-agents SDK)                 │
│  • Drives the agentic loop (LLM ↔ tool calls ↔ observations)   │
│  • State-aware system prompt refreshed before each turn         │
│  • BeforeToolCallEvent guardrail hook enforces stage order      │
│  • Calls tools sequentially within one turn (multi-stage)       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              LLM (AWS Bedrock — Claude Sonnet 4.5)              │
│  • Extracts structured data from natural language               │
│  • Decides which tool to call next based on tool results        │
│  • Generates final human-friendly response                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
         ┌──────────────┬─────────────┬──────────────┐
         ↓              ↓             ↓              ↓
┌──────────────┐ ┌─────────────┐ ┌──────────┐ ┌──────────────┐
│ State Manager│ │ Validators  │ │  Tools   │ │  Guardrail   │
│              │ │             │ │          │ │    Hook      │
│ • Stage      │ │ • Account   │ │ • lookup │ │ • Cancels    │
│ • User data  │ │ • Identity  │ │ • payment│ │   out-of-    │
│ • Attempts   │ │ • Payment   │ │          │ │   order tool │
│ • Transitions│ │ • Luhn algo │ │          │ │   calls      │
└──────────────┘ └─────────────┘ └──────────┘ └──────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              Natural Language Response to User                  │
└─────────────────────────────────────────────────────────────────┘
```

### Core Principle: Separation of Concerns

**Strands / LLM Responsibilities (Non-deterministic):**
- Extract structured data from natural language via tool-calling
- Decide which tool to invoke next based on tool results
- Generate human-friendly responses
- Maintain conversational context across turns

**Python Responsibilities (Deterministic):**
- All business logic and validation
- State transitions and flow control
- API interactions and error handling
- Security-critical operations

---

## 2. Key Design Decisions

### Decision 1: LLM for Extraction Only, Not Validation

**Rationale:**
- LLMs are non-deterministic and can "hallucinate" or be prompt-injected
- Financial operations require absolute reliability
- Regulations (PCI-DSS, data privacy) demand deterministic validation

**Implementation:**
- Extraction prompt explicitly instructs "NEVER guess or infer"
- All validation happens in Python code (`validators.py`)
- LLM output is treated as untrusted user input

**Example:**
```python
# ❌ WRONG: Asking LLM to validate
"Is this account ID valid? Answer yes/no"

# ✅ RIGHT: Python validation
def validate_account_id(account_id: str) -> tuple[bool, str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,30}", account_id):
        return False, "Invalid format"
    return True, ""
```

---

### Decision 2: Multi-Stage Processing in Single Turn

**Problem:** Traditional chatbots require multiple back-and-forth turns even when the user provides complete information upfront.

**Solution:** Leverage the Strands agentic loop — the LLM can call multiple tools sequentially within a single user turn, advancing through all applicable state transitions before returning a response.

**How it Works:**
1. The user sends a single message with all their information
2. The LLM (via Strands) reads the state-aware system prompt and the user message
3. The LLM calls `do_lookup_account` → tool succeeds, state advances to VERIFYING
4. The LLM reads the tool result and calls `do_verify_identity` → state advances to VERIFIED
5. The LLM reads the tool result and calls `do_process_payment` → state advances to COMPLETED
6. Strands returns a single consolidated response

**Example Scenario:**
```
User: "My account is ACC1001, I'm John Doe born 1990-05-14, 
       last 4 of Aadhaar 4321, paying 500 with card 
       4532-1234-5678-9010, CVV 123, expiry 12/2027, 
       cardholder John Doe"

Strands agentic loop (single turn):
  ✓ LLM calls do_lookup_account("ACC1001") → SUCCESS
  ✓ LLM calls do_verify_identity("John Doe", dob="1990-05-14") → SUCCESS
  ✓ LLM calls do_process_payment(500, ...) → SUCCESS
  → "Payment successful! Transaction ID: TXN-123"
```

**Benefits:**
- Dramatically reduces conversation length for power users
- Maintains backward compatibility with incremental disclosure
- Improves user experience without sacrificing security
- No custom orchestration code — Strands handles the tool-calling chain

---

### Decision 3: Strict Identity Verification Logic

**Requirements:**
- Full name must match **exactly** (case-sensitive)
- At least ONE secondary field must match exactly:
  - Date of birth (YYYY-MM-DD format)
  - Last 4 digits of Aadhaar
  - Pincode

**Why Strict Matching?**
- No fuzzy matching ("John" ≠ "Jon", "Doe" ≠ "Do")
- Prevents social engineering attacks
- Reduces false positives in identity verification

**Name Not Leaked to the LLM:**
- The expected customer name (and other account details) are stored only in `account_data` inside the `StateManager`
- They are **never injected into the system prompt or tool response** visible to the LLM
- The LLM collects the user's claim and passes it verbatim to `do_verify_identity`; the Python code performs the comparison invisibly
- This prevents the LLM from inadvertently hinting at, confirming, or leaking the correct name before the user provides it

**Retry Mechanism:**
- Maximum 3 attempts allowed for verification
- Maximum 3 attempts allowed for account lookup (API errors / not-found)
- Each counter is tracked separately in the state
- Session terminates after 3 failures in either category (transitions to FAILED state)

---

### Decision 4: Two-Tool Architecture

**Only Two External API Calls:**

1. **`lookup_account(account_id)`**
   - Called once per session after account ID validation
   - Returns: full_name, dob, aadhaar_last4, pincode, balance
   - Cached in state manager

2. **`process_payment(...)`**
   - Called only after all validations pass
   - Sends complete payment payload to external API
   - Returns: success status, transaction_id, error_code

**Why No Verification Tool?**
- Verification data is already retrieved in `lookup_account`
- Comparison happens in pure Python code
- Reduces attack surface (no PII sent to additional APIs)
- Faster verification (no network round-trip)

---

### Decision 5: State-Aware System Prompt

**Challenge:** Users often use pronouns or references to previous statements:
- "Yes, that's correct"
- "Same as before"
- "The card name is the same as my name"

**Solution:** Rebuild and inject a state-aware system prompt before each turn. The prompt includes the current stage, collected field values, remaining attempts, and exact tool-calling instructions tailored to that stage.

**Benefits:**
- Handles anaphora resolution ("it", "that", "same") via Strands conversation history
- Prevents the LLM from calling tools out of order
- Surfaces partial state (e.g., already-collected fields) so the LLM asks only for what is missing
- More natural, context-aware conversation flow

**Trade-off:**
- Prompt regeneration on every turn adds minor overhead
- Strands conversation history (managed internally by the SDK) grows with turn count

---

## 3. System Components

### 3.1 State Manager (`state_manager.py`)

**Responsibility:** Single source of truth for conversation state

**State Structure:**
```python
{
    "stage": "INIT" | "WAITING_FOR_ACCOUNT_ID" | "ACCOUNT_FETCHED" | 
             "VERIFYING" | "VERIFIED" | "PAYMENT_PROCESSING" | 
             "COMPLETED" | "FAILED",
    
    "account_id": str,
    "account_data": {
        "full_name": str,
        "dob": str,
        "aadhaar_last4": str,
        "pincode": str,
        "balance": float
    },
    
    "lookup": {
        "attempts": int,
        "max_attempts": 3
    },
    
    "user_inputs": {
        "full_name": str,
        "dob": str,
        "aadhaar_last4": str,
        "pincode": str
    },
    
    "verification": {
        "is_verified": bool,
        "attempts": int,
        "max_attempts": 3
    },
    
    "payment": {
        "amount": float,
        "card_details": {
            "cardholder_name": str,
            "card_number": str,
            "cvv": str,
            "expiry_month": int,
            "expiry_year": int
        },
        "status": str,
        "transaction_id": str,
        "attempts": int,
        "max_attempts": 3
    }
}
```

**Transition Guards:**
```python
TRANSITIONS = {
    "INIT":                  ["WAITING_FOR_ACCOUNT_ID"],
    "WAITING_FOR_ACCOUNT_ID":["ACCOUNT_FETCHED", "WAITING_FOR_ACCOUNT_ID", "FAILED"],
    "ACCOUNT_FETCHED":       ["VERIFYING"],
    "VERIFYING":             ["VERIFIED", "VERIFYING", "FAILED"],
    "VERIFIED":              ["PAYMENT_PROCESSING", "VERIFIED"],
    "PAYMENT_PROCESSING":    ["COMPLETED", "VERIFIED", "FAILED"],
    "COMPLETED":             [],  # Terminal
    "FAILED":                []   # Terminal
}
```

Illegal transitions raise `ValueError`.

---

### 3.2 Validators (`validators.py`)

**Pure Python validation functions:**

| Validator | Rule | Implementation |
|-----------|------|----------------|
| `validate_account_id` | 4-30 alphanumeric chars | Regex: `[A-Za-z0-9_-]{4,30}` |
| `verify_identity` | Exact name + ≥1 secondary | Pure comparison, no fuzzy |
| `validate_amount` | > 0 and ≤ balance | Numeric comparison |
| `validate_card_number` | Luhn algorithm | Custom implementation |
| `validate_cvv` | 3-4 digits | Regex: `\d{3,4}` |
| `validate_expiry` | Not expired, month 1-12 | Date comparison |

**Luhn Algorithm Implementation:**
```python
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
```

---

### 3.3 Tools (`tools.py`)

**API Integration Layer:**

Both tools use Python `requests` library with comprehensive error handling:

```python
def lookup_account(account_id: str) -> dict:
    url = f"{BASE_URL}/api/lookup-account"
    try:
        resp = requests.post(url, json={"account_id": account_id}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        # Parse error response for user-friendly messages
        if e.response.status_code == 404:
            raise RuntimeError("Account not found. Please verify...")
        raise RuntimeError(f"Account lookup failed...")
    except requests.exceptions.RequestException as e:
        raise RuntimeError("Network error during account lookup...")
```

**Error Handling Strategy:**
- HTTP errors → Parsed and converted to user-friendly messages
- Network errors → Generic retry message
- All exceptions converted to `RuntimeError` with actionable guidance

---

### 3.4 Agent (`agent.py`)

**Main Orchestrator:**

```python
class Agent:
    def __init__(self):
        self.sm = StateManager()
        # Tool closures that share this StateManager instance
        self._tools = _make_tools(self.sm)
        # Strands agent drives the LLM ↔ tool-calling agentic loop
        self._strands = StrandsAgent(
            model=BedrockModel(...),
            tools=self._tools,
            system_prompt=_build_system_prompt(self.sm),
        )
        # Guardrail: cancel out-of-order tool calls before they fire
        self._strands.hooks.add_callback(BeforeToolCallEvent, _state_guard)

    def next(self, user_input: str) -> dict:
        # Rebuild system prompt to reflect current state before each turn
        self._strands.system_prompt = _build_system_prompt(self.sm)
        result = self._strands(user_input)
        return {"message": str(result)}
```

**Processing Pipeline (Strands agentic loop):**

1. **System prompt** is rebuilt with current stage context before each turn
2. **Strands** sends user message + system prompt to the LLM (Bedrock)
3. **LLM decides** which tool to call based on current context
4. **Guardrail hook** (`BeforeToolCallEvent`) cancels calls that violate stage order
5. **Tool executes** — StateManager is updated, tool returns guidance to the LLM
6. **LLM decides** whether to call the next tool or return a final response
7. Steps 3-6 repeat until the LLM produces a final text response
8. **Single consolidated response** is returned to the caller

**Tool Closures (`_make_tools`):**

Each session creates fresh `@tool`-decorated closures that close over the session's `StateManager`. This gives each conversation fully isolated state while reusing the same tool logic:
- `do_lookup_account(account_id)` — validates and fetches account; transitions `WAITING_FOR_ACCOUNT_ID → VERIFYING`
- `do_verify_identity(full_name, dob, aadhaar_last4, pincode)` — compares against account data; transitions `VERIFYING → VERIFIED` or `FAILED`
- `do_process_payment(amount, card_number, cvv, expiry_month, expiry_year, cardholder_name)` — validates then calls API; transitions `VERIFIED → COMPLETED` or `FAILED`

**Guardrail Hook:**

```python
def _state_guard(event: BeforeToolCallEvent):
    tool_name = event.tool_use["name"]
    stage = sm_ref.stage
    if tool_name == "do_lookup_account" and stage != "WAITING_FOR_ACCOUNT_ID":
        event.cancel_tool = "Account lookup already completed."
    elif tool_name == "do_verify_identity" and stage != "VERIFYING":
        event.cancel_tool = f"Cannot verify identity in stage '{stage}'."
    elif tool_name == "do_process_payment" and stage != "VERIFIED":
        event.cancel_tool = f"Cannot process payment in stage '{stage}'."
```

This is the second line of defence against out-of-order tool calls (the first being per-tool stage checks inside the tool itself).

---

### 3.5 Streamlit Web UI (`app.py`)

**Responsibility:** Browser-based chat interface — an alternative to the terminal runner.

**Run command:**
```bash
streamlit run app.py
```

**Design:**
- Each browser tab instantiates a fresh `Agent` and stores it in `st.session_state`, giving every tab fully isolated state.
- Conversation history is rendered via `st.chat_message`, mirroring the `messages` list in session state.
- A **Start Session** button fires the initial greeting turn so the chat history always begins with an agent message.
- Input is disabled and a status banner is shown once the session reaches `COMPLETED` or `FAILED`; a **Start New Session** button resets state without a page reload.
- No changes to `agent.py`, `state_manager.py`, or any other module — `app.py` is a pure UI layer on top of `Agent.next()`.

---

## 4. Multi-Stage Processing

### How It Works

Multi-stage processing is an emergent property of the **Strands agentic loop** combined with the state machine. There is no custom orchestration code — the LLM calls tools sequentially within a single `Agent.next()` call, guided by tool return messages and the state-aware system prompt.

**Turn lifecycle for a single `Agent.next()` call:**
```
1. Rebuild system prompt (reflects current stage + partial state)
2. Strands sends user message to LLM
3. LLM calls do_lookup_account   → state: WAITING_FOR_ACCOUNT_ID → VERIFYING
4. LLM reads tool result, calls do_verify_identity → state: VERIFYING → VERIFIED
5. LLM reads tool result, calls do_process_payment → state: VERIFIED → COMPLETED
6. LLM produces final text response
7. Strands returns consolidated response
```

Each tool return message explicitly instructs the LLM on what to collect next, enabling the chain.

### Example: Single Turn Complete Payment

**User Input:**
```
"Account ACC1001, John Doe, 1990-05-14, 4321, paying 500
with card 4532123456789010, CVV 123, exp 12/2027,
cardholder John Doe"
```

**Strands agentic loop (within one `Agent.next()` call):**
1. ✅ LLM calls `do_lookup_account("ACC1001")` → account found, balance = 1250.75
2. ✅ LLM calls `do_verify_identity("John Doe", dob="1990-05-14")` → verified
3. ✅ LLM calls `do_process_payment(500, ...)` → all validations pass, API succeeds
4. → State: COMPLETED; Response: `"Payment successful! Transaction ID: TXN-123"`

**Total turns: 1** (vs. traditional 3-5 turns)

---

## 5. Conversation Flow

### State Diagram

```
┌──────┐
│ INIT │
└──┬───┘
   │ Greeting
   ↓
┌─────────────────────┐
│WAITING_FOR_ACCOUNT_ID│
└──┬──────────────────┘
   │ Account ID provided + validated
   ↓
┌─────────────────┐
│ ACCOUNT_FETCHED │ (Transient - immediately goes to VERIFYING)
└──┬──────────────┘
   │
   ↓
┌───────────┐
│ VERIFYING │←─────┐
└──┬────────┘      │ Retry (attempt < 3)
   │               │
   │ Success       │ Failure
   ↓               │
┌──────────┐       │
│ VERIFIED │───────┘
└──┬───────┘
   │ Payment details provided + validated
   ↓
┌────────────────────┐
│ PAYMENT_PROCESSING │
└──┬─────────────────┘
   │
   ├─ Success ──→ ┌───────────┐
   │              │ COMPLETED │ (Terminal)
   │              └───────────┘
   │
   └─ Failure ──→ ┌────────┐
                  │ FAILED │ (Terminal)
                  └────────┘
```

---

## 6. Security & Validation

### 6.1 Data Security Principles

1. **No Sensitive Data in Responses:**
   - Full card numbers never echoed back
   - DOB, Aadhaar never displayed
   - Only last 4 of card shown (if needed)

2. **Sensitive Account Data Never Sent to the LLM:**
   - The customer name, DOB, Aadhaar last 4, and pincode from `account_data` are stored only in `StateManager`
   - They are withheld from both the system prompt and `do_lookup_account` tool return values
   - The LLM cannot inadvertently hint at or expose the expected verification values
   - All identity comparison happens in `verify_identity()` (pure Python), invisible to the LLM

3. **Exact Amount Forwarding:**
   - The payment amount is forwarded to the API exactly as the user stated it
   - The `do_process_payment` tool docstring and the VERIFIED system-prompt stage both explicitly instruct the LLM not to round or otherwise modify the value
   - Example: user says `1000.005` → API receives `1000.005`

4. **Validation Before Transmission:**
   - All input validated locally before API calls
   - Prevents injection attacks via malformed data

5. **Conversation History Trimming:**
   - Only last 6 messages kept for LLM context
   - Reduces exposure of sensitive data in prompts

### 6.2 Validation Layers

**Layer 1: Format Validation**
- Regex patterns for account ID, CVV, card number format
- Type checking (int, float, string)

**Layer 2: Business Logic Validation**
- Luhn algorithm for card numbers
- Expiry date comparison against current date
- Amount ≤ account balance

**Layer 3: Identity Verification**
- Exact string matching (case-sensitive)
- Multi-factor approach (name + secondary field)
- Runs entirely in Python — no external API call
   - Account data (name, DOB, Aadhaar, pincode) is **never exposed to the LLM**; comparison is opaque to the language model

**Layer 5: API Response Validation**
- HTTP status code checking
- JSON error-code interpretation with user-friendly messages

---

## 7. Tradeoffs & Limitations

### Tradeoffs Accepted

#### 1. **Strands SDK Conversation History vs. Token Cost**
- **Decision:** Use Strands' built-in conversation history management
- **Tradeoff:** History grows with turn count; very long sessions may incur higher token costs
- **Rationale:** Payment flows are typically 3-10 turns; Strands manages the window automatically

#### 2. **Strict Matching vs. User Friction**
- **Decision:** No fuzzy matching on names/fields
- **Tradeoff:** Users must provide exact matches (case-sensitive)
- **Rationale:** Security and reliability trump convenience in financial operations

#### 3. **Multi-Stage Processing via Strands**
- **Decision:** Rely on Strands agentic loop for multi-tool chaining instead of custom orchestration
- **Tradeoff:** Less explicit control over the tool-calling sequence
- **Rationale:** Simpler codebase; Strands + guardrail hooks provide sufficient control

#### 4. **Retry Limits**
- **Decision:** 3 attempts for verification and payment
- **Tradeoff:** Legitimate users might get locked out
- **Rationale:** Prevents brute-force attacks; users can contact support

### Current Limitations

1. **No Partial Payment Plans:**
   - Only supports single payment per session
   - Cannot set up installment plans

2. **No Payment Modification:**
   - Once payment processing starts, cannot be canceled
   - No "go back" functionality from PAYMENT_PROCESSING

3. **Limited Error Recovery:**
   - After 3 failed attempts, session terminates completely
   - User must start new session (cannot resume)

4. **No Authentication:**
   - Assumes external authentication layer
   - Does not handle login/logout

5. **English Only:**
   - No multi-language support
   - Prompts and responses hardcoded in English

---

## 8. Future Improvements

1. **Enhanced Error Messages:**
   - Add specific guidance for common card errors
   - Include support phone numbers in terminal failures

2. **Payment Receipt Generation:**
   - Generate PDF/email receipt after successful payment
   - Include transaction details and timestamp

3. **Session Resumption:**
   - Allow users to resume after temporary failures
   - Store session state in database with expiry

4. **Audit Logging:**
   - Log all state transitions with timestamps
   - Track failed verification attempts for fraud detection

5. **Multi-Language Support:**
   - Detect user language preference
   - Localized prompts and responses

6. **Voice Interface:**
   - Integrate with telephony systems
   - Speech-to-text → Agent → Text-to-speech

7. **Analytics Dashboard:**
   - Conversion funnel visualization
   - Common drop-off points
   - Average conversation length
   - Success rate by stage

---

## Conclusion

This payment collection agent demonstrates a **production-ready architecture** that balances:
- **User Experience:** Multi-stage processing for power users, incremental for casual users
- **Security:** Strict validation, no LLM-based business logic, PII protection
- **Reliability:** Deterministic state machine, comprehensive error handling
- **Maintainability:** Clear separation of concerns, type-safe Python code

The hybrid approach—using LLMs for what they're good at (language understanding) while keeping critical logic in deterministic code—provides the best of both worlds: natural conversation with financial-grade reliability.

**Key Innovation:** The multi-stage processing capability sets this apart from traditional chatbots by respecting the user's time while maintaining security and compliance requirements.

---

**Document Version:** 1.1  
**Last Updated:** May 14, 2026  
**Author:** Bhavesh Panjwani
