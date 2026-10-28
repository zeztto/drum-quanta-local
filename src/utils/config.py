"""Shared timing parameters. Detection never chooses separate track plans."""

from typing import ClassVar


class Config:
    GRID_DIVISIONS: ClassVar[dict[str, float]] = {
        "1/4": 1.0,
        "1/8": 0.5,
        "1/16": 0.25,
        "1/32": 0.125,
        "1/64": 0.0625,
        "1/4T": 2 / 3,
        "1/8T": 1 / 3,
        "1/16T": 1 / 6,
        "1/32T": 1 / 12,
        "1/4D": 1.5,
        "1/8D": 0.75,
        "1/16D": 0.375,
    }
    QUANTIZE_CROSSFADE_MS = 5.0
    TRANSIENT_DEFAULT_THRESHOLD = 0.3
    TRANSIENT_MIN_DISTANCE_MS = 10
    BPM_DEFAULT, BPM_MIN, BPM_MAX = 120, 40, 300

    @classmethod
    def get_grid_interval(cls, bpm, division):
        if division not in cls.GRID_DIVISIONS:
            raise ValueError("지원하지 않는 그리드입니다.")
        return 60.0 / bpm * cls.GRID_DIVISIONS[division]
