"""In-memory, thread-safe state store.

Holds everything the bot must remember across calls: versioned contexts
(category/merchant/customer/trigger), open conversations, and suppression
history. A single process, in-memory dict is sufficient per the testing
brief ("storing in memory is fine; just don't restart between calls").
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ContextEntry:
    version: int
    payload: dict[str, Any]


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    trigger_id: Optional[str] = None
    send_as: str = "vera"
    status: str = "open"  # open | waiting | ended
    turns: list[dict[str, Any]] = field(default_factory=list)
    sent_bodies: list[str] = field(default_factory=list)
    auto_reply_streak: int = 0
    last_auto_reply_text: Optional[str] = None
    wait_until_epoch: Optional[float] = None
    accepted_intent: bool = False
    created_epoch: float = field(default_factory=time.time)


class AppState:
    """Process-wide singleton. All access goes through the lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.start_time = time.time()
        self.contexts: dict[tuple[str, str], ContextEntry] = {}
        self.conversations: dict[str, ConversationState] = {}
        # suppression_key -> {"last_sent_epoch": float, "count": int}
        self.suppression: dict[str, dict[str, Any]] = {}
        # merchant_id -> epoch until which ALL outbound is suppressed (opt-out / hostility)
        self.merchant_opt_out_until: dict[str, float] = {}
        self._ack_counter = 0

    # -- contexts ---------------------------------------------------------

    def push_context(self, scope: str, context_id: str, version: int, payload: dict) -> tuple[bool, dict]:
        with self._lock:
            key = (scope, context_id)
            current = self.contexts.get(key)
            if current is not None and version <= current.version:
                # Per api-call-examples.md §1.5, re-posting the same (or a lower)
                # version returns 409 stale_version — it is a no-op on state,
                # but NOT reported as accepted.
                return False, {"reason": "stale_version", "current_version": current.version}
            self.contexts[key] = ContextEntry(version=version, payload=payload)
            self._ack_counter += 1
            return True, {"ack_id": f"ack_{context_id}_v{version}_{self._ack_counter}"}

    def get_context(self, scope: str, context_id: str) -> Optional[dict]:
        with self._lock:
            entry = self.contexts.get((scope, context_id))
            return entry.payload if entry else None

    def contexts_loaded_counts(self) -> dict[str, int]:
        with self._lock:
            counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
            for (scope, _cid) in self.contexts:
                if scope in counts:
                    counts[scope] += 1
            return counts

    # -- conversations ------------------------------------------------------

    def get_or_create_conversation(self, conversation_id: str, **defaults) -> ConversationState:
        with self._lock:
            conv = self.conversations.get(conversation_id)
            if conv is None:
                conv = ConversationState(conversation_id=conversation_id, **defaults)
                self.conversations[conversation_id] = conv
            return conv

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        with self._lock:
            return self.conversations.get(conversation_id)

    # -- suppression --------------------------------------------------------

    def is_suppressed(self, suppression_key: str) -> bool:
        with self._lock:
            return suppression_key in self.suppression

    def mark_sent(self, suppression_key: str) -> None:
        with self._lock:
            entry = self.suppression.setdefault(suppression_key, {"count": 0})
            entry["count"] += 1
            entry["last_sent_epoch"] = time.time()

    def opt_out_merchant(self, merchant_id: str, seconds: float) -> None:
        with self._lock:
            until = time.time() + seconds
            existing = self.merchant_opt_out_until.get(merchant_id, 0)
            self.merchant_opt_out_until[merchant_id] = max(existing, until)

    def is_merchant_opted_out(self, merchant_id: str) -> bool:
        with self._lock:
            until = self.merchant_opt_out_until.get(merchant_id)
            return bool(until and until > time.time())

    def uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)

    def reset(self) -> None:
        with self._lock:
            self.contexts.clear()
            self.conversations.clear()
            self.suppression.clear()
            self.merchant_opt_out_until.clear()


# Process-wide singleton used by all routers/engine modules.
state = AppState()
