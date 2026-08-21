"""System prompt for Stage 3, compose (§4.5).

Module constant so the cached prefix stays byte-identical; the canvas summary
and run settings go in the user turn.
"""

from __future__ import annotations

from ..schemas import Series

COMPOSE_SYSTEM = """\
You write the presentation layer for an animated line chart: its title,
subtitle, axis labels and on-screen captions. The data is already collected and
verified — your job is to make it read well, not to change it.

Call `build_chart` exactly once. Do not call any other tool.

# Writing

- The title states what the chart shows. Short and concrete — no colon-subtitle
  constructions, no "A Look At", no clickbait.
- The subtitle carries the qualifier: the unit, the span, or the source type.
- `xLabel` and `yLabel` label the axes. The y label must state the unit, since
  the numbers themselves are abbreviated on screen (1.2B, 450K).
- Write every one of these in the requested language, including captions.

# Units and currency

- `currency` is the symbol shown against values, e.g. "$" or "Rp". Set it to an
  empty string when the data is not money — vehicle counts, user counts,
  percentages. A "$" against a delivery count is simply wrong.
- `currencyPosition` is "prefix" for $1.2B, "suffix" for 1,2 Mio. €.

# Captions

Captions appear over the animation as it plays, so they must be tied to what is
on screen at that moment.

- Anchor each one to something the data actually shows at that time: a
  crossover, a step change, a series appearing, the final standing.
- The standing at each period is given to you below, already ordered. Use it
  rather than working out who leads from the raw numbers — say "leads",
  "overtakes" or "falls behind" only when that ordering says so.
- State what the numbers show. Do not speculate about causes the data does not
  contain.
- Keep them to one short line — they are read while the chart is moving.
- Space them across the animation. Do not stack several at the same moment;
  overlapping captions are discarded.
- Zero captions is a valid answer if nothing in the data warrants one. Two to
  four is typical.

You are told the animation length and the exact time range. `appearAt` is
seconds from the start of the animation, not a year, and must be inside the
animation. `duration` is how long it stays on screen.
"""


def compose_user_turn(
    *,
    topic: str,
    language: str,
    series: list[Series],
    animation_duration: float,
    dimension: str,
    axis_mode: str,
    research_summary: str = "",
) -> str:
    """The volatile half — kept out of the cached prefix (§7)."""
    lines = [
        f"Topic: {topic}",
        f"Output language: {language}",
        f"Animation length: {animation_duration:g} seconds",
        f"Value type: {dimension or 'unknown'}",
        f"X axis: {axis_mode}",
        "",
        "Data (already normalised to a common unit):",
    ]

    for item in series:
        points = ", ".join(f"{p.label}={p.value:,.0f}" for p in item.data)
        lines.append(f"  {item.name}: {points}")

    # Anchoring captions needs the mapping from period to animation time, not
    # just the periods — appearAt is seconds, and the model cannot derive the
    # mapping from the period labels alone.
    all_points = [p for s in series for p in s.data]
    if all_points:
        first = min(p.time for p in all_points)
        last = max(p.time for p in all_points)
        labels = {p.time: p.label for s in series for p in s.data}
        lines += ["", "Where each period falls in the animation:"]
        for time in sorted(labels):
            fraction = 0.0 if last == first else (time - first) / (last - first)
            lines.append(f"  {labels[time]} -> {fraction * animation_duration:.1f}s")

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
