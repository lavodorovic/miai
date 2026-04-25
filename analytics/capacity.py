from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapacityInputs:
    inflow_per_day: float
    cr_fte: float
    compliance_fte: float


@dataclass(frozen=True)
class CapacityOutputs:
    projected_wip: float
    projected_cycle_time_days: float


def _safe_div(n: float, d: float) -> float:
    return 0.0 if d == 0 else (n / d)


def project_cycle_time_days(current_cycle_time_days: float, *, base_fte: float, new_fte: float) -> float:
    """
    Linear capacity assumption:
    - throughput scales ~linearly with FTE
    - therefore cycle time scales inversely with FTE

    If new_fte == 0 -> cycle time undefined; return 0.0 (caller should handle).
    """
    if current_cycle_time_days <= 0:
        return 0.0
    if base_fte <= 0 or new_fte <= 0:
        return 0.0
    scale = base_fte / new_fte
    return current_cycle_time_days * scale


def project_wip(inflow_per_day: float, cycle_time_days: float) -> float:
    """Little's Law: WIP ≈ throughput * cycle time, using inflow as throughput proxy."""
    if inflow_per_day <= 0 or cycle_time_days <= 0:
        return 0.0
    return inflow_per_day * cycle_time_days


def project_backlog_clear_days(backlog: float, throughput_per_day: float) -> float:
    """How many days to clear backlog at steady throughput."""
    if backlog <= 0:
        return 0.0
    return _safe_div(backlog, throughput_per_day)

