from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

RiskLevel = str

RISK_LEVELS: tuple[RiskLevel, ...] = ("low", "medium_low", "medium", "medium_high", "high")

RISK_POINTS: dict[RiskLevel, int] = {
    "low": 1,
    "medium_low": 2,
    "medium": 4,
    "medium_high": 6,
    "high": 8,
}


def _stable_int(key: str) -> int:
    # Stable across runs (unlike Python's built-in hash()).
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def risk_points(level: RiskLevel) -> int:
    if level not in RISK_POINTS:
        raise KeyError(f"Unknown risk level: {level!r}")
    return int(RISK_POINTS[level])


def generate_case_risk(
    application_ids: Iterable[str],
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Deterministic mock risk table keyed by application_id.
    Intended to be replaced by an external system later.
    """
    rows: list[dict[str, str]] = []
    for app_id in application_ids:
        base = _stable_int(f"{seed}|{app_id}")
        init = RISK_LEVELS[base % len(RISK_LEVELS)]
        end = RISK_LEVELS[(base // 7) % len(RISK_LEVELS)]
        rows.append(
            {
                "application_id": str(app_id),
                "initial_risk": init,
                "end_risk": end,
            }
        )
    return pd.DataFrame(rows)


def generate_staffing_calendar(
    *,
    actors: Iterable[str],
    team: str,
    start_day: str,
    end_day: str,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Deterministic mock staffing calendar.
    Each (actor,day) gets an availability_pct with mean ~85% on weekdays.
    Weekends default to 0% (no staffing) for a more realistic ops calendar demo.
    Distribution (deterministic by seed):
      - 0%: 5%
      - 50%: 20%
      - 100%: 75%
    Expected value: 0*0.05 + 50*0.20 + 100*0.75 = 85.
    """
    days = pd.date_range(start=pd.Timestamp(start_day), end=pd.Timestamp(end_day), freq="D")

    rows: list[dict[str, object]] = []
    for actor in sorted(set(str(a) for a in actors if str(a).strip())):
        for d in days:
            if d.weekday() >= 5:  # Sat/Sun
                pct = 0
                rows.append(
                    {
                        "team": team,
                        "actor": actor,
                        "day": d.date().isoformat(),
                        "availability_pct": int(pct),
                    }
                )
                continue
            k = _stable_int(f"{seed}|{team}|{actor}|{d.date().isoformat()}")
            bucket = k % 100
            if bucket < 5:
                pct = 0
            elif bucket < 25:
                pct = 50
            else:
                pct = 100
            rows.append(
                {
                    "team": team,
                    "actor": actor,
                    "day": d.date().isoformat(),
                    "availability_pct": int(pct),
                }
            )
    return pd.DataFrame(rows)


def wednesday_working_headcounts(staffing: pd.DataFrame) -> pd.DataFrame:
    """
    One row per calendar Wednesday in ``staffing`` with count of distinct actors
    that have availability_pct > 0 that day.

    Expected columns: ``actor``, ``day``, ``availability_pct`` (long calendar like
    ``generate_staffing_calendar`` output).
    """
    if staffing is None or staffing.empty:
        return pd.DataFrame(columns=["wednesday", "n_employees"])
    need = {"actor", "day", "availability_pct"}
    if not need.issubset(staffing.columns):
        raise ValueError(f"staffing missing columns {sorted(need - set(staffing.columns))}")
    w = staffing.copy()
    w["d"] = pd.to_datetime(w["day"], errors="coerce")
    w = w.dropna(subset=["d"])
    w = w[w["d"].dt.weekday == 2]
    pct = pd.to_numeric(w["availability_pct"], errors="coerce").fillna(0)
    w = w.loc[pct > 0]
    if w.empty:
        return pd.DataFrame(columns=["wednesday", "n_employees"])
    w["wednesday"] = w["d"].dt.normalize()
    return (
        w.groupby("wednesday", as_index=False)
        .agg(n_employees=("actor", "nunique"))
        .sort_values("wednesday")
        .reset_index(drop=True)
    )


def generate_team_roster(team: str, *, n_people: int = 8, domain: str = "relio.ch") -> list[str]:
    t = str(team).strip().lower()
    if t == "cr":
        prefix = "cr"
    elif t == "compliance":
        prefix = "compliance"
    else:
        prefix = t or "team"
    return [f"{prefix}{i:02d}@{domain}" for i in range(1, int(n_people) + 1)]


def bucket_actor_to_roster(actor: str, *, team: str, roster: list[str], seed: int = 42) -> str:
    """
    Deterministically map any actor string onto the fixed roster, so synthetic audit logs
    with many distinct actors still roll up to 8 staff members.
    """
    if not roster:
        return str(actor)
    k = _stable_int(f"{seed}|{team}|{actor}")
    return roster[int(k) % len(roster)]


@dataclass(frozen=True)
class ProductivityConfig:
    # Score per transition = 1 + risk_points
    base_points_per_transition: int = 1


def score_transitions(
    transitions: pd.DataFrame,
    case_risk: pd.DataFrame,
    staffing_calendar: pd.DataFrame,
    *,
    config: ProductivityConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute per-actor productivity metrics.

    transitions columns required:
      - application_id, team, actor, transition_at (date or timestamp), from_stage, to_stage

    case_risk columns required:
      - application_id, initial_risk, end_risk

    staffing_calendar columns required:
      - team, actor, day (YYYY-MM-DD), availability_pct
    """
    cfg = config or ProductivityConfig()
    required = {"application_id", "team", "actor", "from_stage", "to_stage", "transition_at"}
    missing = required - set(transitions.columns)
    if missing:
        raise ValueError(f"transitions missing columns: {sorted(missing)}")

    work = transitions.copy()
    work["application_id"] = work["application_id"].astype(str)
    work["team"] = work["team"].astype(str)
    work["actor"] = work["actor"].astype(str)

    risk = case_risk.copy()
    risk["application_id"] = risk["application_id"].astype(str)

    work = work.merge(risk, on="application_id", how="left")
    # Choose risk by team.
    work["risk_level"] = work.apply(
        lambda r: r["initial_risk"] if r["team"] == "CR" else r["end_risk"],
        axis=1,
    )
    work["risk_level"] = work["risk_level"].fillna("low")
    work["risk_points"] = work["risk_level"].map(RISK_POINTS).fillna(1).astype(int)
    work["points"] = int(cfg.base_points_per_transition) + work["risk_points"]

    # Effective days from staffing calendar (sum availability_pct/100).
    cal = staffing_calendar.copy()
    cal["actor"] = cal["actor"].astype(str)
    cal["team"] = cal["team"].astype(str)
    eff = (
        cal.groupby(["team", "actor"], as_index=False)["availability_pct"]
        .sum()
        .rename(columns={"availability_pct": "availability_pct_sum"})
    )
    eff["effective_days"] = eff["availability_pct_sum"].astype(float) / 100.0

    per_actor = (
        work.groupby(["team", "actor"], as_index=False)
        .agg(
            n_transitions=("application_id", "size"),
            n_cases=("application_id", pd.Series.nunique),
            points_total=("points", "sum"),
        )
        .merge(eff[["team", "actor", "effective_days"]], on=["team", "actor"], how="left")
    )
    per_actor["effective_days"] = per_actor["effective_days"].fillna(0.0)
    per_actor["points_per_transition"] = per_actor["points_total"] / per_actor["n_transitions"].clip(lower=1)
    per_actor["points_per_case"] = per_actor["points_total"] / per_actor["n_cases"].clip(lower=1)
    per_actor["points_per_effective_day"] = per_actor["points_total"] / per_actor["effective_days"].replace(0.0, pd.NA)
    per_actor["transitions_per_effective_day"] = per_actor["n_transitions"] / per_actor["effective_days"].replace(0.0, pd.NA)

    return per_actor, work

