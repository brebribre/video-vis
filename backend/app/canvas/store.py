"""The per-run data canvas (§4.0) — durable state the agent fills and revises.

The canvas, not the transcript, is the source of truth (§9.3). Everything the
agent records lands here, gets derived columns computed on every write, and is
persisted as CSV so a run can be inspected or resumed after the fact.
"""

from __future__ import annotations

import csv
import itertools
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from ..schemas import DEFAULT_COLORS, DataPoint, Series
from . import derive

# Values Python writes into `status`.
STATUS_OK = "ok"
STATUS_CONFLICT = "conflict"
STATUS_UNVERIFIED_URL = "unverified_url"
STATUS_UNPARSEABLE_PERIOD = "unparseable_period"
STATUS_UNKNOWN_UNIT = "unknown_unit"

CSV_COLUMNS = [
    "row_id",
    "series",
    "period_label",
    "raw_value",
    "raw_unit",
    "source_url",
    "source_title",
    "cited_text",
    "published_at",
    "period_iso",
    "value_normalized",
    "status",
]

# Two values for the same (series, period) are "the same number" within this
# relative tolerance — sources round differently and that is not a conflict.
CONFLICT_TOLERANCE = 0.005


def canonical_url(url: str) -> str:
    """Normalise for set membership — fragments and trailing slashes only.

    Deliberately keeps the query string: for many sources it selects the very
    document being cited, so dropping it would let a row cite a different page.
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


@dataclass
class Row:
    row_id: str
    series: str
    period_label: str
    raw_value: float
    raw_unit: str
    source_url: str
    source_title: str = ""
    cited_text: str = ""
    published_at: str = ""
    # Derived (§4.4) — never written by the agent.
    period_iso: str = ""
    value_normalized: float | None = None
    status: str = STATUS_OK

    @property
    def period(self) -> derive.Period | None:
        return derive.parse_period(self.period_label)

    @property
    def published_date(self) -> date | None:
        return derive.parse_published_at(self.published_at)


@dataclass
class RowResult:
    """Per-row outcome handed straight back to the agent as a tool result."""

    accepted: bool
    row_id: str | None = None
    reason: str | None = None
    input: dict[str, Any] = field(default_factory=dict)


class CanvasStore:
    """One run's table. Not thread-safe; one store per run."""

    def __init__(self, run_id: str, root: Path | None = None) -> None:
        self.run_id = run_id
        self.root = root
        self._rows: dict[str, Row] = {}
        self._allowed_urls: set[str] = set()
        self._ids = itertools.count(1)

    # ---- retrieved-URL set (§4.2) ---------------------------------------

    def allow_urls(self, urls: Iterable[str]) -> int:
        """Register URLs that a web_search actually returned.

        Only URLs registered here can be cited. This is what makes "verified
        sources" structural rather than a hope — the agent types `source_url`
        into a tool call and could otherwise invent it.
        """
        before = len(self._allowed_urls)
        for url in urls:
            canonical = canonical_url(url)
            if canonical:
                self._allowed_urls.add(canonical)
        return len(self._allowed_urls) - before

    @property
    def allowed_urls(self) -> set[str]:
        return set(self._allowed_urls)

    # ---- mutations -------------------------------------------------------

    def append_rows(self, rows: Iterable[dict[str, Any]]) -> list[RowResult]:
        results: list[RowResult] = []
        for raw in rows:
            results.append(self._append_one(raw))
        self._recompute()
        return results

    def _append_one(self, raw: dict[str, Any]) -> RowResult:
        missing = [
            key
            for key in ("series", "period_label", "raw_value", "raw_unit", "source_url")
            if raw.get(key) in (None, "")
        ]
        if missing:
            return RowResult(False, reason=f"missing required field(s): {', '.join(missing)}", input=raw)

        try:
            value = float(raw["raw_value"])
        except (TypeError, ValueError):
            return RowResult(False, reason=f"raw_value {raw['raw_value']!r} is not a number", input=raw)

        if raw["raw_unit"] not in derive.UNITS:
            return RowResult(
                False,
                reason=f"unknown raw_unit {raw['raw_unit']!r}; expected one of {sorted(derive.UNITS)}",
                input=raw,
            )

        url = str(raw["source_url"])
        if canonical_url(url) not in self._allowed_urls:
            return RowResult(
                False,
                reason=(
                    f"source_url {url!r} was not returned by any search this run. "
                    "Cite a URL from your search results — do not construct one."
                ),
                input=raw,
            )

        if derive.parse_period(str(raw["period_label"])) is None:
            return RowResult(
                False,
                reason=(
                    f"period_label {raw['period_label']!r} could not be parsed. "
                    "Use the form the source uses, e.g. '2024', 'FY2024', 'Q3 2025', '2024-06'."
                ),
                input=raw,
            )

        row_id = f"r{next(self._ids)}"
        self._rows[row_id] = Row(
            row_id=row_id,
            series=str(raw["series"]).strip(),
            period_label=str(raw["period_label"]).strip(),
            raw_value=value,
            raw_unit=str(raw["raw_unit"]),
            source_url=url,
            source_title=str(raw.get("source_title") or ""),
            cited_text=str(raw.get("cited_text") or ""),
            published_at=str(raw.get("published_at") or ""),
        )
        return RowResult(True, row_id=row_id)

    def revise_row(self, row_id: str, **changes: Any) -> RowResult:
        row = self._rows.get(row_id)
        if row is None:
            return RowResult(False, reason=f"no such row_id {row_id!r}")

        editable = {
            k: v
            for k, v in changes.items()
            if k in {"series", "period_label", "raw_value", "raw_unit",
                     "source_url", "source_title", "cited_text", "published_at"}
            and v is not None
        }
        if "source_url" in editable and canonical_url(str(editable["source_url"])) not in self._allowed_urls:
            return RowResult(False, row_id=row_id, reason="source_url was not returned by any search this run")
        if "raw_unit" in editable and editable["raw_unit"] not in derive.UNITS:
            return RowResult(False, row_id=row_id, reason=f"unknown raw_unit {editable['raw_unit']!r}")
        if "period_label" in editable and derive.parse_period(str(editable["period_label"])) is None:
            return RowResult(False, row_id=row_id, reason="period_label could not be parsed")
        if "raw_value" in editable:
            try:
                editable["raw_value"] = float(editable["raw_value"])
            except (TypeError, ValueError):
                return RowResult(False, row_id=row_id, reason="raw_value is not a number")

        self._rows[row_id] = replace(row, **editable)
        self._recompute()
        return RowResult(True, row_id=row_id)

    def drop_row(self, row_id: str, reason: str) -> RowResult:
        """Remove a row. `reason` is required so drops are never silent (§4.0)."""
        if row_id not in self._rows:
            return RowResult(False, reason=f"no such row_id {row_id!r}")
        if not reason:
            return RowResult(False, row_id=row_id, reason="a reason is required to drop a row")
        del self._rows[row_id]
        self._recompute()
        return RowResult(True, row_id=row_id, reason=reason)

    # ---- derived columns (§4.4) -----------------------------------------

    def _recompute(self) -> None:
        for row in self._rows.values():
            period = row.period
            row.period_iso = period.iso if period else ""
            normalized = derive.normalize_value(row.raw_value, row.raw_unit)
            row.value_normalized = normalized[0] if normalized else None
            if period is None:
                row.status = STATUS_UNPARSEABLE_PERIOD
            elif normalized is None:
                row.status = STATUS_UNKNOWN_UNIT
            elif canonical_url(row.source_url) not in self._allowed_urls:
                row.status = STATUS_UNVERIFIED_URL
            else:
                row.status = STATUS_OK
        self._flag_conflicts()

    def _flag_conflicts(self) -> None:
        """Newest `published_at` wins; superseded rows are flagged, not deleted.

        Keeping the loser visible is the point — §9.2 says surface the
        disagreement rather than silently picking one.
        """
        groups: dict[tuple[str, str], list[Row]] = {}
        for row in self._rows.values():
            if row.status == STATUS_OK and row.period_iso:
                groups.setdefault((row.series, row.period_iso), []).append(row)

        for rows in groups.values():
            if len(rows) < 2:
                continue
            values = [r.value_normalized or 0.0 for r in rows]
            spread = max(values) - min(values)
            scale = max(abs(v) for v in values) or 1.0
            if spread / scale <= CONFLICT_TOLERANCE:
                continue  # rounding, not disagreement
            winner = max(rows, key=lambda r: (r.published_date or date.min, r.row_id))
            for row in rows:
                if row.row_id != winner.row_id:
                    row.status = STATUS_CONFLICT

    # ---- reads -----------------------------------------------------------

    @property
    def rows(self) -> list[Row]:
        return sorted(self._rows.values(), key=lambda r: (r.series, r.period_iso, r.row_id))

    def read(self, series: str | None = None, status: str | None = None) -> dict[str, Any]:
        rows = self.rows
        if series:
            rows = [r for r in rows if r.series == series]
        if status:
            rows = [r for r in rows if r.status == status]
        return {"rows": [asdict(r) for r in rows], "gap_report": self.gap_report()}

    def gap_report(self) -> dict[str, Any]:
        """What the agent works against — this is what makes the loop converge.

        A series is only expected to cover from *its own* first period to the
        overall latest, so a late-starting series is not reported as missing the
        early years (§9.1).
        """
        usable = [r for r in self._rows.values() if r.status in {STATUS_OK, STATUS_CONFLICT}]
        periods = [r.period for r in usable if r.period]
        if not periods:
            return {
                "series": [],
                "range": None,
                "missing": [],
                "conflicts": self._conflicts(),
                "needs_attention": self._needs_attention(),
            }

        granularity = "year" if all(p.granularity == "year" for p in periods) else "month"
        overall_end = max(periods, key=lambda p: p.sort_key)

        by_series: dict[str, list[derive.Period]] = {}
        for row in usable:
            if row.period:
                by_series.setdefault(row.series, []).append(row.period)

        missing: list[dict[str, Any]] = []
        for name, series_periods in sorted(by_series.items()):
            have = {p.iso for p in series_periods}
            start = min(series_periods, key=lambda p: p.sort_key)
            expected = derive.expand_periods(start, overall_end, granularity)
            holes = [p.iso for p in expected if p.iso not in have]
            if holes:
                missing.append({"series": name, "missing_periods": holes})

        return {
            "series": sorted(by_series),
            "range": {
                "start": min(periods, key=lambda p: p.sort_key).iso,
                "end": overall_end.iso,
                "granularity": granularity,
            },
            "missing": missing,
            "conflicts": self._conflicts(),
            "needs_attention": self._needs_attention(),
        }

    def _conflicts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        losers = [r for r in self._rows.values() if r.status == STATUS_CONFLICT]
        for loser in losers:
            winner = next(
                (
                    r
                    for r in self._rows.values()
                    if r.status == STATUS_OK
                    and r.series == loser.series
                    and r.period_iso == loser.period_iso
                ),
                None,
            )
            out.append(
                {
                    "series": loser.series,
                    "period": loser.period_iso,
                    "kept": None
                    if winner is None
                    else {
                        "row_id": winner.row_id,
                        "value": winner.value_normalized,
                        "source_url": winner.source_url,
                        "published_at": winner.published_at,
                    },
                    "superseded": {
                        "row_id": loser.row_id,
                        "value": loser.value_normalized,
                        "source_url": loser.source_url,
                        "published_at": loser.published_at,
                    },
                }
            )
        return out

    def _needs_attention(self) -> list[dict[str, str]]:
        return [
            {"row_id": r.row_id, "status": r.status, "period_label": r.period_label}
            for r in self._rows.values()
            if r.status in {STATUS_UNPARSEABLE_PERIOD, STATUS_UNVERIFIED_URL, STATUS_UNKNOWN_UNIT}
        ]

    # ---- persistence -----------------------------------------------------

    @property
    def path(self) -> Path | None:
        return None if self.root is None else self.root / self.run_id / "canvas.csv"

    def persist(self) -> Path | None:
        path = self.path
        if path is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in self.rows:
                writer.writerow({k: v for k, v in asdict(row).items() if k in CSV_COLUMNS})
        return path

    @classmethod
    def load(cls, run_id: str, root: Path, allowed_urls: Iterable[str] = ()) -> CanvasStore:
        """Reopen a persisted run. Callers must re-supply the allowed-URL set.

        The set is not persisted on purpose: it records what *this* run actually
        retrieved, and silently trusting URLs from an earlier run would weaken
        the §4.2 guard.
        """
        store = cls(run_id, root)
        store.allow_urls(allowed_urls)
        path = store.path
        if path is None or not path.exists():
            return store
        with path.open(newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                row_id = record["row_id"]
                store._rows[row_id] = Row(
                    row_id=row_id,
                    series=record["series"],
                    period_label=record["period_label"],
                    raw_value=float(record["raw_value"]),
                    raw_unit=record["raw_unit"],
                    source_url=record["source_url"],
                    source_title=record.get("source_title", ""),
                    cited_text=record.get("cited_text", ""),
                    published_at=record.get("published_at", ""),
                )
        largest = max((int(rid[1:]) for rid in store._rows if rid[1:].isdigit()), default=0)
        store._ids = itertools.count(largest + 1)
        store._recompute()
        return store

    # ---- finalisation (§4.4 step 4) --------------------------------------

    def finalize(self) -> tuple[list[Series], str, str]:
        """Canvas → `Series[]` for the renderer, plus the axis mode and unit.

        Only `ok` rows are used. Series are ordered by their latest value so the
        leader takes DEFAULT_COLORS[0].
        """
        usable = [r for r in self._rows.values() if r.status == STATUS_OK and r.period]
        if not usable:
            return [], "year", ""

        axis_mode = derive.axis_mode_for([r.period for r in usable if r.period])
        dimension = ""
        by_series: dict[str, list[Row]] = {}
        for row in usable:
            by_series.setdefault(row.series, []).append(row)
            normalized = derive.normalize_value(row.raw_value, row.raw_unit)
            if normalized:
                dimension = normalized[1]

        def latest_value(rows: list[Row]) -> float:
            newest = max(rows, key=lambda r: r.period.sort_key)  # type: ignore[union-attr]
            return newest.value_normalized or 0.0

        ordered = sorted(by_series.items(), key=lambda kv: latest_value(kv[1]), reverse=True)

        series_out: list[Series] = []
        for index, (name, rows) in enumerate(ordered):
            points = [
                DataPoint(
                    time=derive.time_for(row.period, axis_mode),  # type: ignore[arg-type]
                    label=derive.label_for(row.period, axis_mode),  # type: ignore[arg-type]
                    value=row.value_normalized or 0.0,
                )
                for row in sorted(rows, key=lambda r: r.period.sort_key)  # type: ignore[union-attr]
            ]
            series_out.append(
                Series(
                    name=name,
                    color=DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
                    data=points,
                )
            )
        return series_out, axis_mode, dimension
