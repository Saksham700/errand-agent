from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
        """
        Returns (response_text, telemetry_dict).
        telemetry_dict contains tokens, latency_ms, cost_usd.
        """
        pass
