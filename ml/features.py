"""Feature helpers shared by the simulator and the dataset builders.

Kept free of file I/O so Phase 5/6 can reuse them on data read from PostgreSQL.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd

from . import config as C

_HOLIDAYS = set(C.HOLIDAYS_MD)


def is_holiday(d: date) -> bool:
    return (d.month, d.day) in _HOLIDAYS


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and not is_holiday(d)


def add_calendar_columns(df: pd.DataFrame, ts_col: str, prefix: str = "") -> pd.DataFrame:
    """Add day-of-week / month / working-day / holiday / academic-phase columns for ts_col."""
    ts = pd.to_datetime(df[ts_col])
    dates = ts.dt.date
    df[f"{prefix}dow"] = ts.dt.dayofweek
    df[f"{prefix}month"] = ts.dt.month
    df[f"{prefix}is_holiday"] = dates.map(is_holiday).astype(int)
    df[f"{prefix}is_working_day"] = dates.map(is_working_day).astype(int)
    df[f"{prefix}academic_phase"] = ts.dt.month.map(C.ACADEMIC_PHASE_BY_MONTH)
    return df


def to_epoch_seconds(ts) -> np.ndarray:
    """datetime-like -> float seconds since epoch (unit-safe across pandas versions)."""
    idx = pd.DatetimeIndex(ts)
    # Delta-from-epoch in seconds: unit-safe across pandas versions and NaT -> NaN (not a huge negative int).
    return ((idx - pd.Timestamp("1970-01-01")) / pd.Timedelta(seconds=1)).to_numpy(dtype="float64")


class HistoryTracker:
    """Per-student application history, fed strictly in time order.

    prior_apps(sid, t)            = applications the student submitted before t
    prior_reviews_lagged(sid, t)  = of those, how many were flagged for manual review AND were
                                    submitted at least `lag_days` before t (so their outcome would
                                    normally be known by t; this also avoids the circularity of
                                    "outcome of an application that is still in the queue").
    """

    def __init__(self, lag_days: float = 14.0):
        self.lag = lag_days * 86400.0
        self._times: dict = defaultdict(list)
        self._cum_reviews: dict = defaultdict(list)

    def prior_apps(self, sid, t: float) -> int:
        return bisect_left(self._times[sid], t)

    def prior_reviews_lagged(self, sid, t: float) -> int:
        times = self._times[sid]
        i = bisect_right(times, t - self.lag)
        return self._cum_reviews[sid][i - 1] if i else 0

    def add(self, sid, t: float, reviewed: int) -> None:
        cum = self._cum_reviews[sid]
        cum.append((cum[-1] if cum else 0) + int(reviewed))
        self._times[sid].append(t)


def history_features(student_id, submitted_at, reviewed) -> tuple[np.ndarray, np.ndarray]:
    """Batch version: (prior_apps, prior_reviews_lagged) for rows ALREADY sorted by time."""
    tracker = HistoryTracker()
    t = to_epoch_seconds(submitted_at)
    n = len(t)
    prior_apps = np.zeros(n, dtype=int)
    prior_rev = np.zeros(n, dtype=int)
    for i in range(n):
        sid = student_id[i]
        prior_apps[i] = tracker.prior_apps(sid, t[i])
        prior_rev[i] = tracker.prior_reviews_lagged(sid, t[i])
        tracker.add(sid, t[i], reviewed[i])
    return prior_apps, prior_rev


def split_for(ts, train_end: date, valid_end: date) -> pd.Series:
    """Chronological split label by timestamp: train <= train_end < valid <= valid_end < test."""
    d = pd.to_datetime(ts).dt.date
    return pd.Series(
        np.where(d <= train_end, "train", np.where(d <= valid_end, "valid", "test")), index=ts.index
    )
