"""Caption sanitisation (§4.5).

The model proposes `appearAt` / `duration`; this decides what the renderer
actually gets. Model timestamps are never trusted straight through — a caption
that starts after the animation ends is invisible, and two that overlap render
on top of each other.

Pure functions, so the rules are testable without an API call.
"""

from __future__ import annotations

from ..schemas import Caption

# Below this a caption flashes past unread.
MIN_DURATION = 1.0
# More than this and they collide no matter how they are spaced.
MAX_CAPTIONS = 6
# Gap enforced between one caption ending and the next starting.
MIN_GAP = 0.2


def sanitize_captions(
    raw: list[dict[str, object]] | None,
    *,
    animation_duration: float,
    max_captions: int = MAX_CAPTIONS,
) -> tuple[list[Caption], list[str]]:
    """Return renderer-safe captions plus a note of what was changed and why.

    The notes exist so a surprising result is explainable after the fact rather
    than looking like the model simply ignored the brief.
    """
    notes: list[str] = []
    if not raw:
        return [], notes

    candidates: list[Caption] = []
    for entry in raw:
        text = str(entry.get("text") or "").strip()
        if not text:
            notes.append("dropped a caption with no text")
            continue

        try:
            appear_at = float(entry.get("appearAt", entry.get("appear_at", 0)) or 0)
            duration = float(entry.get("duration", 0) or 0)
        except (TypeError, ValueError):
            notes.append(f"dropped {text[:40]!r}: appearAt/duration were not numbers")
            continue

        if appear_at < 0:
            notes.append(f"{text[:40]!r}: appearAt {appear_at:.1f}s clamped to 0")
            appear_at = 0.0

        # A caption starting at or after the end is never seen at all.
        if appear_at >= animation_duration:
            notes.append(
                f"dropped {text[:40]!r}: appearAt {appear_at:.1f}s is at or past "
                f"the {animation_duration:.1f}s end"
            )
            continue

        if duration < MIN_DURATION:
            notes.append(f"{text[:40]!r}: duration raised to {MIN_DURATION:.1f}s")
            duration = MIN_DURATION

        # Trim rather than drop when it merely runs past the end.
        if appear_at + duration > animation_duration:
            duration = animation_duration - appear_at
            notes.append(f"{text[:40]!r}: duration trimmed to fit the animation")

        if duration < MIN_DURATION:
            notes.append(f"dropped {text[:40]!r}: no room left before the end")
            continue

        candidates.append(Caption(text=text, appear_at=appear_at, duration=duration))

    candidates.sort(key=lambda c: c.appear_at)

    kept: list[Caption] = []
    for caption in candidates:
        if len(kept) >= max_captions:
            notes.append(f"dropped {caption.text[:40]!r}: over the {max_captions}-caption cap")
            continue
        if kept:
            previous = kept[-1]
            if caption.appear_at < previous.appear_at + previous.duration + MIN_GAP:
                notes.append(
                    f"dropped {caption.text[:40]!r}: overlaps "
                    f"{previous.text[:40]!r}"
                )
                continue
        kept.append(caption)

    return kept, notes
