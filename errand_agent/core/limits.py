from __future__ import annotations
import time
from typing import Optional

class LimitExhaustedError(Exception):
    def __init__(self, limit_type: str, message: str):
        super().__init__(message)
        self.limit_type = limit_type
        self.user_message = message

class ExecutionBudget:
    """
    Enforces bounded execution:
    - Hard caps on model turns
    - Hard caps on tool calls
    - Hard cap on wall-clock time
    - Clean user-facing exit message on exhaustion
    """
    def __init__(
        self,
        max_turns: int = 10,
        max_tool_calls: int = 15,
        max_wall_clock_seconds: float = 30.0
    ):
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.max_wall_clock_seconds = max_wall_clock_seconds
        self.turns_count = 0
        self.tool_calls_count = 0
        self.start_time = time.time()
        self.turn_start_time = time.time()

    def start_turn(self) -> None:
        """Reset the wall-clock timer for the current active processing turn."""
        self.turn_start_time = time.time()

    def record_turn(self) -> None:
        self.turns_count += 1
        self.check_limits()

    def record_tool_call(self) -> None:
        self.tool_calls_count += 1
        self.check_limits()

    def check_limits(self) -> None:
        # Measure active processing time of the current turn
        elapsed = time.time() - self.turn_start_time
        if elapsed > self.max_wall_clock_seconds:
            raise LimitExhaustedError(
                "wall_clock_time",
                f"I took longer than expected to process your request ({elapsed:.1f}s > {self.max_wall_clock_seconds:.1f}s limit). I have halted safely to protect your account. Please let me know how you'd like to proceed."
            )

        if self.turns_count > self.max_turns:
            raise LimitExhaustedError(
                "turn_cap",
                f"I've reached the maximum conversational turn limit ({self.max_turns} turns) for this session. To prevent circular conversations, I've paused here. Would you like me to start fresh?"
            )

        if self.tool_calls_count > self.max_tool_calls:
            raise LimitExhaustedError(
                "tool_calls_cap",
                f"I reached the maximum allowable backend operations ({self.max_tool_calls} tool calls) without completing the request. I have stopped safely to avoid duplicate actions. Please try again with more specific constraints."
            )

    def stats(self) -> dict:
        return {
            "turns_used": self.turns_count,
            "max_turns": self.max_turns,
            "tool_calls_used": self.tool_calls_count,
            "max_tool_calls": self.max_tool_calls,
            "elapsed_seconds": round(time.time() - self.start_time, 3),
            "max_wall_clock_seconds": self.max_wall_clock_seconds
        }
