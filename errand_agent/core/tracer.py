from __future__ import annotations
import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional
from errand_agent.models import TraceEvent

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),
    re.compile(r"sk-[0-9A-Za-z]{32,}"),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"password['\"]?\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE)
]

def sanitize_secrets(obj: Any) -> Any:
    """Recursively redacts any API keys or secrets from trace payloads."""
    if isinstance(obj, str):
        sanitized = obj
        for pat in SECRET_PATTERNS:
            sanitized = pat.sub("[REDACTED_SECRET]", sanitized)
        return sanitized
    elif isinstance(obj, dict):
        return {k: sanitize_secrets(v) for k, v in obj.items() if "secret" not in k.lower() and "key" not in k.lower() or "idempotency" in k.lower()}
    elif isinstance(obj, list):
        return [sanitize_secrets(elem) for elem in obj]
    return obj

class ExecutionTracer:
    """
    Collects rich observability traces for every run:
    - State transitions
    - Model calls (with prompt, response, latency, tokens, cost)
    - Tool calls + sanitized arguments and outputs
    - Approval verification checks
    - Security quarantine events
    - Hard limit enforcement
    - Strict redaction of secrets
    """
    def __init__(self, run_id: Optional[str] = None):
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:10]}"
        self.start_time = time.time()
        self.events: List[TraceEvent] = []

    def record_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        latency_ms: Optional[float] = None,
        tokens: Optional[Dict[str, int]] = None,
        cost_usd: Optional[float] = None
    ) -> TraceEvent:
        clean_payload = sanitize_secrets(payload)
        event = TraceEvent(
            timestamp=time.time(),
            event_type=event_type,
            payload=clean_payload,
            latency_ms=round(latency_ms, 2) if latency_ms is not None else None,
            tokens=tokens,
            cost_usd=round(cost_usd, 6) if cost_usd is not None else None
        )
        self.events.append(event)
        return event

    def log_state_transition(self, from_state: str, to_state: str, details: Optional[Dict[str, Any]] = None) -> None:
        self.record_event("state_transition", {
            "from_state": from_state,
            "to_state": to_state,
            "details": details or {}
        })

    def log_model_call(self, prompt: str, response: str, latency_ms: float, tokens: Optional[Dict[str, int]] = None, cost_usd: Optional[float] = None) -> None:
        self.record_event(
            "model_call",
            {"prompt_summary": prompt[:200] + ("..." if len(prompt) > 200 else ""), "response": response},
            latency_ms=latency_ms,
            tokens=tokens or {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(response) // 4, "total_tokens": (len(prompt) + len(response)) // 4},
            cost_usd=cost_usd or 0.0
        )

    def log_tool_call(self, tool_name: str, args: Dict[str, Any]) -> None:
        self.record_event("tool_call", {"tool": tool_name, "arguments": args})

    def log_tool_result(self, tool_name: str, result: Any, latency_ms: float, error: Optional[str] = None) -> None:
        self.record_event("tool_result", {
            "tool": tool_name,
            "result": result,
            "error": error
        }, latency_ms=latency_ms)

    def log_approval_check(self, action: str, approved: bool, reason: str, details: Dict[str, Any]) -> None:
        self.record_event("approval_check", {
            "action": action,
            "approved": approved,
            "reason": reason,
            "details": details
        })

    def log_user_message(self, message: str) -> None:
        self.record_event("user_message", {"content": message})

    def log_agent_message(self, message: str) -> None:
        self.record_event("agent_message", {"content": message})

    def to_dict(self) -> Dict[str, Any]:
        total_latency = (time.time() - self.start_time) * 1000
        total_tokens = sum((e.tokens.get("total_tokens", 0) for e in self.events if e.tokens), 0)
        total_cost = sum((e.cost_usd for e in self.events if e.cost_usd), 0.0)
        return {
            "run_id": self.run_id,
            "start_time": self.start_time,
            "total_latency_ms": round(total_latency, 2),
            "total_events": len(self.events),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "events": [
                {
                    "event_id": e.event_id,
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "payload": e.payload,
                    "latency_ms": e.latency_ms,
                    "tokens": e.tokens,
                    "cost_usd": e.cost_usd
                }
                for e in self.events
            ]
        }

    def export_json(self, filepath: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
