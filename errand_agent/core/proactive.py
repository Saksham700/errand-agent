from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
from errand_agent.tools.mock_provider import MockProviderService
from errand_agent.core.approval import ApprovalStore
from errand_agent.core.workflow import WorkflowManager
from errand_agent.core.tracer import ExecutionTracer

class ProactiveFollowUpHandler:
    """
    Nice-To-Have Implementation: Proactive Follow-Up.
    When a booked provider cancels:
    1. Agent notices cancellation event.
    2. Searches for suitable replacement providers matching service, area, and constraints.
    3. Obtains a hold on the best available replacement slot.
    4. Code creates an ApprovalRecord and asks user for explicit approval.
    5. NEVER rebooks automatically without user confirmation.
    """
    def __init__(self, service: MockProviderService, approval_store: ApprovalStore, tracer: ExecutionTracer):
        self.service = service
        self.approval_store = approval_store
        self.tracer = tracer

    def handle_cancellation_event(
        self,
        user_id: str,
        cancelled_booking_id: str,
        workflow: WorkflowManager
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        self.tracer.record_event("proactive_cancellation_detected", {
            "booking_id": cancelled_booking_id,
            "user_id": user_id
        })

        booking = self.service.bookings.get(cancelled_booking_id)
        if not booking:
            return False, f"Booking {cancelled_booking_id} not found in provider records.", None

        # Mark booking as cancelled by provider
        booking.status = "cancelled_by_provider"

        # Determine area from original booking provider
        booking_prov = self.service.providers.get(booking.provider_id)
        area = booking_prov.area if booking_prov else "Indiranagar"

        # Search replacements
        providers = self.service.search_providers(
            service=booking.service,
            area=area,
            date_range=None
        )

        # Filter out the cancelled provider
        candidates = [p for p in providers if p["id"] != booking.provider_id and len(p.get("free_slots", [])) > 0]
        if not candidates:
            msg = f"Your booking ({booking.service} with {booking.provider_name}) was cancelled by the provider. Unfortunately, no alternative providers are currently open in your area. Would you like to adjust your date or search another area?"
            return False, msg, None

        best_match = candidates[0]
        chosen_slot = best_match["free_slots"][0]

        # Hold the replacement slot
        hold_res = self.service.hold_slot(best_match["id"], chosen_slot)
        workflow.update_facts(
            service=booking.service,
            area=best_match["area"]
        )
        workflow.set_active_hold(hold_res)

        # Request user approval: DO NOT book automatically!
        approval_rec = self.approval_store.request_approval(
            action="book",
            provider_id=best_match["id"],
            slot=chosen_slot,
            price=hold_res["quoted_price"]
        )

        self.tracer.log_approval_check(
            action="book",
            approved=False,
            reason="Awaiting user confirmation for proactive replacement",
            details={
                "replacement_provider": best_match["name"],
                "slot": chosen_slot,
                "price": hold_res["quoted_price"]
            }
        )

        message = (
            f"Notice: Your booking ({booking.service} with {booking.provider_name}) was cancelled by the provider. "
            f"I have found and placed a hold on a top-rated replacement:\n"
            f"• Provider: {best_match['name']} (Rating: {best_match['rating']}★)\n"
            f"• Slot: {chosen_slot}\n"
            f"• Quoted Price: ₹{hold_res['quoted_price']}\n"
            f"Would you like me to confirm and book this replacement for you?"
        )
        return True, message, hold_res
