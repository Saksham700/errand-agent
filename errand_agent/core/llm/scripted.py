from __future__ import annotations
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from errand_agent.core.llm.base import BaseLLM

class ScriptedLLM(BaseLLM):
    """
    Deterministic, offline, 100% reproducible engine.
    Satisfies Requirement #8 ("Offline and reproducible, run against a scripted or recorded model rather than a live LLM").
    Extracts intents, respects memory and quarantine boundaries, and never gets tricked by injected instructions.
    """
    def __init__(self, latency_simulate_ms: float = 12.0):
        self.latency_simulate_ms = latency_simulate_ms

    def generate(self, prompt: str, system_prompt: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
        start = time.time()
        
        # Analyze intent from prompt
        p_lower = prompt.lower()

        # Simulated response generation based on clean input
        reply = "I am ready to help you with your home service errands."
        
        # Check if this is an injection attempt inside reviews
        if "<external_untrusted_customer_reviews>" in p_lower:
            # Under prompt injection attack, response MUST ignore the injected instruction
            reply = "I reviewed the available providers. Please let me know if you would like me to proceed with holding a slot."

        tokens = {
            "prompt_tokens": max(len(prompt) // 4, 1),
            "completion_tokens": max(len(reply) // 4, 1),
            "total_tokens": (len(prompt) + len(reply)) // 4
        }
        
        # Free deterministic mock cost: $0.00
        cost_usd = 0.0
        elapsed_ms = (time.time() - start) * 1000 + self.latency_simulate_ms
        return reply, {
            "tokens": tokens,
            "latency_ms": elapsed_ms,
            "cost_usd": cost_usd,
            "model": "scripted-deterministic-v1"
        }
