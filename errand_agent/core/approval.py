from __future__ import annotations
import time
from typing import Dict, Optional, Tuple
from errand_agent.models import ApprovalRecord, ApprovalStatus

class ApprovalError(Exception):
    pass

class ApprovalRequiredError(ApprovalError):
    pass

class ApprovalVoidError(ApprovalError):
    pass

class ApprovalStore:
    """
    Code-enforced approval system.
    Guarantees that book, cancel, and reschedule can only execute if an explicit,
    valid ApprovalRecord matching exact action, provider, slot, and price exists in code.
    Any change to provider, slot, or price voids prior approval.
    """
    def __init__(self):
        self.active_record: Optional[ApprovalRecord] = None
        self.history: list[ApprovalRecord] = []

    def request_approval(self, action: str, provider_id: str, slot: str, price: int, booking_id: Optional[str] = None) -> ApprovalRecord:
        """Create a new pending approval record."""
        # If an active record existed, void it because details or action are being re-requested
        if self.active_record and self.active_record.status == ApprovalStatus.PENDING:
            self.active_record.void("Superceded by new approval proposal")
            self.history.append(self.active_record)

        record = ApprovalRecord(
            action=action,
            provider_id=provider_id,
            slot=slot,
            price=price,
            booking_id=booking_id,
            status=ApprovalStatus.PENDING
        )
        self.active_record = record
        return record

    def user_confirmed(self) -> Tuple[bool, str]:
        """User explicitly confirmed the pending proposal."""
        if not self.active_record:
            return False, "No active proposal to confirm."
        if self.active_record.status == ApprovalStatus.APPROVED:
            return True, "Proposal was already confirmed."
        if self.active_record.status != ApprovalStatus.PENDING:
            return False, f"Cannot confirm proposal in status: {self.active_record.status.value}"

        self.active_record.status = ApprovalStatus.APPROVED
        self.active_record.confirmed_at = time.time()
        return True, "Approval recorded."

    def user_rejected(self, reason: str = "User declined") -> None:
        """User explicitly rejected proposal."""
        if self.active_record:
            self.active_record.status = ApprovalStatus.REJECTED
            self.active_record.void_reason = reason
            self.history.append(self.active_record)
            self.active_record = None

    def check_or_void_on_parameter_change(self, provider_id: str, slot: str, price: int) -> bool:
        """
        If parameters changed from what was presented/approved, immediately void.
        Returns True if parameters match, False if voided.
        """
        if not self.active_record:
            return False

        if (self.active_record.provider_id != provider_id or 
            self.active_record.slot != slot or 
            self.active_record.price != price):
            old_desc = f"provider={self.active_record.provider_id}, slot={self.active_record.slot}, price={self.active_record.price}"
            new_desc = f"provider={provider_id}, slot={slot}, price={price}"
            self.active_record.void(f"Parameters changed: ({old_desc}) -> ({new_desc})")
            self.history.append(self.active_record)
            # Retain active_record in VOID status so verify_and_consume can report ApprovalVoidError
            return False
        return True

    def verify_and_consume(self, action: str, provider_id: str, slot: str, price: int, booking_id: Optional[str] = None) -> ApprovalRecord:
        """
        Strict code verification before tool execution.
        Must match action, provider, slot, price, booking_id.
        """
        record = self.active_record
        if not record:
            raise ApprovalRequiredError("Action blocked: No approval record exists.")

        if record.status == ApprovalStatus.VOID:
            raise ApprovalVoidError(f"Action blocked: Approval was voided ({record.void_reason}).")

        if record.status != ApprovalStatus.APPROVED:
            raise ApprovalRequiredError(f"Action blocked: Proposal status is '{record.status.value}', user approval is mandatory.")

        if not record.is_valid_for(action, provider_id, slot, price, booking_id):
            record.void(f"Mismatch between approved parameters and target parameters: approved=({record.action}, {record.provider_id}, {record.slot}, {record.price}) vs target=({action}, {provider_id}, {slot}, {price})")
            self.history.append(record)
            self.active_record = None
            raise ApprovalVoidError(f"Action blocked: Parameters differed from approved record. Approval voided.")

        # Successfully verified and consumed!
        self.history.append(record)
        # Note: Do not clear immediately if idempotent retry might occur within the same verified operation,
        # but mark as consumed to prevent duplicate different actions
        return record
