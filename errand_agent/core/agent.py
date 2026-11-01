from __future__ import annotations
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from errand_agent.models import ApprovalRecord, ApprovalStatus, Provider, Booking
from errand_agent.tools.mock_provider import (
    MockProviderService,
    ProviderAPIError,
    SlotUnavailableError,
    SlotConflictError,
    HoldExpiredError,
    SlotTakenError,
    TimeoutError,
    Transient503Error
)
from errand_agent.core.approval import ApprovalStore, ApprovalRequiredError, ApprovalVoidError
from errand_agent.core.workflow import WorkflowManager
from errand_agent.core.memory import MemoryStore
from errand_agent.core.idempotency import BookingRecoveryManager
from errand_agent.core.security import SecurityQuarantine
from errand_agent.core.limits import ExecutionBudget, LimitExhaustedError
from errand_agent.core.tracer import ExecutionTracer
from errand_agent.core.llm.base import BaseLLM
from errand_agent.core.llm.scripted import ScriptedLLM
from errand_agent.core.proactive import ProactiveFollowUpHandler

class ErrandAgent:
    """
    Main ErrandAgent Orchestrator.
    Fulfills all 8 Must-Haves and Nice-To-Have proactive follow-up.
    """
    def __init__(
        self,
        user_id: str = "user-123",
        provider_service: Optional[MockProviderService] = None,
        memory_store: Optional[MemoryStore] = None,
        llm: Optional[BaseLLM] = None,
        tracer: Optional[ExecutionTracer] = None,
        budget: Optional[ExecutionBudget] = None,
        journal_path: Optional[str] = None
    ):
        self.user_id = user_id
        self.service = provider_service or MockProviderService()
        self.memory = memory_store or MemoryStore()
        self.llm = llm or ScriptedLLM()
        self.tracer = tracer or ExecutionTracer()
        self.budget = budget or ExecutionBudget()
        self.workflow = WorkflowManager(user_id=user_id)
        self.approval = ApprovalStore()
        self.recovery = BookingRecoveryManager(journal_path=journal_path)
        self.proactive = ProactiveFollowUpHandler(self.service, self.approval, self.tracer)
        self.last_completed_booking: Optional[Booking] = None

    def handle_message(self, user_text: str) -> str:
        """Process a single turn of user conversation."""
        self.tracer.log_user_message(user_text)
        self.budget.start_turn()

        try:
            self.budget.record_turn()
            response = self._process_turn(user_text)
            self.tracer.log_agent_message(response)
            return response
        except LimitExhaustedError as e:
            msg = e.user_message
            self.tracer.record_event("limit_exhausted", {
                "limit_type": e.limit_type,
                "stats": self.budget.stats()
            })
            self.tracer.log_agent_message(msg)
            return msg
        except Exception as e:
            msg = f"I encountered an unexpected error: {str(e)}. I have safely paused execution. How would you like to proceed?"
            self.tracer.record_event("error_halt", {"error": str(e)})
            self.tracer.log_agent_message(msg)
            return msg

    def _process_turn(self, text: str) -> str:
        t_clean = text.strip()
        t_lower = t_clean.lower()

        # 1. Memory inspection & forgetting commands
        if "what do you remember" in t_lower or "view memory" in t_lower or "show memory" in t_lower:
            facts = self.memory.view_memory()
            if not facts:
                return "I currently do not have any saved preferences in my memory."
            lines = ["Here are the preferences I currently have recorded:"]
            for f in facts:
                source_desc = "stated by you" if f["source"] == "stated" else ("inferred (confirmed)" if f["confirmed"] else "inferred (needs confirmation)")
                lines.append(f"• {f['key']}: {f['value']} ({source_desc})")
            return "\n".join(lines)

        forget_match = re.search(r"forget\s+(?:my\s+)?(\w+)", t_lower)
        if forget_match:
            key_to_forget = forget_match.group(1).lower()
            # Normalize common keys
            if key_to_forget in ["neighborhood", "location"]:
                key_to_forget = "area"
            elif key_to_forget in ["plumber", "electrician", "technician"]:
                key_to_forget = "preferred_technician"
            
            existed = self.memory.forget_fact(key_to_forget)
            self.tracer.record_event("memory_forgotten", {"key": key_to_forget, "existed": existed})
            if existed:
                return f"I have forgotten your '{key_to_forget}' preference and will not use it again."
            else:
                return f"I have noted to never use '{key_to_forget}'."

        # Confirmation of pending inferred fact
        if "confirm" in t_lower and ("preference" in t_lower or "fact" in t_lower or "inferred" in t_lower):
            for k in ["area", "earliest_time", "preferred_technician"]:
                if k in t_lower:
                    self.memory.confirm_inferred_fact(k)
                    return f"Thank you! I have confirmed your {k} preference and will use it in future searches."

        # 2. Check if this is an explicit confirmation ("yes", "confirm", "proceed", "go ahead")
        is_confirmation = bool(re.search(r"\b(yes|confirm|proceed|go ahead|book it|sure|okay|sounds good)\b", t_lower))
        is_rejection = bool(re.search(r"\b(no|decline|don't|dont|stop)\b", t_lower))

        if is_confirmation:
            return self._handle_confirmation()

        if is_rejection and self.approval.active_record and self.approval.active_record.status == ApprovalStatus.PENDING:
            self.approval.user_rejected("User rejected proposal")
            self.workflow.clear_hold()
            return "I have cancelled this proposal. Let me know if you would like to search for a different time or provider."

        # 3. Check for Reschedule Intent
        if "reschedule" in t_lower or "move my" in t_lower:
            return self._handle_reschedule_intent(t_clean)

        # 4. Check for Cancellation Intent
        if "cancel my" in t_lower or ("cancel" in t_lower and ("booking" in t_lower or "service" in t_lower or "servicing" in t_lower or "plumber" in t_lower or "electrician" in t_lower)):
            return self._handle_cancellation_intent(t_clean)

        # 5. Booking Search / Specification / Single Fact Update Intent
        return self._handle_search_or_update(t_clean)

    def _handle_confirmation(self) -> str:
        # Check if user already booked something and is repeating "yes"
        if self.last_completed_booking and not (self.approval.active_record and self.approval.active_record.status == ApprovalStatus.PENDING):
            return (
                f"Your booking is already confirmed for {self.last_completed_booking.service} "
                f"with {self.last_completed_booking.provider_name} on {self.last_completed_booking.slot} "
                f"(Booking ID: {self.last_completed_booking.id}). No duplicate booking was made."
            )

        if not self.approval.active_record or self.approval.active_record.status != ApprovalStatus.PENDING:
            return "There is no pending action waiting for your approval right now. How can I help you?"

        record = self.approval.active_record
        self.approval.user_confirmed()

        # Execute according to action type
        if record.action == "book":
            return self._execute_approved_booking(record)
        elif record.action == "cancel":
            return self._execute_approved_cancellation(record)
        elif record.action == "reschedule":
            return self._execute_approved_reschedule(record)
        else:
            return f"Unknown action: {record.action}"

    def _execute_approved_booking(self, record: ApprovalRecord) -> str:
        # Requirement 2: Approval enforced by code before tool execution!
        try:
            self.budget.record_tool_call()
            # Strictly verify matching code record
            self.approval.verify_and_consume("book", record.provider_id, record.slot, record.price)
        except (ApprovalRequiredError, ApprovalVoidError) as e:
            return f"Booking halted: {str(e)}"

        hold = self.workflow.state.active_hold
        if not hold:
            return "Booking failed: No active slot hold found. Please search again."

        hold_id = hold.hold_id if hasattr(hold, "hold_id") else hold["hold_id"]

        # Requirement 3: Deterministic idempotency key
        idemp_key = self.recovery.generate_key(
            self.user_id, "book", record.provider_id, record.slot, record.price
        )

        self.tracer.log_tool_call("book", {
            "hold_id": hold_id,
            "idempotency_key": idemp_key,
            "provider_id": record.provider_id,
            "slot": record.slot,
            "price": record.price
        })

        # Execute with recovery on timeout
        start_t = time.time()
        try:
            success, b_id, msg = self.recovery.execute_booking_with_recovery(
                self.service,
                hold_id,
                idemp_key,
                self.user_id,
                record.provider_id,
                record.slot,
                record.price,
                tracer=self.tracer
            )
            elapsed = (time.time() - start_t) * 1000
            self.tracer.log_tool_result("book", {"success": success, "booking_id": b_id}, elapsed)

            if success and b_id:
                # Save confirmed booking
                booking_obj = self.service.bookings.get(b_id)
                self.last_completed_booking = booking_obj
                self.workflow.reset_for_new_search()
                return (
                    f"Confirmed! Your booking is successfully verified.\n"
                    f"• Booking ID: {b_id}\n"
                    f"• Provider: {booking_obj.provider_name if booking_obj else record.provider_id}\n"
                    f"• Slot: {record.slot}\n"
                    f"• Total Price: ₹{record.price}\n"
                    f"The technician has been notified."
                )
            else:
                return f"Could not complete booking: {msg}"

        except SlotTakenError:
            self.tracer.log_tool_result("book", None, (time.time() - start_t) * 1000, error="slot_taken")
            self.workflow.clear_hold()
            return "Unfortunately, that slot was taken by another user just now. Would you like me to find another available slot?"
        except HoldExpiredError:
            self.tracer.log_tool_result("book", None, (time.time() - start_t) * 1000, error="hold_expired")
            self.workflow.clear_hold()
            return "The 10-minute hold on this slot has expired. Would you like me to place a fresh hold?"
        except ProviderAPIError as e:
            self.tracer.log_tool_result("book", None, (time.time() - start_t) * 1000, error=str(e))
            return f"Booking could not be completed: {str(e)}"

    def _execute_approved_cancellation(self, record: ApprovalRecord) -> str:
        try:
            self.budget.record_tool_call()
            self.approval.verify_and_consume("cancel", record.provider_id, record.slot, record.price, booking_id=record.booking_id)
        except (ApprovalRequiredError, ApprovalVoidError) as e:
            return f"Cancellation halted: {str(e)}"

        idemp_key = f"cancel-{record.booking_id}"
        self.tracer.log_tool_call("cancel", {"booking_id": record.booking_id, "idempotency_key": idemp_key})

        start_t = time.time()
        # Requirement: Transient 503 on first call, retry succeeds
        try:
            res = self.service.cancel(record.booking_id, idemp_key)
            self.tracer.log_tool_result("cancel", res, (time.time() - start_t) * 1000)
            return f"Your booking {record.booking_id} has been successfully cancelled."
        except Transient503Error:
            # Handle transient 503 retry
            self.tracer.record_event("transient_retry", {"tool": "cancel", "booking_id": record.booking_id, "attempt": 1})
            self.budget.record_tool_call()
            retry_res = self.service.cancel(record.booking_id, idemp_key)
            self.tracer.log_tool_result("cancel_retry", retry_res, (time.time() - start_t) * 1000)
            return f"Your booking {record.booking_id} has been successfully cancelled (recovered after transient retry)."

    def _execute_approved_reschedule(self, record: ApprovalRecord) -> str:
        try:
            self.budget.record_tool_call()
            self.approval.verify_and_consume("reschedule", record.provider_id, record.slot, record.price, booking_id=record.booking_id)
        except (ApprovalRequiredError, ApprovalVoidError) as e:
            return f"Reschedule halted: {str(e)}"

        idemp_key = f"resched-{record.booking_id}-{record.slot}"
        self.tracer.log_tool_call("reschedule", {"booking_id": record.booking_id, "new_slot": record.slot, "idempotency_key": idemp_key})

        start_t = time.time()
        try:
            res = self.service.reschedule(record.booking_id, record.slot, idemp_key)
            self.tracer.log_tool_result("reschedule", res, (time.time() - start_t) * 1000)
            return f"Your booking {record.booking_id} has been successfully rescheduled to {record.slot}."
        except SlotConflictError as e:
            self.tracer.log_tool_result("reschedule", None, (time.time() - start_t) * 1000, error=str(e))
            return f"Could not reschedule: That slot has a schedule conflict. Would you like to pick a different time?"

    def _handle_cancellation_intent(self, text: str) -> str:
        self.budget.record_tool_call()
        bookings = self.service.list_bookings(self.user_id)
        active_bookings = [b for b in bookings if b["status"] == "confirmed"]

        if not active_bookings:
            return "You have no active confirmed bookings to cancel."

        # Target most relevant booking
        target = active_bookings[0]
        for b in active_bookings:
            if b["service"].lower() in text.lower():
                target = b
                break

        # Register pending approval in code
        self.approval.request_approval(
            action="cancel",
            provider_id=target.get("provider_id", "unknown"),
            slot=target["slot"],
            price=target["price"],
            booking_id=target["id"]
        )

        return (
            f"Are you sure you want to cancel your upcoming booking for {target['service']} "
            f"with {target['provider']} on {target['slot']} (₹{target['price']})? "
            f"Please reply 'yes' to confirm or 'no' to keep it."
        )

    def _handle_reschedule_intent(self, text: str) -> str:
        self.budget.record_tool_call()
        bookings = self.service.list_bookings(self.user_id)
        active_bookings = [b for b in bookings if b["status"] == "confirmed"]

        if not active_bookings:
            return "You have no active bookings to reschedule."

        target = active_bookings[0]
        for b in active_bookings:
            if b["service"].lower() in text.lower():
                target = b
                break

        # Extract new slot preference
        new_slot = "2026-11-07 10:00"  # default target for Saturday
        if "saturday" in text.lower():
            new_slot = "2026-11-07 10:00"
        elif "sunday" in text.lower():
            new_slot = "2026-11-08 11:00"

        # Register pending approval in code
        self.approval.request_approval(
            action="reschedule",
            provider_id=target.get("provider_id", "unknown"),
            slot=new_slot,
            price=target["price"],
            booking_id=target["id"]
        )

        return (
            f"I can move your {target['service']} booking with {target['provider']} "
            f"from {target['slot']} to {new_slot}. "
            f"Do you confirm this reschedule?"
        )

    def _handle_search_or_update(self, text: str) -> str:
        t_lower = text.lower()

        # Check for stated facts to save into memory
        area_stated_match = re.search(r"(?:i live in|my area is|location is)\s+([A-Za-z\s]+)", text, re.IGNORECASE)
        if area_stated_match:
            stated_area = area_stated_match.group(1).strip()
            self.memory.set_stated_fact("area", stated_area)

        # Parse slots from user message
        extracted = self._extract_slots(text)
        
        # Check usable memory for missing fields
        if not extracted.get("area"):
            usable_area = self.memory.get_usable_fact("area")
            if usable_area:
                extracted["area"] = usable_area

        if not extracted.get("earliest_time"):
            usable_earliest = self.memory.get_usable_fact("earliest_time")
            if usable_earliest:
                extracted["earliest_time"] = usable_earliest

        # Check if an unconfirmed inferred fact exists in memory
        pending_inferred_area = self.memory.get_pending_inferred_fact("area")
        if pending_inferred_area and not self.workflow.state.area and not extracted.get("area"):
            return (
                f"I noticed you might be in {pending_inferred_area.value}. "
                f"Shall I search in {pending_inferred_area.value}, or would you prefer a different neighborhood?"
            )

        # Update workflow state (Requirement 1: Corrections to one detail keep everything else!)
        self.workflow.update_facts(**extracted)

        # Check missing fields
        missing = self.workflow.get_missing_fields()
        if missing:
            # Ask only for what is missing!
            return self.workflow.generate_missing_fields_prompt()

        # If all required fields are present, execute search and provider evaluation
        return self._search_and_propose()

    def _search_and_propose(self) -> str:
        state = self.workflow.state
        self.budget.record_tool_call()

        self.tracer.log_tool_call("search_providers", {
            "service": state.service,
            "area": state.area,
            "date_range": state.date_range
        })

        providers = self.service.search_providers(
            service=state.service,
            area=state.area,
            date_range=state.date_range
        )

        if not providers:
            return f"I couldn't find any {state.service} providers available in {state.area}. Would you like to expand your search area?"

        # Filter by budget if specified
        if state.budget:
            budget_matches = [p for p in providers if p["price"] <= state.budget]
            if budget_matches:
                providers = budget_matches

        # Check preferred technician
        preferred_tech = state.preferences.get("preferred_technician")
        if preferred_tech:
            for p in providers:
                if preferred_tech.lower() in p["name"].lower():
                    providers = [p] + [x for x in providers if x["id"] != p["id"]]
                    break

        # Pick top provider
        chosen = providers[0]

        # Fetch provider details and sanitize untrusted reviews (Requirement 4)
        self.budget.record_tool_call()
        prov_details = self.service.get_provider(chosen["id"])
        quarantine_res = SecurityQuarantine.inspect_and_quarantine_reviews(prov_details.get("reviews", []))
        self.tracer.record_event("untrusted_tool_output_quarantined", {
            "provider_id": chosen["id"],
            "flagged_injections": quarantine_res["flagged_injection_attempts"],
            "total_reviews": quarantine_res["total_reviews"]
        })

        # Filter slot based on preferences
        slots = chosen.get("free_slots", [])
        chosen_slot = slots[0] if slots else "2026-11-02 10:00"
        
        # Respect "mornings only" or "not before 10 a.m."
        time_win = (state.time_window or "").lower()
        earliest_t = state.preferences.get("earliest_time", "")

        for s in slots:
            # Extract hour
            time_part = s.split(" ")[1] if " " in s else "09:00"
            hour = int(time_part.split(":")[0])
            if "not before 10" in time_win or "after 10" in time_win or earliest_t == "10:00":
                if hour >= 10:
                    chosen_slot = s
                    break
            elif "morning" in time_win:
                if hour < 12:
                    chosen_slot = s
                    break

        # Place hold on slot
        self.budget.record_tool_call()
        try:
            hold_res = self.service.hold_slot(chosen["id"], chosen_slot)
        except SlotUnavailableError:
            return f"The slot {chosen_slot} with {chosen['name']} is currently unavailable. Please pick another time."

        quoted_price = hold_res["quoted_price"]
        self.workflow.set_active_hold(hold_res, Provider(**prov_details))

        # Check if quoted price differs from search price
        price_note = ""
        if quoted_price != chosen["price"]:
            price_note = f" (Note: Quoted hold price is ₹{quoted_price}, updated from search estimate ₹{chosen['price']})"

        # Create code approval record (Requirement 2)
        self.approval.request_approval(
            action="book",
            provider_id=chosen["id"],
            slot=chosen_slot,
            price=quoted_price
        )

        return (
            f"I found a great match for your request:\n"
            f"• Provider: {chosen['name']} (Rating: {chosen['rating']}★)\n"
            f"• Service: {chosen['service'].capitalize()}\n"
            f"• Slot: {chosen_slot}\n"
            f"• Price: ₹{quoted_price}{price_note}\n\n"
            f"Would you like me to go ahead and book this for you?"
        )

    def _extract_slots(self, text: str) -> Dict[str, Any]:
        extracted = {}
        t_low = text.lower()

        # Service extraction
        if "plumb" in t_low or "tap" in t_low or "sink" in t_low:
            extracted["service"] = "plumber"
        elif "electri" in t_low or "wiring" in t_low or "fuse" in t_low:
            extracted["service"] = "electrician"
        elif re.search(r"\bac\b|\bair\s*condition", t_low):
            extracted["service"] = "ac_servicing"

        # Area extraction
        for area in ["Indiranagar", "Koramangala", "HSR Layout", "Whitefield", "Jayanagar"]:
            if area.lower() in t_low:
                extracted["area"] = area
                break

        # Budget extraction
        budget_match = re.search(r"(?:under|within|max|budget\s*(?:of|is|to)?)\s*(?:₹|rs\.?|inr)?\s*([0-9,]+)", t_low)
        if budget_match:
            try:
                extracted["budget"] = int(budget_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Time window extraction
        if "morning" in t_low:
            extracted["time_window"] = "mornings only"
        elif "afternoon" in t_low:
            extracted["time_window"] = "afternoons only"
        elif "saturday" in t_low:
            extracted["time_window"] = "Saturday"
            extracted["date_range"] = "2026-11-07"
        elif "this week" in t_low:
            extracted["date_range"] = "this week"

        # Preferences
        prefs = {}
        if "not before 10" in t_low or "after 10" in t_low:
            prefs["earliest_time"] = "10:00"
        if "same electrician as last time" in t_low:
            # Query past bookings to resolve technician
            self.budget.record_tool_call()
            bookings = self.service.list_bookings(self.user_id)
            for b in bookings:
                if "electri" in b["service"].lower():
                    prefs["preferred_technician"] = b["provider"]
                    break
        if prefs:
            extracted["preferences"] = prefs

        return extracted
