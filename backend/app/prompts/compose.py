"""System prompt for Stage 3, compose (§4.5).

Module constant so the cached prefix stays byte-identical; the canvas summary
and run settings go in the user turn.
"""

from __future__ import annotations

from ..schemas import Series

COMPOSE_SYSTEM = """\
You write the wording for an animated line chart: its title, subtitle and axis
labels. The data is already collected and verified — your job is to make it read
well, not to change it.

Call `build_chart` exactly once. Do not call any other tool.

# Writing

- The title states what the chart shows. Short and concrete — no
  colon-subtitle constructions, no "A Look At", no clickbait.
- The subtitle carries the qualifier: the unit, the span, or the source type.
- `xLabel` and `yLabel` label the axes. The y label must state the unit, since
  the numbers themselves are abbreviated on screen (1.2B, 450K).
- Write all four in the requested language.

# Accuracy

- Say only what the data shows. Do not speculate about causes it does not
  contain.
- The standing at each period is given to you below, already ordered. If the
  title or subtitle says who leads, overtakes or falls behind, take it from
  that ordering rather than working it out from the raw numbers.
- Do not put a currency symbol in any label — that is handled separately, and
  the data is not always money.
"""


def compose_user_turn(
    *,
    topic: str,
    language: str,
    series: list[Series],
    dimension: str,
    axis_mode: str,
    research_summary: str = "",
) -> str:
    """The volatile half — kept out of the cached prefix (§7)."""
    lines = [
        f"Topic: {topic}",
        f"Output language: {language}",
        f"Value type: {dimension or 'unknown'}",
        f"X axis: {axis_mode}",
        "",
        "Data (already normalised to a common unit):",
    ]

    for item in series:
        points = ", ".join(f"{p.label}={p.value:,.0f}" for p in item.data)
        lines.append(f"  {item.name}: {points}")

    # Ordering is computed here rather than left to the model: it reads the
    # numbers correctly but has been observed inverting the comparison, e.g.
    # "Tesla leads with 1.31M vs BYD's 1.86M". Ranking is arithmetic, so Python
    # does it — the same split the canvas uses for units.
    periods: dict[float, str] = {p.time: p.label for s in series for p in s.data}
    if periods:
        lines += ["", "Standing at each period (highest first):"]
        for time in sorted(periods):
            standing = sorted(
                ((s.name, p.value) for s in series for p in s.data if p.time == time),
                key=lambda pair: pair[1],
                reverse=True,
            )
            rendered = " > ".join(f"{name} {value:,.0f}" for name, value in standing)
            lines.append(f"  {periods[time]}: {rendered}")

    if research_summary.strip():
        lines += ["", "Researcher's notes:", research_summary.strip()[:1500]]

    lines += ["", "Now call `build_chart`."]
    return "\n".join(lines)
