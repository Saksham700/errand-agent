import pytest
from errand_agent.core.approval import ApprovalStore, ApprovalStatus, ApprovalRequiredError, ApprovalVoidError

def test_approval_lifecycle():
    store = ApprovalStore()
    rec = store.request_approval(action="book", provider_id="p1", slot="2026-11-02 10:00", price=1200)
    assert rec.status == ApprovalStatus.PENDING

    # Attempting execution before user confirmation raises ApprovalRequiredError
    with pytest.raises(ApprovalRequiredError):
        store.verify_and_consume("book", "p1", "2026-11-02 10:00", 1200)

    # User confirms
    success, msg = store.user_confirmed()
    assert success
    assert rec.status == ApprovalStatus.APPROVED

    # Consuming matching record succeeds
    consumed = store.verify_and_consume("book", "p1", "2026-11-02 10:00", 1200)
    assert consumed.action == "book"

def test_approval_void_on_parameter_change():
    store = ApprovalStore()
    store.request_approval(action="book", provider_id="p1", slot="2026-11-02 10:00", price=1200)
    store.user_confirmed()

    # Price changes
    store.check_or_void_on_parameter_change(provider_id="p1", slot="2026-11-02 10:00", price=1500)
    assert store.active_record.status == ApprovalStatus.VOID

    with pytest.raises(ApprovalVoidError):
        store.verify_and_consume("book", "p1", "2026-11-02 10:00", 1500)

def test_approval_void_on_slot_mismatch():
    store = ApprovalStore()
    store.request_approval(action="book", provider_id="p1", slot="2026-11-02 10:00", price=1200)
    store.user_confirmed()

    with pytest.raises(ApprovalVoidError):
        store.verify_and_consume("book", "p1", "2026-11-02 14:00", 1200)
