import pytest
from errand_agent.tools.mock_provider import MockProviderService
from errand_agent.core.idempotency import BookingRecoveryManager

def test_timeout_after_success_recovery():
    service = MockProviderService()
    service.force_book_outcome = "timeout_and_booked"
    recovery = BookingRecoveryManager()
    
    hold = service.hold_slot("prov-plumb-101", "2026-11-02 09:00")
    key = recovery.generate_key("u1", "book", "prov-plumb-101", "2026-11-02 09:00", 1200)

    success, booking_id, msg = recovery.execute_booking_with_recovery(
        service, hold["hold_id"], key, "u1", "prov-plumb-101", "2026-11-02 09:00", 1200
    )

    assert success is True
    assert booking_id is not None
    assert "book-" in booking_id

    # Verify authoritative status check
    status = service.get_booking_status(key)
    assert status["status"] == "booked"
    assert status["booking_id"] == booking_id

def test_timeout_after_failed_recovery():
    service = MockProviderService()
    service.force_book_outcome = "timeout_and_failed"
    recovery = BookingRecoveryManager()

    hold = service.hold_slot("prov-plumb-101", "2026-11-02 09:00")
    key = recovery.generate_key("u1", "book", "prov-plumb-101", "2026-11-02 09:00", 1200)

    success, booking_id, msg = recovery.execute_booking_with_recovery(
        service, hold["hold_id"], key, "u1", "prov-plumb-101", "2026-11-02 09:00", 1200
    )

    assert success is False
    assert booking_id is None
    status = service.get_booking_status(key)
    assert status["status"] == "failed"
