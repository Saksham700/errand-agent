from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from errand_agent.models import WorkflowState, HoldSlotResult, Provider

class WorkflowManager:
    """
    Manages explicit conversational state for booking errands.
    Enforces:
    1. Ask only for what's missing (service, area, time window / date, budget, preferences).
    2. Never re-ask a known fact.
    3. Corrections to one detail preserve all other existing facts.
    """
    def __init__(self, user_id: str):
        self.state = WorkflowState(user_id=user_id)
        self.suggested_providers: List[Dict[str, Any]] = []

    def update_facts(self, **kwargs) -> Dict[str, Any]:
        """Update specific facts while preserving existing state."""
        updated = {}
        for k, v in kwargs.items():
            if v is not None:
                if k == "preferences" and isinstance(v, dict):
                    self.state.preferences.update(v)
                    updated[k] = self.state.preferences
                elif hasattr(self.state, k):
                    setattr(self.state, k, v)
                    updated[k] = v
        return updated

    def get_missing_fields(self) -> List[str]:
        """Returns ordered list of essential fields that are still missing."""
        missing = []
        if not self.state.service:
            missing.append("service")
        if not self.state.area:
            missing.append("area")
        if not self.state.date_range and not self.state.time_window:
            missing.append("time_window")
        return missing

    def generate_missing_fields_prompt(self) -> Optional[str]:
        """Generate a focused question asking strictly for missing facts without re-asking known facts."""
        missing = self.get_missing_fields()
        if not missing:
            return None

        # Check what we already know to frame contextual response if needed
        known_parts = []
        if self.state.service:
            known_parts.append(f"service: {self.state.service}")
        if self.state.area:
            known_parts.append(f"area: {self.state.area}")
        if self.state.date_range or self.state.time_window:
            known_parts.append(f"time: {self.state.date_range or self.state.time_window}")
        if self.state.budget:
            known_parts.append(f"budget: ₹{self.state.budget}")

        if len(missing) == 1:
            field = missing[0]
            if field == "service":
                return "What service do you need help with? (e.g. plumber, electrician, AC servicing)"
            elif field == "area":
                return f"Got it for {self.state.service}. Which neighborhood or area are you located in? (e.g. Indiranagar, Koramangala, HSR Layout)"
            elif field == "time_window":
                return f"Understood. When would you like the {self.state.service} to visit? (e.g. this week, tomorrow morning, Saturday after 10 a.m.)"

        questions = []
        if "service" in missing:
            questions.append("the type of service")
        if "area" in missing:
            questions.append("your area / neighborhood")
        if "time_window" in missing:
            questions.append("your preferred date or time window")

        return f"To assist you, could you please provide {' and '.join(questions)}?"

    def is_ready_for_search(self) -> bool:
        return self.state.is_ready_for_search()

    def set_active_hold(self, hold: Any, provider: Optional[Provider] = None) -> None:
        if isinstance(hold, dict):
            self.state.active_hold = HoldSlotResult(
                hold_id=hold["hold_id"],
                provider_id=hold["provider_id"],
                slot=hold["slot"],
                quoted_price=hold["quoted_price"],
                expires_at=hold.get("expires_at", 0)
            )
        else:
            self.state.active_hold = hold
        if provider:
            self.state.last_suggested_provider = provider

    def clear_hold(self) -> None:
        self.state.active_hold = None

    def reset_for_new_search(self) -> None:
        """Reset operational slots while retaining user ID and persistent preferences."""
        self.state.service = None
        self.state.date_range = None
        self.state.time_window = None
        self.state.budget = None
        self.state.active_hold = None
        self.state.active_action = None
        self.state.target_booking_id = None
        self.suggested_providers = []
