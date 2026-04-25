"""
Canonical audit log contract for Relio Operations Intelligence.

The analytics layer should only depend on these column names and types,
not on whether rows came from synthetic generation or PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

AUDIT_COLUMNS = (
    "timestamp",
    "actor",
    "action",
    "description",
    "context",
    "application_id",
    "product_type",
)


@dataclass(frozen=True)
class AuditLogRow:
    timestamp: pd.Timestamp
    actor: str
    action: str
    description: str
    context: Mapping[str, Any] | None
    application_id: str
    product_type: str

    def as_dict(self) -> dict[str, Any]:
        ctx = self.context
        return {
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action,
            "description": self.description,
            "context": ctx if ctx is not None else {},
            "application_id": self.application_id,
            "product_type": self.product_type,
        }


def audit_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in AUDIT_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
    return df[list(AUDIT_COLUMNS)]
