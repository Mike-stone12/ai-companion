"""Memory benchmark: dataset loading, scoring, and the markdown report.

``cases.jsonl`` holds one user message per line together with the facts a memory system should
keep from it (an empty list means "nothing worth remembering"). Scoring works on summaries: an
expected fact counts as recalled when some extracted summary contains every one of its keys, where
``"a|b"`` inside a key accepts either spelling. Cases that share a ``scenario`` are fed in turn
order through a real ``MemoryStore`` to measure duplicates (paraphrases) and stale facts
(contradictions).

This module is pure Python and never touches the network; ``run_benchmark.py`` drives it.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from companion.core.memory.store import MemoryStore

CASES_PATH = Path(__file__).with_name("cases.jsonl")
GROUPS = ("identity", "preference", "plan", "event", "relation", "chitchat", "paraphrase", "conflict")
LANGS = ("zh", "en")


class DatasetError(ValueError):
    """cases.jsonl is malformed."""


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def pct(numerator: int, denominator: int) -> str:
    return f"{100 * ratio(numerator, denominator):.0f}%" if denominator else "n/a"


# --- dataset -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    text: str
    keys: tuple[str, ...]

    def matches(self, summary: str) -> bool:
        target = normalize(summary)
        return all(any(normalize(option) in target for option in key.split("|")) for key in self.keys)


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    lang: str
    user: str
    assistant: str
    expected: tuple[Fact, ...]
    scenario: str | None = None
    turn: int = 0
    supersedes: bool = False
    note: str = ""

    @property
    def should_remember(self) -> bool:
        return bool(self.expected)


def _parse_fact(raw: object, where: str) -> Fact:
    if not isinstance(raw, dict) or not isinstance(raw.get("fact"), str) or not raw["fact"].strip():
        raise DatasetError(f"{where}: each expected item needs a non-empty 'fact'")
    keys = raw.get("keys")
    if not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key.strip() for key in keys):
        raise DatasetError(f"{where}: fact {raw['fact']!r} needs a non-empty list of string keys")
    return Fact(raw["fact"].strip(), tuple(keys))


def parse_case(raw: object, where: str = "case") -> Case:
    if not isinstance(raw, Mapping):
        raise DatasetError(f"{where}: expected a JSON object")
    for name in ("id", "group", "user"):
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DatasetError(f"{where}: '{name}' must be a non-empty string")
    if raw["group"] not in GROUPS:
        raise DatasetError(f"{where}: unknown group {raw['group']!r}")
    lang = raw.get("lang", "zh")
    if lang not in LANGS:
        raise DatasetError(f"{where}: unknown lang {lang!r}")
    expected_raw = raw.get("expected")
    if not isinstance(expected_raw, list):
        raise DatasetError(f"{where}: 'expected' must be a list (empty when nothing should be remembered)")
    expected = tuple(_parse_fact(item, where) for item in expected_raw)
    scenario = raw.get("scenario")
    turn = raw.get("turn", 0)
    if scenario is not None and (not isinstance(scenario, str) or not isinstance(turn, int) or turn < 1):
        raise DatasetError(f"{where}: a scenario case needs a string 'scenario' and an integer 'turn' >= 1")
    if scenario is None and raw.get("supersedes"):
        raise DatasetError(f"{where}: 'supersedes' only makes sense inside a scenario")
    return Case(
        id=raw["id"].strip(),
        group=raw["group"],
        lang=lang,
        user=raw["user"],
        assistant=str(raw.get("assistant") or ""),
        expected=expected,
        scenario=scenario,
        turn=turn if scenario else 0,
        supersedes=bool(raw.get("supersedes", False)),
        note=str(raw.get("note") or ""),
    )


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        where = f"{path.name}:{line_no}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{where}: invalid JSON ({exc.msg})") from exc
        case = parse_case(raw, where)
        if case.id in seen:
            raise DatasetError(f"{where}: duplicate id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    _check_scenarios(cases)
    return cases


def _check_scenarios(cases: Iterable[Case]) -> None:
    turns: dict[str, list[int]] = defaultdict(list)
    for case in cases:
        if case.scenario:
            turns[case.scenario].append(case.turn)
    for name, seen in turns.items():
        if seen != list(range(1, len(seen) + 1)):
            raise DatasetError(f"scenario {name!r}: turns must be 1..n in file order, got {seen}")


# --- gate ----------------------------------------------------------------------------------


@dataclass
class GateResult:
    """Which messages the rule-based gate lets through to the extractor."""

    decisions: dict[str, bool]
    hits: list[str] = field(default_factory=list)  # should remember, passed
    misses: list[str] = field(default_factory=list)  # should remember, rejected: the fact is lost
    false_alarms: list[str] = field(default_factory=list)  # nothing to remember, passed: a wasted request
    correct_rejects: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return ratio(len(self.hits), len(self.hits) + len(self.misses))

    @property
    def precision(self) -> float:
        return ratio(len(self.hits), len(self.hits) + len(self.false_alarms))


def evaluate_gate(cases: Iterable[Case], gate: Callable[[str], bool]) -> GateResult:
    result = GateResult(decisions={})
    for case in cases:
        passed = bool(gate(case.user))
        result.decisions[case.id] = passed
        if case.should_remember:
            (result.hits if passed else result.misses).append(case.id)
        else:
            (result.false_alarms if passed else result.correct_rejects).append(case.id)
    return result


# --- extraction ----------------------------------------------------------------------------


@dataclass
class Tally:
    expected: int = 0  # facts the dataset wants
    recalled: int = 0  # of those, found in some summary
    extracted: int = 0  # summaries produced
    correct: int = 0  # of those, matching at least one expected fact
    cases: int = 0

    def add(self, other: Tally) -> None:
        self.expected += other.expected
        self.recalled += other.recalled
        self.extracted += other.extracted
        self.correct += other.correct
        self.cases += other.cases

    @property
    def noise(self) -> int:
        return self.extracted - self.correct

    @property
    def recall(self) -> float:
        return ratio(self.recalled, self.expected)

    @property
    def precision(self) -> float:
        return ratio(self.correct, self.extracted)

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


@dataclass
class CaseScore:
    case: Case
    summaries: list[str]
    recalled: tuple[Fact, ...]
    missed: tuple[Fact, ...]
    correct_items: int
    noise_items: int

    @property
    def tally(self) -> Tally:
        return Tally(
            expected=len(self.case.expected),
            recalled=len(self.recalled),
            extracted=len(self.summaries),
            correct=self.correct_items,
            cases=1,
        )


@dataclass
class ExtractionScore:
    cases: list[CaseScore]

    @property
    def total(self) -> Tally:
        return self.by(lambda case: "all")["all"]

    @property
    def chitchat_noise(self) -> int:
        """Summaries produced for messages that hold nothing worth remembering."""
        return sum(score.noise_items for score in self.cases if not score.case.should_remember)

    def by(self, key: Callable[[Case], str]) -> dict[str, Tally]:
        tallies: dict[str, Tally] = defaultdict(Tally)
        for score in self.cases:
            tallies[key(score.case)].add(score.tally)
        return dict(tallies)


def score_case(case: Case, summaries: Iterable[str]) -> CaseScore:
    summaries = [summary for summary in summaries if summary and summary.strip()]
    recalled = tuple(fact for fact in case.expected if any(fact.matches(summary) for summary in summaries))
    missed = tuple(fact for fact in case.expected if fact not in recalled)
    correct_items = sum(1 for summary in summaries if any(fact.matches(summary) for fact in case.expected))
    return CaseScore(case, summaries, recalled, missed, correct_items, len(summaries) - correct_items)


def score_extraction(cases: Iterable[Case], extracted: Mapping[str, Iterable[str]]) -> ExtractionScore:
    """Score summaries per case; cases missing from ``extracted`` count as producing nothing."""
    return ExtractionScore([score_case(case, extracted.get(case.id, ())) for case in cases])


# --- store simulation (dedup / update) ------------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    group: str
    stored: list[str]
    duplicates: list[str]  # entries whose facts are all carried by another stored entry
    stale: list[str]  # entries that only carry a fact a later turn replaced
    missing: list[Fact]  # current facts that no stored entry carries
    current: int


@dataclass
class StoreResult:
    scenarios: list[ScenarioResult]

    @property
    def stored_total(self) -> int:
        return sum(len(scenario.stored) for scenario in self.scenarios)

    @property
    def duplicate_total(self) -> int:
        return sum(len(scenario.duplicates) for scenario in self.scenarios)

    @property
    def stale_total(self) -> int:
        return sum(len(scenario.stale) for scenario in self.scenarios)

    @property
    def missing_total(self) -> int:
        return sum(len(scenario.missing) for scenario in self.scenarios)

    @property
    def current_total(self) -> int:
        return sum(scenario.current for scenario in self.scenarios)

    @property
    def duplicate_rate(self) -> float:
        return ratio(self.duplicate_total, self.stored_total)

    @property
    def stale_rate(self) -> float:
        return ratio(self.stale_total, self.stored_total)


def judge_scenario(
    name: str, group: str, stored: list[str], current: Iterable[Fact], superseded: Iterable[Fact]
) -> ScenarioResult:
    current = list(dict.fromkeys(current))
    superseded = [fact for fact in dict.fromkeys(superseded) if fact not in current]
    carried = [[fact for fact in current if fact.matches(summary)] for summary in stored]
    # Entries carrying more facts are credited first, so the count does not depend on store order.
    order = sorted(range(len(stored)), key=lambda index: (-len(carried[index]), index))
    covered: set[Fact] = set()
    duplicates: list[str] = []
    stale: list[str] = []
    for index in order:
        facts = carried[index]
        if facts:
            if all(fact in covered for fact in facts):
                duplicates.append(stored[index])
            covered.update(facts)
        elif any(fact.matches(stored[index]) for fact in superseded):
            stale.append(stored[index])
    missing = [fact for fact in current if fact not in covered]
    return ScenarioResult(name, group, stored, duplicates, stale, missing, len(current))


def simulate_store(cases: Iterable[Case], extracted: Mapping[str, Iterable[str]]) -> StoreResult:
    """Feed each scenario's summaries through a fresh MemoryStore and judge what it ends up holding.

    A turn marked ``supersedes`` replaces the facts of every earlier turn in its scenario.
    """
    scenarios: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        if case.scenario:
            scenarios[case.scenario].append(case)

    results: list[ScenarioResult] = []
    for name, turns in scenarios.items():
        turns = sorted(turns, key=lambda case: case.turn)
        last_supersede = max((case.turn for case in turns if case.supersedes), default=0)
        current = [fact for case in turns if case.turn >= last_supersede for fact in case.expected]
        superseded = [fact for case in turns if case.turn < last_supersede for fact in case.expected]
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.json")
            for case in turns:
                summaries = extracted.get(case.id, ())
                store.upsert_many([{"summary": text, "category": "memory", "source": "eval"} for text in summaries])
            stored = [item["summary"] for item in store.items]
        results.append(judge_scenario(name, turns[0].group, stored, current, superseded))
    return StoreResult(results)


# --- results files --------------------------------------------------------------------------


def write_results(path: Path, meta: Mapping[str, object], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"meta": dict(meta)}, ensure_ascii=False) + "\n")
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


def load_results(path: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return the run metadata and the per-case rows keyed by case id."""
    meta: dict[str, object] = {}
    rows: dict[str, dict[str, object]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "meta" in row and "id" not in row:
            meta = dict(row["meta"])
        else:
            rows[str(row["id"])] = row
    return meta, rows


def summaries_from_rows(rows: Mapping[str, Mapping[str, object]]) -> dict[str, list[str]]:
    summaries: dict[str, list[str]] = {}
    for case_id, row in rows.items():
        memories = row.get("memories") or []
        summaries[case_id] = [str(item.get("summary", "")) for item in memories if isinstance(item, Mapping)]
    return summaries


# --- report ---------------------------------------------------------------------------------


def _ids(ids: Iterable[str]) -> str:
    ids = list(ids)
    return f"{len(ids)}: " + ", ".join(f"`{case_id}`" for case_id in ids) if ids else "0"


def _tally_table(tallies: Mapping[str, Tally], label: str) -> list[str]:
    lines = [
        f"| {label} | Cases | Expected facts | Recalled | Recall | Extracted | Correct | Precision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, tally in tallies.items():
        lines.append(
            f"| {name} | {tally.cases} | {tally.expected} | {tally.recalled} | {pct(tally.recalled, tally.expected)} "
            f"| {tally.extracted} | {tally.correct} | {pct(tally.correct, tally.extracted)} |"
        )
    return lines


def render_gate_section(cases: list[Case], gate: GateResult) -> list[str]:
    should = [case for case in cases if case.should_remember]
    passed_with_facts = len(gate.hits) + len(gate.false_alarms)
    lines = [
        "## Gate (rule-based, no API calls)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases | {len(cases)} ({len(should)} with something to remember) |",
        f"| Passed to the extractor | {sum(gate.decisions.values())} |",
        f"| Gate recall (messages with facts that reach the extractor) | {len(gate.hits)}/{len(should)} "
        f"({pct(len(gate.hits), len(should))}) |",
        f"| Gate precision (passed messages that hold a fact) | {len(gate.hits)}/{passed_with_facts} "
        f"({pct(len(gate.hits), passed_with_facts)}) |",
        f"| Missed (facts lost before extraction) | {_ids(gate.misses)} |",
        f"| False alarms (chit-chat that costs a request) | {_ids(gate.false_alarms)} |",
        "",
        "| Group | Cases | With facts | Passed | Missed | False alarms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    by_group: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        by_group[case.group].append(case)
    misses, alarms = set(gate.misses), set(gate.false_alarms)
    for group, members in by_group.items():
        lines.append(
            f"| {group} | {len(members)} | {sum(1 for c in members if c.should_remember)} "
            f"| {sum(1 for c in members if gate.decisions[c.id])} | {sum(1 for c in members if c.id in misses)} "
            f"| {sum(1 for c in members if c.id in alarms)} |"
        )
    by_lang: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        by_lang[case.lang].append(case)
    for lang, members in by_lang.items():
        lines.append(
            f"| lang={lang} | {len(members)} | {sum(1 for c in members if c.should_remember)} "
            f"| {sum(1 for c in members if gate.decisions[c.id])} | {sum(1 for c in members if c.id in misses)} "
            f"| {sum(1 for c in members if c.id in alarms)} |"
        )
    return lines


def render_extraction_section(title: str, score: ExtractionScore, show_failures: bool = True) -> list[str]:
    total = score.total
    lines = [
        f"## {title}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Precision (extracted summaries that match an expected fact) | {total.correct}/{total.extracted} "
        f"({pct(total.correct, total.extracted)}) |",
        f"| Recall (expected facts found in some summary) | {total.recalled}/{total.expected} "
        f"({pct(total.recalled, total.expected)}) |",
        f"| F1 | {total.f1:.2f} |",
        f"| Noise on chit-chat (summaries for messages with nothing to remember) | {score.chitchat_noise} |",
        "",
        *_tally_table(score.by(lambda case: case.group), "Group"),
        *_tally_table(score.by(lambda case: "lang=" + case.lang), "Language")[2:],
    ]
    if show_failures:
        failures = [s for s in score.cases if s.missed or s.noise_items]
        lines += ["", "| Case | Message | Missed facts | Extracted summaries |", "| --- | --- | --- | --- |"]
        for item in failures:
            missed = "; ".join(fact.text for fact in item.missed) or "-"
            got = "; ".join(item.summaries) or "(nothing)"
            lines.append(f"| `{item.case.id}` | {item.case.user} | {missed} | {got} |")
        if not failures:
            lines.append("| - | every case was extracted exactly as expected | - | - |")
    return lines


def render_store_section(store: StoreResult, title: str = "Store after scenario turns (pipeline)") -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| Scenario | Group | Stored | Duplicates | Stale | Missing | Entries |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for scenario in store.scenarios:
        entries = "; ".join(scenario.stored) or "(empty)"
        lines.append(
            f"| {scenario.name} | {scenario.group} | {len(scenario.stored)} | {len(scenario.duplicates)} "
            f"| {len(scenario.stale)} | {len(scenario.missing)}/{scenario.current} | {entries} |"
        )
    lines += [
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Stored entries | {store.stored_total} |",
        "| Duplicate rate (entries that repeat a fact already stored) "
        f"| {store.duplicate_total}/{store.stored_total} ({pct(store.duplicate_total, store.stored_total)}) |",
        f"| Stale rate (entries a later message contradicted) | {store.stale_total}/{store.stored_total} "
        f"({pct(store.stale_total, store.stored_total)}) |",
        f"| Current facts missing from the store | {store.missing_total}/{store.current_total} |",
    ]
    return lines


def render_report(
    cases: list[Case],
    gate: GateResult,
    pipeline: ExtractionScore,
    extractor_only: ExtractionScore | None,
    store: StoreResult,
    meta: Mapping[str, object],
    store_extractor_only: StoreResult | None = None,
) -> str:
    extractor = meta.get("extractor", "?")
    lines = [
        f"# Memory benchmark: {extractor}",
        "",
        "| Run | |",
        "| --- | --- |",
        *(f"| {key} | {value} |" for key, value in meta.items()),
        "",
        *render_gate_section(cases, gate),
        "",
        *render_extraction_section(f"Pipeline (gate + {extractor} extractor, what the app stores)", pipeline),
    ]
    if extractor_only is not None:
        lines += [
            "",
            *render_extraction_section(
                f"Extractor alone ({extractor} on every message, gate ignored)", extractor_only, show_failures=False
            ),
        ]
    lines += ["", *render_store_section(store)]
    if store_extractor_only is not None:
        lines += ["", *render_store_section(store_extractor_only, "Store after scenario turns (extractor alone)")]
    return "\n".join(lines) + "\n"
