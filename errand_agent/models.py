from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import time
import uuid

class ApprovalStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    VOID = "void"

class MemorySource(str, Enum):
    STATED = "stated"
    INFERRED = "inferred"

@dataclass
class Provider:
    id: str
    name: str
    service: str
    area: str
    price: int
    rating: float
    free_slots: List[str]
    attributes: Dict[str, Any] = field(default_factory=dict)
    reviews: List[str] = field(default_factory=list)

@dataclass
class HoldSlotResult:
    hold_id: str
    provider_id: str
    slot: str
    quoted_price: int
    expires_at: float  # unix epoch in seconds

@dataclass
class Booking:
    id: str
    user_id: str
    provider_id: str
    provider_name: str
    service: str
    slot: str
    price: int
    status: str  # "confirmed", "cancelled", "rescheduled"
    idempotency_key: str
    created_at: float = field(default_factory=time.time)

@dataclass
class ApprovalRecord:
    action: str  # "book", "cancel", "reschedule"
    provider_id: str
    slot: str
    price: int
    booking_id: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    confirmed_at: Optional[float] = None
    void_reason: Optional[str] = None

    def is_valid_for(self, action: str, provider_id: str, slot: str, price: int, booking_id: Optional[str] = None) -> bool:
        if self.status != ApprovalStatus.APPROVED:
            return False
        if self.action != action:
            return False
        if self.provider_id != provider_id:
            return False
        if self.slot != slot:
            return False
        if self.price != price:
            return False
        if booking_id is not None and self.booking_id != booking_id:
            return False
        return True

    def void(self, reason: str) -> None:
        self.status = ApprovalStatus.VOID
        self.void_reason = reason

@dataclass
class WorkflowState:
    user_id: str
    service: Optional[str] = None
    area: Optional[str] = None
    date_range: Optional[str] = None
    time_window: Optional[str] = None
    budget: Optional[int] = None
    preferences: Dict[str, Any] = field(default_factory=dict)
    active_hold: Optional[HoldSlotResult] = None
    target_booking_id: Optional[str] = None  # for cancel / reschedule
    active_action: Optional[str] = None      # "book", "cancel", "reschedule"
    last_suggested_provider: Optional[Provider] = None

    def get_missing_fields(self) -> List[str]:
        missing = []
        if not self.service:
            missing.append("service")
        if not self.area:
            missing.append("area")
        if not self.date_range and not self.time_window:
            missing.append("time window / date range")
        return missing

    def is_ready_for_search(self) -> bool:
        return bool(self.service and self.area and (self.date_range or self.time_window))

    def update_detail(self, **kwargs) -> None:
        """Update only specific fields, preserving all other existing facts."""
        for k, v in kwargs.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)

@dataclass
class MemoryFact:
    key: str
    value: Any
    source: MemorySource
    confirmed_by_user: bool = False
    updated_at: float = field(default_factory=time.time)

@dataclass
class TraceEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""  # state_transition, model_call, tool_call, tool_result, approval, user_message, agent_message, limit_exhausted
    payload: Dict[str, Any] = field(default_factory=dict)
    latency_ms: Optional[float] = None
    tokens: Optional[Dict[str, int]] = None
    cost_usd: Optional[float] = None
