from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from companion.core.memory import store as store_module
from companion.core.memory.apply import apply_consolidation
from companion.core.memory.consolidator import ConsolidationDecision, parse_consolidation_response
from companion.core.memory.store import MemoryStore, utc_now_iso


@dataclass(frozen=True)
class ConsolidationResult:
    entries: list[dict[str, str]]
    counts: dict[str, int]
    fallback_count: int


def consolidate_candidates(
    existing: list[dict[str, str]],
    candidates: list[dict[str, str]],
    request_decision: Callable[[str, list[str]], ConsolidationDecision | str | None],
    *,
    now: Callable[[], str] = utc_now_iso,
) -> ConsolidationResult:
    """Consolidate candidates in order against a copied, evolving memory list.

    The callable takes candidate text and current summaries, as in ``decide``
    with its client bound. It returns a validated decision, a raw reply to parse,
    or None on failure. Exceptions also trigger fallback. For observable failure
    counts, the callable must signal failure rather than hide it as an ADD (as
    ``decide`` currently does).

    Counts describe applied ADD/UPDATE/NOOP outcomes, except deferred DELETE is
    counted as DELETE, never NOOP. Each candidate contributes exactly one count.
    Fallbacks add the original candidate with the apply helper's normalization
    and exact-summary deduplication; fallback_count includes deduplicated NOOPs
    and invalid UPDATE targets handled by that helper.

    Inputs are not mutated, and returned entries own their dictionaries. No
    retention trimming occurs here; persistence and retention belong to the store.
    """
    entries = [dict(item) for item in existing]
    counts = {"ADD": 0, "UPDATE": 0, "DELETE": 0, "NOOP": 0}
    fallback_count = 0

    for candidate in candidates:
        summary = candidate.get("summary", "")
        try:
            decision = request_decision(summary, [item.get("summary", "") for item in entries])
            if isinstance(decision, str):
                decision = parse_consolidation_response(decision, len(entries))
        except Exception:
            # A failed candidate must not abort the batch or expose memory text.
            decision = None

        failed = decision is None
        if failed:
            decision = ConsolidationDecision("ADD", None, summary)

        applied = apply_consolidation(entries, candidate, decision, now=now, limit=len(entries) + 1)
        entries = applied.entries
        action = "DELETE" if applied.deferred_delete else applied.action_applied
        counts[action] += 1
        fallback_count += int(failed or applied.fallback_to_add)

    return ConsolidationResult(entries, counts, fallback_count)


@dataclass(frozen=True)
class StoreConsolidationSummary:
    added: int
    updated: int
    unchanged: int
    fallback_count: int = 0


def consolidate_store(
    store: MemoryStore,
    candidates: list[dict[str, str]],
    request_decision: Callable[[str, list[str]], ConsolidationDecision | str | None],
) -> StoreConsolidationSummary:
    """Consolidate and persist a batch, treating deferred DELETE as unchanged.

    Counts describe candidate outcomes before retention. Any pipeline or request
    failure discards the provisional result and uses upsert_many for the entire
    batch, including its exact-dedupe metadata and timestamp refresh behavior.
    Successful updates retain their positions; overflow retains the newest
    entries by timestamp, as upsert_many does. Existing duplicates are preserved.
    Storage errors propagate to the caller.
    """
    store.load()
    try:
        result = consolidate_candidates(store.items, candidates, request_decision, now=store_module.utc_now_iso)
    except Exception:
        # Exception messages can contain private memory text.
        result = None

    if result is None or result.fallback_count:
        added = store.upsert_many(candidates)
        return StoreConsolidationSummary(added, 0, len(candidates) - added, len(candidates))

    entries = result.entries
    if len(entries) > store.limit:
        entries = sorted(entries, key=lambda item: item.get("updated_at", ""), reverse=True)[: store.limit]
    store.items = entries
    if candidates:
        store.save()
    return StoreConsolidationSummary(
        result.counts["ADD"], result.counts["UPDATE"], result.counts["NOOP"] + result.counts["DELETE"]
    )
