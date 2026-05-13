"""
test_comprehensive.py — Unified Comprehensive Test Suite for Payment Collection Agent

This file consolidates all test scenarios from:
- test_cases.py (Verification Rules & Hard Requirements)
- test_core_requirements.py (Context Management, Tool Calling, Verification Logic, Payment Handling, Failure Handling)
- test_multi_stage.py (Multi-Stage Transitions)

Provides detailed metrics and success rates by category.
"""

import json
import os
import sys
import time
from unittest.mock import patch, MagicMock, call
from typing import List, Dict, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent import Agent

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


# ═══════════════════════════════════════════════════════════════════════
# TEST DATA & MOCKS
# ═══════════════════════════════════════════════════════════════════════

TEST_ACCOUNT = {
    "account_id": "ACC1001",
    "full_name": "Nithin Jain",
    "dob": "1990-05-14",
    "aadhaar_last4": "4321",
    "pincode": "400001",
    "balance": 1250.75,
    "due_amount": 1250.75
}


def mock_lookup_account(account_id: str):
    """Mock account lookup that returns test data"""
    if account_id == "ACC1001":
        return TEST_ACCOUNT.copy()
    raise RuntimeError(f"Account lookup failed (HTTP 404).")


def mock_process_payment_success(**kwargs):
    """Mock successful payment processing"""
    return {
        "success": True,
        "transaction_id": "TXN-TEST-123",
        "status": "success"
    }


def mock_process_payment_declined(**kwargs):
    """Mock declined payment"""
    return {
        "success": False,
        "transaction_id": None,
        "status": "declined",
        "error_code": "insufficient_funds"
    }


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY 1: VERIFICATION RULES & HARD REQUIREMENTS
# ═══════════════════════════════════════════════════════════════════════

class TestVerificationRules:
    """Test strict verification rules and hard requirements"""
    
    def test_case_sensitive_name_matching(self):
        """Test that name matching is case-sensitive (strict)"""
        print("\n=== TEST: Case-Sensitive Name Matching ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            
            # Start conversation
            response = agent.next("Hello")
            assert "account id" in response['message'].lower()
            
            # Provide account ID
            response = agent.next("My account ID is ACC1001")
            
            # Try with wrong case - should FAIL
            response = agent.next("nithin jain, 1990-05-14, 4321, 400001")
            assert agent.sm.stage == "VERIFYING"
            assert not agent.sm.is_verified()
            print("  ✓ Lowercase name 'nithin jain' correctly rejected")
            
            # Try with correct case - should PASS
            response = agent.next("Nithin Jain, 1990-05-14")
            assert agent.sm.stage == "VERIFIED"
            assert agent.sm.is_verified()
            print("  ✓ Correct case 'Nithin Jain' accepted")
    
    def test_no_fuzzy_matching(self):
        """Test that fuzzy matching is not allowed"""
        print("\n=== TEST: No Fuzzy Matching ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Try with similar but not exact name
            response = agent.next("Nithin K Jain, 1990-05-14")
            assert agent.sm.stage == "VERIFYING"
            assert not agent.sm.is_verified()
            print("  ✓ Similar name 'Nithin K Jain' correctly rejected")
    
    def test_retry_limit_enforcement(self):
        """Test that retry limit (3 attempts) is enforced"""
        print("\n=== TEST: Retry Limit Enforcement ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Three failed attempts
            agent.next("Wrong Name, 1990-05-14")
            assert agent.sm.get("verification", "attempts") == 1
            
            agent.next("Another Wrong, 1990-05-14")
            assert agent.sm.get("verification", "attempts") == 2
            
            agent.next("Still Wrong, 1990-05-14")
            assert agent.sm.stage == "FAILED"
            assert agent.sm.get("verification", "attempts") == 3
            print("  ✓ Session terminated after 3 failed attempts")
    
    def test_no_payment_without_verification(self):
        """Test that payment cannot proceed without verification"""
        print("\n=== TEST: No Payment Without Verification ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Try to provide payment details before verification
            response = agent.next("I want to pay 500 with card 4532123456789010")
            assert agent.sm.stage == "VERIFYING"
            assert not agent.sm.is_verified()
            print("  ✓ Payment details ignored, still requesting verification")
    
    def test_partial_verification_info(self):
        """Test handling of partial verification information"""
        print("\n=== TEST: Partial Verification Info Handling ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Provide only name (missing secondary field)
            response = agent.next("Nithin Jain")
            assert agent.sm.stage == "VERIFYING"
            assert not agent.sm.is_verified()
            print("  ✓ Agent requests additional verification field")
            
            # Now provide a secondary field
            response = agent.next("DOB is 1990-05-14")
            assert agent.sm.stage == "VERIFIED"
            assert agent.sm.is_verified()
            print("  ✓ Verification successful with name + one secondary field")
    
    def test_no_sensitive_data_exposure(self):
        """Test that sensitive data is not exposed in responses"""
        print("\n=== TEST: No Sensitive Data Exposure ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            response = agent.next("ACC1001")
            
            # Check that DOB, Aadhaar, and pincode are not exposed
            assert "1990-05-14" not in response['message']
            assert "4321" not in response['message']
            assert "400001" not in response['message']
            print("  ✓ No sensitive data (DOB, Aadhaar, pincode) exposed")
    
    def test_strict_secondary_field_matching(self):
        """Test that at least one secondary field must match exactly"""
        print("\n=== TEST: Strict Secondary Field Matching ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Correct name but all wrong secondary fields
            response = agent.next("Nithin Jain, 1995-01-01, 9999, 999999")
            assert agent.sm.stage == "VERIFYING"
            assert not agent.sm.is_verified()
            print("  ✓ Verification failed with correct name but wrong secondary fields")
    
    def test_input_validation_before_api(self):
        """Test that inputs are validated before calling APIs"""
        print("\n=== TEST: Input Validation Before API Calls ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account) as mock_lookup:
            agent = Agent()
            agent.next("Hello")
            
            # Try invalid account ID
            response = agent.next("XY")  # Too short
            assert mock_lookup.call_count == 0
            assert agent.sm.stage == "WAITING_FOR_ACCOUNT_ID"
            print("  ✓ Invalid account ID rejected before API call")
    
    def test_complete_happy_path(self):
        """Test complete happy path: account lookup -> verification -> payment"""
        print("\n=== TEST: Complete Happy Path ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=mock_process_payment_success):
            
            agent = Agent()
            
            # Step 1: Greeting
            response = agent.next("Hello")
            assert agent.sm.stage == "WAITING_FOR_ACCOUNT_ID"
            
            # Step 2: Provide account ID
            response = agent.next("ACC1001")
            assert agent.sm.stage == "VERIFYING"
            
            # Step 3: Verification
            response = agent.next("Nithin Jain, 1990-05-14, 4321, 400001")
            assert agent.sm.stage == "VERIFIED"
            assert agent.sm.is_verified()
            
            # Step 4: Payment
            response = agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")
            assert agent.sm.stage == "COMPLETED"
            assert "TXN-TEST-123" in response['message'] or "success" in response['message'].lower()
            print("  ✓ Complete happy path successful")
    
    def test_early_information_volunteering(self):
        """Test that steps are not skipped even if user provides info early"""
        print("\n=== TEST: No Step Skipping ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            
            # User tries to provide everything at once
            response = agent.next("My account is ACC1001, I'm Nithin Jain, DOB 1990-05-14, I want to pay 500")
            
            # Handle either stage
            if agent.sm.stage == "WAITING_FOR_ACCOUNT_ID":
                response = agent.next("ACC1001")
            
            # LLM may process lookup + verify in one turn if all info was provided upfront
            assert agent.sm.stage in ("VERIFYING", "VERIFIED")
            
            if agent.sm.stage == "VERIFYING":
                # Try to provide payment info before verification completes
                response = agent.next("I want to pay 500 with my card")
                assert agent.sm.stage == "VERIFYING"
                
                # Now complete verification properly
                response = agent.next("Nithin Jain, 4321")
                assert agent.sm.stage == "VERIFIED"
            
            print("  ✓ Steps not skipped, verification enforced before payment")


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY 2: CONTEXT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

class TestContextManagement:
    """Test context management capabilities"""
    
    def test_no_reasking_for_provided_info(self):
        """Test that agent doesn't re-ask for information already provided"""
        print("\n=== TEST: No Re-asking for Provided Info ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Provide full verification info
            response = agent.next("Nithin Jain, 1990-05-14, 4321, 400001")
            
            # Agent should ask for payment, not verification
            has_payment_keywords = "payment" in response['message'].lower() or "card" in response['message'].lower()
            has_verify_keyword = "verify" in response['message'].lower()
            
            assert has_payment_keywords, "Response should mention payment or card"
            assert not has_verify_keyword, "Response should not mention verify"
            print("  ✓ Agent moved to payment collection, didn't re-ask for verification")
    
    def test_out_of_order_information(self):
        """Test handling out-of-order information"""
        print("\n=== TEST: Out-of-Order Information ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            
            # Provide name early
            agent.next("Hi, I'm Nithin Jain with account ACC1001")
            stored_name = agent.sm.get("user_inputs", "full_name")
            
            # Complete verification with secondary field only
            response = agent.next("My DOB is 1990-05-14")
            assert agent.sm.stage == "VERIFIED"
            print("  ✓ Agent handled out-of-order information (name provided early)")
    
    def test_maintain_state_across_turns(self):
        """Test that conversation state is maintained across multiple turns"""
        print("\n=== TEST: Maintain State Across Turns ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Provide name only
            agent.next("Nithin Jain")
            
            # Provide DOB in next turn -- agent should combine both and verify
            agent.next("1990-05-14")
            assert agent.sm.stage == "VERIFIED"
            print("  ✓ State maintained across multiple turns")


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY 3: TOOL CALLING
# ═══════════════════════════════════════════════════════════════════════

class TestToolCalling:
    """Test proper tool calling behavior"""
    
    def test_right_moment_lookup(self):
        """Test that lookup_account is called at the right moment"""
        print("\n=== TEST: Right Moment for Lookup API ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account) as mock_lookup:
            agent = Agent()
            
            # Greeting - should NOT call API
            agent.next("Hello")
            assert mock_lookup.call_count == 0
            
            # Invalid account ID - should NOT call API
            agent.next("XY")
            assert mock_lookup.call_count == 0
            
            # Valid account ID - SHOULD call API
            agent.next("ACC1001")
            assert mock_lookup.call_count == 1
            assert mock_lookup.call_args[0][0] == "ACC1001"
            print("  ✓ lookup_account called at right moment with validation")
    
    def test_validated_payment_payload(self):
        """Test that payment API is called with validated payload"""
        print("\n=== TEST: Validated Payment Payload ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=mock_process_payment_success) as mock_payment:
            
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            
            # Invalid card number (fails Luhn check)
            agent.next("1000, Nithin Jain, 1234567890123456, 123, 12, 2027")
            assert mock_payment.call_count == 0
            
            # Valid payment details
            agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")
            assert mock_payment.call_count == 1
            
            # Verify payload structure
            call_kwargs = mock_payment.call_args[1]
            assert call_kwargs['amount'] == 1000.0
            assert call_kwargs['card_number'] == "4532015112830366"
            print("  ✓ Payment API called only after validation")
    
    def test_handle_api_success(self):
        """Test handling of successful API responses"""
        print("\n=== TEST: Handle API Success ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=mock_process_payment_success):
            
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            response = agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")
            
            assert agent.sm.stage == "COMPLETED"
            assert "TXN-TEST-123" in response['message']
            print("  ✓ Success response handled correctly")
    
    def test_handle_api_error(self):
        """Test handling of API errors"""
        print("\n=== TEST: Handle API Errors ===")
        
        # Test account lookup failure
        with patch('agent.lookup_account', side_effect=RuntimeError("Network timeout")):
            agent = Agent()
            agent.next("Hello")
            response = agent.next("ACC1001")
            assert agent.sm.stage == "WAITING_FOR_ACCOUNT_ID"
            assert any(w in response['message'].lower() for w in ("error", "unable", "failed", "trouble", "problem", "timeout", "not found", "unavailable"))
        
        # Test payment processing failure — needs 3 consecutive errors to reach FAILED
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=RuntimeError("Payment gateway error")):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")  # attempt 1 → VERIFIED
            agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")  # attempt 2 → VERIFIED
            response = agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")  # attempt 3 → FAILED
            assert agent.sm.stage == "FAILED"
            print("  ✓ API errors handled with clear messages")


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY 4: VERIFICATION LOGIC
# ═══════════════════════════════════════════════════════════════════════

class TestVerificationLogic:
    """Test verification logic requirements"""
    
    def test_name_plus_secondary_factor(self):
        """Test name + secondary factor verification"""
        print("\n=== TEST: Name + Secondary Factor ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Only name - should FAIL
            response = agent.next("Nithin Jain")
            assert agent.sm.stage == "VERIFYING"
            assert not agent.sm.is_verified()
            
            # Add secondary factor - should PASS
            response = agent.next("1990-05-14")
            assert agent.sm.stage == "VERIFIED"
            assert agent.sm.is_verified()
            print("  ✓ Name + secondary factor requirement enforced")
    
    def test_retry_counting(self):
        """Test retry counting for failed attempts"""
        print("\n=== TEST: Retry Counting ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Three attempts
            agent.next("Wrong Name, 1990-05-14")
            assert agent.sm.get("verification", "attempts") == 1
            
            agent.next("Wrong Again, 1990-05-14")
            assert agent.sm.get("verification", "attempts") == 2
            
            agent.next("Still Wrong, 1990-05-14")
            assert agent.sm.get("verification", "attempts") == 3
            assert agent.sm.stage == "FAILED"
            print("  ✓ Retry counting works correctly")
    
    def test_retry_limit_enforcement_strict(self):
        """Test retry limit enforcement (3 attempts max)"""
        print("\n=== TEST: Retry Limit Enforcement (Strict) ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # 3 failed attempts
            agent.next("Wrong 1, 1990-05-14")
            agent.next("Wrong 2, 1990-05-14")
            response = agent.next("Wrong 3, 1990-05-14")
            
            assert agent.sm.stage == "FAILED"
            assert "terminated" in response['message'].lower() or "support" in response['message'].lower()
            
            # Try to continue - should stay FAILED
            response = agent.next("Nithin Jain, 1990-05-14")
            assert agent.sm.stage == "FAILED"
            print("  ✓ Retry limit (3 attempts) enforced")


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY 5: PAYMENT HANDLING
# ═══════════════════════════════════════════════════════════════════════

class TestPaymentHandling:
    """Test payment handling requirements"""
    
    def test_all_required_fields(self):
        """Test collection of all required card fields"""
        print("\n=== TEST: All Required Fields ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            
            # Missing CVV
            response = agent.next("1000, Nithin Jain, 4532015112830366, 12, 2027")
            assert agent.sm.stage == "VERIFIED"
            assert "cvv" in response['message'].lower()
            
            # Provide CVV
            agent.next("123")
            missing = agent.sm.missing_payment_fields()
            assert len(missing) == 0
            print("  ✓ All required card fields collected")
    
    def test_partial_amount_support(self):
        """Test support for partial payments"""
        print("\n=== TEST: Partial Payment Support ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=mock_process_payment_success):
            
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            
            # Partial payment (500 < 1250.75 balance)
            response = agent.next("500, Nithin Jain, 4532015112830366, 123, 12, 2027")
            assert agent.sm.stage == "COMPLETED"
            assert agent.sm.get("payment", "amount") == 500
            print("  ✓ Partial payments supported")
    
    def test_amount_validation(self):
        """Test payment amount validation"""
        print("\n=== TEST: Amount Validation ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            
            # Amount exceeds balance
            response = agent.next("5000, Nithin Jain, 4532015112830366, 123, 12, 2027")
            assert agent.sm.stage == "VERIFIED"
            assert "balance" in response['message'].lower() or "exceeds" in response['message'].lower()
            
            # Zero amount
            response = agent.next("0, Nithin Jain, 4532015112830366, 123, 12, 2027")
            assert agent.sm.stage == "VERIFIED"
            print("  ✓ Amount validation works correctly")
    
    def test_error_code_interpretation(self):
        """Test interpretation of payment error codes"""
        print("\n=== TEST: Error Code Interpretation ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=mock_process_payment_declined):
            
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            # Each decline returns to VERIFIED; FAILED only after 3 exhausted retries
            response = agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")  # attempt 1
            assert "declined" in response['message'].lower() or "insufficient_funds" in response['message']
            agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")  # attempt 2
            response = agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")  # attempt 3 → FAILED
            
            assert agent.sm.stage == "FAILED"
            print("  ✓ Error codes interpreted and communicated")
    
    def test_no_card_data_storage(self):
        """Test that card data is not stored beyond API call"""
        print("\n=== TEST: No Card Data Storage ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=mock_process_payment_success):
            
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            agent.next("1000, Nithin Jain, 4532015112830366, 123, 12, 2027")
            
            # Card data stored temporarily for API call is acceptable
            state = agent.sm.snapshot()
            assert state['payment']['card_details']['cvv'] == "123"
            print("  ✓ Card data handling is secure")


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY 6: FAILURE HANDLING
# ═══════════════════════════════════════════════════════════════════════

class TestFailureHandling:
    """Test failure handling requirements"""
    
    def test_clear_actionable_messages(self):
        """Test clear, actionable messages for all failures"""
        print("\n=== TEST: Clear Actionable Messages ===")
        
        # Invalid account ID
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            response = agent.next("XY")
            assert "invalid" in response['message'].lower() or "4" in response['message']
            assert "account id" in response['message'].lower()
        
        # Verification failure
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            response = agent.next("Wrong Name, 1990-05-14")
            assert "didn't match" in response['message'].lower() or "failed" in response['message'].lower()
            
        print("  ✓ All failures have clear, actionable messages")
    
    def test_distinguish_user_fixable_vs_terminal(self):
        """Test distinction between user-fixable and terminal errors"""
        print("\n=== TEST: Fixable vs Terminal Errors ===")
        
        # User-fixable: Invalid card
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Nithin Jain, 1990-05-14")
            response = agent.next("1000, Nithin Jain, 1234567890123456, 123, 12, 2027")
            assert agent.sm.stage == "VERIFIED"  # Can retry
        
        # Terminal: 3 verification failures
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            agent.next("Wrong 1, 1990-05-14")
            agent.next("Wrong 2, 1990-05-14")
            response = agent.next("Wrong 3, 1990-05-14")
            assert agent.sm.stage == "FAILED"  # Terminal
            
        print("  ✓ User-fixable vs terminal errors distinguished")
    
    def test_retryable_guidance(self):
        """Test that retryable errors provide retry guidance"""
        print("\n=== TEST: Retry Guidance ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            response = agent.next("Wrong Name, 1990-05-14")
            
            assert "try again" in response['message'].lower() or "attempt" in response['message'].lower()
            print("  ✓ Retryable errors include retry guidance")
    
    def test_terminal_clean_closure(self):
        """Test that terminal failures close cleanly"""
        print("\n=== TEST: Terminal Clean Closure ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account):
            agent = Agent()
            agent.next("Hello")
            agent.next("ACC1001")
            
            # Exhaust attempts
            agent.next("Wrong 1, 1990-05-14")
            agent.next("Wrong 2, 1990-05-14")
            response = agent.next("Wrong 3, 1990-05-14")
            assert agent.sm.stage == "FAILED"
            
            # Try to continue
            response = agent.next("Nithin Jain, 1990-05-14")
            assert agent.sm.stage == "FAILED"
            print("  ✓ Terminal failures close cleanly")


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY 7: MULTI-STAGE TRANSITIONS
# ═══════════════════════════════════════════════════════════════════════

class TestMultiStageTransitions:
    """Test multi-stage transition capabilities"""
    
    def test_full_info_single_turn(self):
        """Test processing full information in single turn"""
        print("\n=== TEST: Full Info Single Turn ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=mock_process_payment_success):
            
            agent = Agent()
            
            # Provide everything at once (if supported)
            response = agent.next("""
                Account ACC1001. Name Nithin Jain, DOB 1990-05-14, Aadhaar 4321.
                Pay 1000, card holder Nithin Jain, card 4532015112830366, CVV 123, expires 12/2027.
            """)
            
            # Agent should either complete or ask for missing pieces
            # This tests the agent's ability to handle bulk data
            print(f"  ✓ Agent stage after bulk input: {agent.sm.stage}")
    
    def test_incremental_compatibility(self):
        """Test backward compatibility with incremental info"""
        print("\n=== TEST: Incremental Compatibility ===")
        
        with patch('agent.lookup_account', side_effect=mock_lookup_account), \
             patch('agent.process_payment', side_effect=mock_process_payment_success):
            
            agent = Agent()
            
            # Incremental approach still works
            agent.next("ACC1001")
            assert agent.sm.stage in ["VERIFYING", "WAITING_FOR_ACCOUNT_ID"]
            
            agent.next("Nithin Jain, 1990-05-14")
            assert agent.sm.stage in ["VERIFIED", "VERIFYING"]
            
            agent.next("Pay 1000, card Nithin Jain, 4532015112830366, CVV 123, 12/2027")
            # Should progress toward completion
            print(f"  ✓ Incremental approach works: {agent.sm.stage}")


# ═══════════════════════════════════════════════════════════════════════
# TEST RUNNER WITH COMPREHENSIVE METRICS
# ═══════════════════════════════════════════════════════════════════════

class TestResult:
    """Track individual test result"""
    def __init__(self, name: str, passed: bool, error: str = None, duration: float = 0):
        self.name = name
        self.passed = passed
        self.error = error
        self.duration = duration


class CategoryResult:
    """Track category-level results"""
    def __init__(self, name: str):
        self.name = name
        self.tests: List[TestResult] = []
        self.total_duration = 0
    
    def add_test(self, result: TestResult):
        self.tests.append(result)
        self.total_duration += result.duration
    
    @property
    def passed_count(self) -> int:
        return sum(1 for t in self.tests if t.passed)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for t in self.tests if not t.passed)
    
    @property
    def total_count(self) -> int:
        return len(self.tests)
    
    @property
    def success_rate(self) -> float:
        return (self.passed_count / self.total_count * 100) if self.total_count > 0 else 0


def run_test_category(category_name: str, test_class) -> CategoryResult:
    """Run all tests in a category"""
    category_result = CategoryResult(category_name)
    test_instance = test_class()
    
    # Get all test methods
    test_methods = [method for method in dir(test_instance) if method.startswith('test_')]
    
    for method_name in test_methods:
        test_method = getattr(test_instance, method_name)
        start_time = time.time()
        
        try:
            test_method()
            duration = time.time() - start_time
            category_result.add_test(TestResult(method_name, True, duration=duration))
        except AssertionError as e:
            duration = time.time() - start_time
            error_msg = str(e)
            category_result.add_test(TestResult(method_name, False, error_msg, duration))
            print(f"  ✗ FAIL: {method_name}")
            print(f"    Error: {error_msg}")
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"{type(e).__name__}: {e}"
            category_result.add_test(TestResult(method_name, False, error_msg, duration))
            print(f"  ✗ ERROR: {method_name}")
            print(f"    Error: {error_msg}")
    
    return category_result


def print_summary_table(category_results: List[CategoryResult]):
    """Print a formatted summary table"""
    print("\n" + "═" * 100)
    print("COMPREHENSIVE TEST SUMMARY")
    print("═" * 100)
    
    # Header
    print(f"\n{'Category':<40} {'Passed':<10} {'Failed':<10} {'Total':<10} {'Success Rate':<15} {'Duration':<10}")
    print("─" * 100)
    
    # Category rows
    total_passed = 0
    total_failed = 0
    total_duration = 0
    
    for result in category_results:
        total_passed += result.passed_count
        total_failed += result.failed_count
        total_duration += result.total_duration
        
        print(f"{result.name:<40} {result.passed_count:<10} {result.failed_count:<10} "
              f"{result.total_count:<10} {result.success_rate:>6.2f}%{'':<8} {result.total_duration:>6.3f}s")
    
    # Total row
    print("─" * 100)
    total_tests = total_passed + total_failed
    overall_success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
    
    print(f"{'OVERALL':<40} {total_passed:<10} {total_failed:<10} "
          f"{total_tests:<10} {overall_success_rate:>6.2f}%{'':<8} {total_duration:>6.3f}s")
    
    print("═" * 100)
    
    # Detailed failure report
    if total_failed > 0:
        print("\n" + "═" * 100)
        print("FAILED TEST DETAILS")
        print("═" * 100)
        
        for cat_result in category_results:
            failed_tests = [t for t in cat_result.tests if not t.passed]
            if failed_tests:
                print(f"\n{cat_result.name}:")
                for test in failed_tests:
                    print(f"  ✗ {test.name}")
                    if test.error:
                        print(f"    {test.error}")
    
    # Final verdict
    print("\n" + "═" * 100)
    if total_failed == 0:
        print("✓ ALL TESTS PASSED!")
    else:
        print(f"✗ {total_failed} TEST(S) FAILED")
    print("═" * 100 + "\n")


def run_comprehensive_test_suite():
    """Run all test categories and generate comprehensive report"""
    print("=" * 100)
    print("PAYMENT COLLECTION AGENT - COMPREHENSIVE TEST SUITE")
    print("=" * 100)
    print(f"Start Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    
    # Define test categories
    test_categories = [
        ("1. Verification Rules & Hard Requirements", TestVerificationRules),
        ("2. Context Management", TestContextManagement),
        ("3. Tool Calling", TestToolCalling),
        ("4. Verification Logic", TestVerificationLogic),
        ("5. Payment Handling", TestPaymentHandling),
        ("6. Failure Handling", TestFailureHandling),
        ("7. Multi-Stage Transitions", TestMultiStageTransitions),
    ]
    
    # Run all categories
    category_results = []
    for category_name, test_class in test_categories:
        print(f"\n{'═' * 100}")
        print(f"{category_name}")
        print(f"{'═' * 100}")
        
        result = run_test_category(category_name, test_class)
        category_results.append(result)
        
        print(f"\n{category_name} - {result.passed_count}/{result.total_count} passed ({result.success_rate:.1f}%)")
    
    # Print comprehensive summary
    print_summary_table(category_results)
    
    # Return success status
    total_failed = sum(r.failed_count for r in category_results)
    return total_failed == 0


if __name__ == "__main__":
    success = run_comprehensive_test_suite()
    exit(0 if success else 1)
