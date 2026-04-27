from __future__ import annotations

import pandas as pd

from analytics.team_productivity import (
    RISK_POINTS,
    generate_case_risk,
    generate_staffing_calendar,
    score_transitions,
    wednesday_working_headcounts,
)


def test_wednesday_working_headcounts_unique_actors() -> None:
    assert pd.Timestamp("2026-04-08").weekday() == 2  # Wednesday
    df = pd.DataFrame(
        [
            {"actor": "cr01@relio.ch", "day": "2026-04-08", "availability_pct": 100},
            {"actor": "cr02@relio.ch", "day": "2026-04-08", "availability_pct": 50},
            {"actor": "cr01@relio.ch", "day": "2026-04-08", "availability_pct": 0},
        ]
    )
    out = wednesday_working_headcounts(df)
    assert len(out) == 1
    assert int(out.iloc[0]["n_employees"]) == 2


def test_generate_case_risk_is_deterministic() -> None:
    apps = ["a1", "a2", "a3"]
    r1 = generate_case_risk(apps, seed=1)
    r2 = generate_case_risk(apps, seed=1)
    assert r1.to_dict(orient="records") == r2.to_dict(orient="records")


def test_score_transitions_uses_team_specific_risk() -> None:
    transitions = pd.DataFrame(
        [
            {
                "application_id": "app1",
                "team": "CR",
                "actor": "alice",
                "transition_at": "2026-04-01T10:00:00",
                "from_stage": 1,
                "to_stage": 2,
            },
            {
                "application_id": "app1",
                "team": "Compliance",
                "actor": "bob",
                "transition_at": "2026-04-02T10:00:00",
                "from_stage": 2,
                "to_stage": 3,
            },
        ]
    )
    case_risk = pd.DataFrame(
        [
            {
                "application_id": "app1",
                "initial_risk": "low",
                "end_risk": "high",
            }
        ]
    )
    cal = generate_staffing_calendar(
        actors=["alice", "bob"],
        team="CR",
        start_day="2026-04-01",
        end_day="2026-04-02",
        seed=1,
    )
    cal2 = generate_staffing_calendar(
        actors=["alice", "bob"],
        team="Compliance",
        start_day="2026-04-01",
        end_day="2026-04-02",
        seed=1,
    )
    staffing = pd.concat([cal, cal2], ignore_index=True)

    per_actor, detailed = score_transitions(transitions, case_risk, staffing)
    # CR transition should use initial risk (low)
    cr_points = int(detailed.loc[detailed["team"] == "CR", "risk_points"].iloc[0])
    # Compliance transition should use end risk (high)
    comp_points = int(detailed.loc[detailed["team"] == "Compliance", "risk_points"].iloc[0])
    assert cr_points == RISK_POINTS["low"]
    assert comp_points == RISK_POINTS["high"]
    assert set(per_actor["actor"].tolist()) == {"alice", "bob"}

