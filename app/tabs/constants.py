"""Shared dashboard constants (aligned with process definitions / funnel)."""

from __future__ import annotations

TERMINAL_ACTIONS: tuple[str, ...] = (
    "MASTER_DATA_SUBMITTED",
    "APPLICATION_REJECTED",
    "APPLICATION_CANCELLED",
    "OFFER_REFUSED",
)

# Funnel step_order for terminal buckets (aligned with funnel_overview labels).
TERMINAL_STEP_ORDERS: frozenset[int] = frozenset({17, 18, 22, 26})

LOOP_ACTIONS: frozenset[str] = frozenset(
    {
        "COMPLIANCE_REVIEW_STARTED",
        "INTERACTION_STARTED",
        "INTERACTION_SUBMITTED",
        "ANSWERS_EDIT_STARTED",
    }
)
