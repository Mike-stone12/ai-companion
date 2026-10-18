from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from companion.core.memory.store import clip_memory_text

if TYPE_CHECKING:
    from companion.core.memory.consolidator import ConsolidationDecision


@dataclass(frozen=True)
class ApplyResult:
    entries: list[dict[str, str]]
    action_applied: Literal["ADD", "UPDATE", "NOOP"]
    fallback_to_add: bool = False
    deferred_delete: bool = False
    deferred_delete_target: int | None = None


def apply_consolidation(
    entries: list[dict[str, str]],
    candidate: dict[str, str],
    decision: ConsolidationDecision,
    *,
    now: Callable[[], str],
    limit: int = 24,
) -> ApplyResult:
    """Apply a decision to copied MemoryStore entries without persistence.

    Targets index the supplied entries, which must match the list used to request
    the decision. UPDATE preserves position and metadata, refreshing updated_at
    for recency recall. A missing or invalid target adds the original candidate,
    rather than a summary merged with a now-missing memory.

    ADD uses the decision summary and candidate metadata, normalizing text like
    MemoryStore. Exact duplicates and empty summaries are NOOPs. New entries are
    appended; on overflow, retain the newest ``limit`` entries by updated_at, as
    MemoryStore.upsert_many does. The limit must be nonnegative.

    DELETE never removes entries: it returns a deferred flag and target for later
    human review. NOOP and deferred DELETE leave values unchanged. Every result
    owns a new list and new entry dictionaries. The injected clock returns an ISO
    timestamp in the store's UTC format and is called only for an ADD or UPDATE.
    """
    if limit < 0:
        raise ValueError("limit must be nonnegative")

    result = [dict(item) for item in entries]
    if decision.action == "DELETE":
        return ApplyResult(result, "NOOP", deferred_delete=True, deferred_delete_target=decision.target)
    if decision.action == "NOOP":
        return ApplyResult(result, "NOOP")

    target = decision.target
    fallback = decision.action == "UPDATE" and (type(target) is not int or not 0 <= target < len(result))
    text = candidate.get("summary", "") if fallback or decision.summary is None else decision.summary
    summary = clip_memory_text(str(text).strip())
    if not summary:
        return ApplyResult(result, "NOOP", fallback_to_add=fallback)

    if decision.action == "UPDATE" and not fallback:
        result[target]["summary"] = summary
        result[target]["updated_at"] = now()
        return ApplyResult(result, "UPDATE")

    if any(item.get("summary") == summary for item in result):
        return ApplyResult(result, "NOOP", fallback_to_add=fallback)

    result.append(
        {
            "summary": summary,
            "category": str(candidate.get("category", "memory") or "memory"),
            "source": str(candidate.get("source", "") or ""),
            "updated_at": now(),
        }
    )
    if len(result) > limit:
        result = sorted(result, key=lambda item: item.get("updated_at", ""), reverse=True)[:limit]
    return ApplyResult(result, "ADD", fallback_to_add=fallback)
