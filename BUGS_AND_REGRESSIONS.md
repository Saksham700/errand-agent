# Real Bugs Encountered, Root Cause Analysis, and Regression Guards

During the implementation and automated evaluation testing of the Errand Agent, the following three real bugs were uncovered, diagnosed, fixed, and permanently guarded with regression tests.

---

### Bug 1: Dictionary vs Dataclass Type Mismatch on Slot Holds

- **What Broke**:
  Executing an approved booking (`_execute_approved_booking`) crashed with an unexpected exception:
  `AttributeError: 'dict' object has no attribute 'hold_id'`.
  This broke all confirmed booking executions across the happy path, timeout recoveries, and repeated confirmations.
- **Why It Happened**:
  The mock tool `hold_slot()` returned a raw dictionary `{"hold_id": ..., "provider_id": ..., "slot": ..., "quoted_price": ...}`, but `workflow.set_active_hold()` directly assigned the variable without converting it to the `HoldSlotResult` dataclass. When `_execute_approved_booking()` accessed `hold.hold_id`, Python threw an `AttributeError`.
- **The Fix**:
  1. Updated `workflow.set_active_hold()` to inspect incoming objects: if a dict is passed, it automatically constructs a typed `HoldSlotResult`.
  2. In `agent._execute_approved_booking()`, added safe property resolution: `hold_id = hold.hold_id if hasattr(hold, "hold_id") else hold["hold_id"]`.
- **Regression Test Guarding It**:
  - `evals/scenarios.py`: `test_happy_path` (Scenario 1) & `test_repeated_confirmation` (Scenario 10).
  - `tests/test_workflow.py`: `test_workflow_missing_fields_and_prompt`.

---

### Bug 2: Premature Nullification in Parameter Change Voiding

- **What Broke**:
  When a provider's quoted price changed between approval and booking execution, the system failed to raise `ApprovalVoidError` and instead raised generic `ApprovalRequiredError: Action blocked: No approval record exists`.
- **Why It Happened**:
  In `approval.py`, `check_or_void_on_parameter_change()` marked `self.active_record.void(...)`, appended it to history, and then immediately set `self.active_record = None`. When the execution pipeline proceeded to `verify_and_consume()`, it inspected `self.active_record` which was now `None`, completely erasing the context of the voided record and its reason.
- **The Fix**:
  Retained `self.active_record` in state with `status = ApprovalStatus.VOID` and its associated `void_reason`. This allows `verify_and_consume()` to detect the voided state and raise the descriptive `ApprovalVoidError(f"Action blocked: Approval was voided ({record.void_reason})")`.
- **Regression Test Guarding It**:
  - `evals/scenarios.py`: `test_price_change_voiding` (Scenario 3) & `test_slot_change_voiding` (Scenario 4).
  - `tests/test_approval.py`: `test_approval_void_on_parameter_change`.

---

### Bug 3: Keyword Overlap Causing Cancellation Rejection Inversion

- **What Broke**:
  When the agent asked the user to confirm a cancellation (*"Are you sure you want to cancel your upcoming booking...?"*), and the user replied *"Yes, cancel it"*, the agent inverted the intent and replied *"I have cancelled this proposal. Let me know if you would like to search for a different time or provider"*, aborting the cancellation rather than executing it.
- **Why It Happened**:
  In `agent.py`, the rejection detector included `"cancel"` in its keyword regex (`r"\b(no|cancel|stop|don't book|decline)\b"`). When the user replied *"Yes, cancel it"*, both `is_confirmation` and `is_rejection` evaluated to `True`. Because rejection took precedence or was evaluated first, the user's explicit confirmation was misclassified as declining the action.
- **The Fix**:
  1. Removed `"cancel"` from `is_rejection` keywords; rejection keywords were narrowed to explicit negative indicators (`no`, `decline`, `don't`, `stop`).
  2. Evaluated affirmative confirmation (`is_confirmation`) with higher priority before evaluating proposal rejections.
- **Regression Test Guarding It**:
  - `evals/scenarios.py`: `test_cancellation_503_retry` (Scenario 9).
  - `tests/test_evals_suite.py`: automated test suite validation.
