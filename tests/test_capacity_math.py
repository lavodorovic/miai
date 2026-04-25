from __future__ import annotations

from analytics.capacity import (
    project_backlog_clear_days,
    project_cycle_time_days,
    project_wip,
)


def test_project_cycle_time_scaling() -> None:
    assert project_cycle_time_days(10.0, base_fte=10.0, new_fte=20.0) == 5.0
    assert project_cycle_time_days(10.0, base_fte=10.0, new_fte=5.0) == 20.0
    assert project_cycle_time_days(0.0, base_fte=10.0, new_fte=5.0) == 0.0
    assert project_cycle_time_days(10.0, base_fte=0.0, new_fte=5.0) == 0.0


def test_project_wip() -> None:
    assert project_wip(2.0, 5.0) == 10.0
    assert project_wip(0.0, 5.0) == 0.0
    assert project_wip(2.0, 0.0) == 0.0


def test_project_backlog_clear_days() -> None:
    assert project_backlog_clear_days(10.0, 2.0) == 5.0
    assert project_backlog_clear_days(10.0, 0.0) == 0.0
    assert project_backlog_clear_days(0.0, 2.0) == 0.0

