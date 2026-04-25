"""
SQL-backed period dashboard (PHASE_0 §2 / §5). Requires date_range on QueryManager calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from analytics.query_manager import QueryManager


@dataclass(frozen=True)
class PeriodDashboardData:
    start_snapshot: pd.DataFrame
    end_snapshot: pd.DataFrame
    n_arrivals: int
    n_losses: int
    transition_edges: pd.DataFrame
    n_movers: int


def load_period_dashboard(
    qm: QueryManager,
    *,
    product_type: str | None,
    date_range: tuple[str, str],
) -> PeriodDashboardData:
    start_df = qm.run(
        "period_start_snapshot",
        product_type=product_type,
        date_range=date_range,
    )
    end_df = qm.run(
        "period_end_snapshot",
        product_type=product_type,
        date_range=date_range,
    )
    al = qm.run(
        "period_arrivals_losses",
        product_type=product_type,
        date_range=date_range,
    )
    n_arrivals = int(al.iloc[0]["n_arrivals"]) if len(al) else 0
    n_losses = int(al.iloc[0]["n_losses"]) if len(al) else 0
    edges = qm.run(
        "period_transition_edges_unique_apps",
        product_type=product_type,
        date_range=date_range,
    )
    movers = qm.run(
        "period_transition_movers_unique_apps",
        product_type=product_type,
        date_range=date_range,
    )
    n_movers = int(movers.iloc[0]["n_movers"]) if len(movers) else 0
    return PeriodDashboardData(
        start_snapshot=start_df,
        end_snapshot=end_df,
        n_arrivals=n_arrivals,
        n_losses=n_losses,
        transition_edges=edges,
        n_movers=n_movers,
    )
