from __future__ import annotations
import hashlib
import json
import os
from typing import Any, Dict, Optional, Tuple
from errand_agent.tools.mock_provider import MockProviderService, TimeoutError

class BookingRecoveryManager:
    """
    Guarantees booking correctness:
    - Generates deterministic idempotency keys tied to (user_id, action, provider_id, slot, price)
    - On timeout, immediately queries get_booking_status before retrying or reporting
    - Never claims success until verified
    - Persists in-flight journal to disk to survive restarts mid-booking
    """
    def __init__(self, journal_path: Optional[str] = None):
        self.journal_path = journal_path
        self.pending_journal: Dict[str, Dict[str, Any]] = {}
        if journal_path and os.path.exists(journal_path):
            self._load_journal()

    def generate_key(self, user_id: str, action: str, provider_id: str, slot: str, price: int, attempt: int = 0) -> str:
        # Key is deterministic for the exact transaction intent
        seed = f"{user_id}:{action}:{provider_id}:{slot}:{price}"
        h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return f"idemp-{action}-{h}"

    def journal_in_flight(self, idempotency_key: str, user_id: str, action: str, provider_id: str, slot: str, price: int, hold_id: Optional[str] = None) -> None:
        self.pending_journal[idempotency_key] = {
            "idempotency_key": idempotency_key,
            "user_id": user_id,
            "action": action,
            "provider_id": provider_id,
            "slot": slot,
            "price": price,
            "hold_id": hold_id,
            "status": "in_flight"
        }
        self._save_journal()

    def journal_resolved(self, idempotency_key: str, outcome: str, booking_id: Optional[str] = None) -> None:
        if idempotency_key in self.pending_journal:
            self.pending_journal[idempotency_key]["status"] = outcome
            if booking_id:
                self.pending_journal[idempotency_key]["booking_id"] = booking_id
            self._save_journal()

    def execute_booking_with_recovery(
        self,
        service: MockProviderService,
        hold_id: str,
        idempotency_key: str,
        user_id: str,
        provider_id: str,
        slot: str,
        price: int,
        tracer: Optional[Any] = None
    ) -> Tuple[bool, Optional[str], str]:
        """
        Executes book() and handles timeouts by checking get_booking_status().
        Returns (success: bool, booking_id: Optional[str], message: str)
        """
        self.journal_in_flight(idempotency_key, user_id, "book", provider_id, slot, price, hold_id)

        try:
            res = service.book(hold_id, idempotency_key)
            booking_id = res.get("booking_id")
            self.journal_resolved(idempotency_key, "booked", booking_id)
            return True, booking_id, "Booking successful and verified."
        except TimeoutError:
            # Crucial requirement: On timeout, check get_booking_status before retrying or reporting!
            if tracer:
                tracer.log_tool_call("get_booking_status", {"idempotency_key": idempotency_key, "reason": "timeout_recovery"})
            status_res = service.get_booking_status(idempotency_key)
            if tracer:
                tracer.log_tool_result("get_booking_status", status_res, latency_ms=15.0)

            if status_res.get("status") == "booked":
                booking_id = status_res.get("booking_id")
                self.journal_resolved(idempotency_key, "booked", booking_id)
                return True, booking_id, f"Connection timed out, but verified booking was completed successfully (Booking ID: {booking_id})."
            else:
                self.journal_resolved(idempotency_key, "failed")
                return False, None, "Booking timed out and authoritative status verified that the booking did NOT go through."

    def recover_pending_transactions(self, service: MockProviderService) -> List[Dict[str, Any]]:
        """Used after an agent restart mid-booking to reconcile any in-flight transaction."""
        reconciled = []
        for key, entry in list(self.pending_journal.items()):
            if entry.get("status") == "in_flight":
                status_res = service.get_booking_status(key)
                if status_res.get("status") == "booked":
                    b_id = status_res.get("booking_id")
                    entry["status"] = "booked"
                    entry["booking_id"] = b_id
                    reconciled.append({"key": key, "status": "booked", "booking_id": b_id})
                else:
                    entry["status"] = "failed"
                    reconciled.append({"key": key, "status": "failed"})
        self._save_journal()
        return reconciled

    def _save_journal(self) -> None:
        if not self.journal_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.journal_path)), exist_ok=True)
        with open(self.journal_path, "w", encoding="utf-8") as f:
            json.dump(self.pending_journal, f, indent=2)

    def _load_journal(self) -> None:
        try:
            with open(self.journal_path, "r", encoding="utf-8") as f:
                self.pending_journal = json.load(f)
        except Exception:
            self.pending_journal = {}
