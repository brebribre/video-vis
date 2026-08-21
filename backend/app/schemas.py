"""Pydantic mirrors of `frontend/src/types.ts`.

These are wire-format DTOs: fields are snake_case in Python but serialise to the
camelCase the renderer expects. Always dump with `by_alias=True`.

Keep in lockstep with types.ts — the renderer consumes this shape directly and
`DataPoint` deliberately has no source field (§9.2); provenance travels
separately over the `sources` SSE event.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

AspectRatio = Literal["9:16", "4:5"]
XAxisMode = Literal["text", "date-ddmmyy", "date-mmyy", "year", "datetime-hhmm-ddmmyy"]
IconSize = Literal["small", "medium", "large"]
ChartFont = Literal["modern", "royal"]
CurrencyPosition = Literal["prefix", "suffix"]

# Must match DEFAULT_COLORS in types.ts, in order.
DEFAULT_COLORS = [
    "#4f8ff7",
    "#f74f4f",
    "#4ff78f",
    "#f7c94f",
    "#c74ff7",
    "#4ff7f7",
    "#f77b4f",
    "#7b4ff7",
]

# NUMBER_SUFFIX_PRESETS in types.ts. The language chosen for a run selects one
# of these so an Indonesian chart reads "1,2Jt" and not "1.2M" (§4.5).
NUMBER_SUFFIX_PRESETS: dict[str, dict[str, str]] = {
    "English": {"thousands": "K", "millions": "M", "billions": "B"},
    "Indonesian": {"thousands": "Rb", "millions": "Jt", "billions": "M"},
    "Japanese": {"thousands": "K", "millions": "百万", "billions": "十億"},
}


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DataPoint(Wire):
    time: float
    label: str
    value: float


class Series(Wire):
    name: str
    color: str
    data: list[DataPoint]
    image: str | None = None


class NumberSuffixes(Wire):
    thousands: str = "K"
    millions: str = "M"
    billions: str = "B"


class Caption(Wire):
    text: str
    appear_at: float
    duration: float


class ChartConfig(Wire):
    series: list[Series]
    aspect_ratio: AspectRatio = "9:16"
    x_axis_mode: XAxisMode = "year"
    title: str = ""
    subtitle: str = ""
    x_label: str = ""
    y_label: str = ""
    currency: str = "$"
    currency_position: CurrencyPosition = "prefix"
    allow_negative: bool = False
    icon_size: IconSize = "medium"
    chart_font: ChartFont = "modern"
    show_end_ranking: bool = True
    animation_duration: float = 8
    text_size: float = 0.7
    number_suffixes: NumberSuffixes = NumberSuffixes()
    captions: list[Caption] = []
