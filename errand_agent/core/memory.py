from __future__ import annotations
import json
import os
import time
from typing import Any, Dict, List, Optional
from errand_agent.models import MemoryFact, MemorySource

class MemoryStore:
    """
    Persists stable preferences across sessions (area, earliest time, preferred technician).
    Rules:
    - Mark each fact as stated by user or inferred by agent.
    - Inferred facts are NEVER used without confirmation.
    - Users can view, correct, and forget facts.
    - Forgotten facts are tombstoned and never reused.
    """
    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path
        self.facts: Dict[str, MemoryFact] = {}
        self.tombstones: set[str] = set()
        if storage_path and os.path.exists(storage_path):
            self.load()

    def set_stated_fact(self, key: str, value: Any) -> MemoryFact:
        """User explicitly stated a preference."""
        if key in self.tombstones:
            self.tombstones.remove(key)  # User explicitly re-stating removes tombstone
        fact = MemoryFact(
            key=key,
            value=value,
            source=MemorySource.STATED,
            confirmed_by_user=True,
            updated_at=time.time()
        )
        self.facts[key] = fact
        self.save()
        return fact

    def set_inferred_fact(self, key: str, value: Any) -> Optional[MemoryFact]:
        """Agent inferred a preference from behavior."""
        if key in self.tombstones:
            # Forgotten facts are never reused or re-inferred
            return None
        # Don't overwrite an already stated fact with an inferred one
        existing = self.facts.get(key)
        if existing and existing.source == MemorySource.STATED:
            return existing

        fact = MemoryFact(
            key=key,
            value=value,
            source=MemorySource.INFERRED,
            confirmed_by_user=False,
            updated_at=time.time()
        )
        self.facts[key] = fact
        self.save()
        return fact

    def confirm_inferred_fact(self, key: str) -> bool:
        """User confirms an inferred fact."""
        fact = self.facts.get(key)
        if fact and fact.source == MemorySource.INFERRED:
            fact.confirmed_by_user = True
            fact.updated_at = time.time()
            self.save()
            return True
        return False

    def get_usable_fact(self, key: str) -> Optional[Any]:
        """
        Returns fact value ONLY if it is safe to use.
        Inferred facts are NEVER used without user confirmation.
        Forgotten facts are never reused.
        """
        if key in self.tombstones:
            return None
        fact = self.facts.get(key)
        if not fact:
            return None
        if fact.source == MemorySource.STATED:
            return fact.value
        if fact.source == MemorySource.INFERRED and fact.confirmed_by_user:
            return fact.value
        return None  # Unconfirmed inferred fact cannot be used silently

    def get_pending_inferred_fact(self, key: str) -> Optional[MemoryFact]:
        fact = self.facts.get(key)
        if fact and fact.source == MemorySource.INFERRED and not fact.confirmed_by_user:
            return fact
        return None

    def forget_fact(self, key: str) -> bool:
        """Permanently forgets a fact and tombstones it so it is never reused."""
        existed = key in self.facts
        if existed:
            del self.facts[key]
        self.tombstones.add(key)
        self.save()
        return existed

    def view_memory(self) -> List[Dict[str, Any]]:
        """Return human-readable listing of all stored facts."""
        items = []
        for key, f in self.facts.items():
            items.append({
                "key": key,
                "value": f.value,
                "source": f.source.value,
                "confirmed": f.confirmed_by_user,
                "usable": (f.source == MemorySource.STATED) or (f.source == MemorySource.INFERRED and f.confirmed_by_user)
            })
        return items

    def save(self) -> None:
        if not self.storage_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
        data = {
            "facts": {
                k: {
                    "key": v.key,
                    "value": v.value,
                    "source": v.source.value,
                    "confirmed_by_user": v.confirmed_by_user,
                    "updated_at": v.updated_at
                }
                for k, v in self.facts.items()
            },
            "tombstones": list(self.tombstones)
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self) -> None:
        if not self.storage_path or not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.tombstones = set(data.get("tombstones", []))
            self.facts = {}
            for k, v in data.get("facts", {}).items():
                self.facts[k] = MemoryFact(
                    key=v["key"],
                    value=v["value"],
                    source=MemorySource(v["source"]),
                    confirmed_by_user=v.get("confirmed_by_user", False),
                    updated_at=v.get("updated_at", time.time())
                )
        except Exception:
            self.facts = {}
            self.tombstones = set()
