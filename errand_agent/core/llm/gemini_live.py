from __future__ import annotations
import os
import time
import requests
from typing import Any, Dict, Optional, Tuple
from errand_agent.core.llm.base import BaseLLM

class GeminiLiveLLM(BaseLLM):
    """
    Live Gemini LLM adapter using the official Google Gemini REST API.
    Optionally enabled if GEMINI_API_KEY is configured.
    """
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def generate(self, prompt: str, system_prompt: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        url = f"{self.base_url}?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 600
            }
        }
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        start = time.time()
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            latency_ms = (time.time() - start) * 1000
            
            if resp.status_code == 200:
                data = resp.json()
                text = ""
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts)
                
                usage = data.get("usageMetadata", {})
                tokens = {
                    "prompt_tokens": usage.get("promptTokenCount", len(prompt) // 4),
                    "completion_tokens": usage.get("candidatesTokenCount", len(text) // 4),
                    "total_tokens": usage.get("totalTokenCount", (len(prompt) + len(text)) // 4)
                }
                # Approximate Gemini 1.5 Flash cost: $0.075 / 1M prompt, $0.30 / 1M completion
                cost_usd = (tokens["prompt_tokens"] * 0.000000075) + (tokens["completion_tokens"] * 0.00000030)

                return text.strip(), {
                    "tokens": tokens,
                    "latency_ms": latency_ms,
                    "cost_usd": cost_usd,
                    "model": self.model
                }
            else:
                # Return error details without leaking API key
                return f"[Gemini API returned error {resp.status_code}]", {
                    "tokens": {"total_tokens": 0},
                    "latency_ms": latency_ms,
                    "cost_usd": 0.0,
                    "error": resp.text[:200]
                }
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            return f"[Error invoking Gemini API: {str(e)}]", {
                "tokens": {"total_tokens": 0},
                "latency_ms": latency_ms,
                "cost_usd": 0.0,
                "error": str(e)
            }
