"""Thread-safe in-memory Product Library adapter."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable

from ..errors import ProductKnowledgeError, ProductKnowledgeErrorCode
from .authority import require_product_knowledge_writer


def empty_library_state() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": 0,
        "products": {},
        "feedback_events": {},
        "rules": {},
        "conflicts": {},
        "audit": [],
        "idempotency": {},
    }


class InMemoryProductLibrary:
    """A deterministic adapter with copy-on-read and atomic commits."""

    def __init__(self) -> None:
        self._state = empty_library_state()
        self._lock = RLock()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def commit(
        self,
        *,
        writer_authority: object,
        command: str,
        idempotency_key: str,
        input_digest: str,
        actor: str,
        reason: str,
        expected_revision: int,
        update: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock:
            require_product_knowledge_writer(writer_authority)
            replay = self._state["idempotency"].get(idempotency_key)
            if replay is not None:
                if replay["command"] != command or replay["input_digest"] != input_digest:
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.IDEMPOTENCY_MISMATCH,
                        "Idempotency key was already used for a different command input",
                    )
                return deepcopy(replay["result"])
            if self._state["revision"] != expected_revision:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.LIBRARY_VERSION_CONFLICT,
                    "Product Library revision changed",
                    retryable=True,
                    details={
                        "expected_revision": expected_revision,
                        "actual_revision": self._state["revision"],
                    },
                )
            next_state = deepcopy(self._state)
            result = update(next_state)
            before_revision = next_state["revision"]
            next_state["revision"] = before_revision + 1
            next_state["idempotency"][idempotency_key] = {
                "command": command,
                "input_digest": input_digest,
                "result": deepcopy(result),
            }
            next_state["audit"].append(
                {
                    "audit_id": f"audit-{next_state['revision']:012d}",
                    "writer_id": "product-knowledge",
                    "command": command,
                    "actor": actor,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                    "input_digest": input_digest,
                    "before_revision": before_revision,
                    "after_revision": next_state["revision"],
                    "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            )
            self._state = next_state
            return deepcopy(result)
