"""
Synthetic Relio-style audit logs for stress-testing analytics.

Grounded in:
- State-machine hubs (REVIEW <-> INTERACTION, DOCUMENTS_UPLOAD, OFFER_*, terminals).
- Screenshot-derived action names and description phrasing (German snippets optional).
"""

from __future__ import annotations

import json
import math
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from audit_log_schema import AUDIT_COLUMNS, audit_frame

SYSTEM_ACTOR = "N.A. SYSTEM ACTION"

_TERMINAL_ACTIONS = frozenset({
    "MASTER_DATA_SUBMITTED",
    "APPLICATION_REJECTED",
    "APPLICATION_CANCELLED",
    "OFFER_REFUSED",
})

CR_ROSTER = [f"cr{i:02d}@relio.ch" for i in range(1, 9)]
COMPLIANCE_ROSTER = [f"compliance{i:02d}@relio.ch" for i in range(1, 9)]


def _pick_assigned(rng: random.Random, assigned: str, roster: list[str]) -> str:
    # 80% stay with assigned, 20% random teammate (cover/escalation).
    if rng.random() < 0.80:
        return assigned
    return roster[rng.randint(0, len(roster) - 1)]

SWISS_TOWNS = ["Zug", "Zürich", "Genf", "Basel", "Bern", "Lausanne"]
SWISS_ZIPS = ["6300", "8001", "1201", "4051", "3011", "1003"]

PRODUCT_TYPES = (
    "Business Account",
    "Capital Payments Account",
)

BA_PRODUCT = "Business Account"
BA_WEEK_MIN_NEW_APPS = 25
BA_WEEK_MIN_TERMINAL = 20
BA_WEEK_MIN_CUSTOMERS = 4


def _che_uid(rng: random.Random) -> str:
    body = "".join(str(rng.randint(0, 9)) for _ in range(9))
    return f"CHE{body}"


def _fake_iban_chf(rng: random.Random) -> str:
    digits = "".join(str(rng.randint(0, 9)) for _ in range(19))
    return f"CH{digits}"


def _german_interaction_blob(rng: random.Random, index: int, started_iso: str) -> dict[str, Any]:
    codes = ["QADD3", "QADD4", "QADD5", "QADD18"]
    picked = rng.sample(codes, k=rng.randint(2, 4))
    questions = []
    for code in picked:
        questions.append(
            {
                "code": code,
                "text": (
                    "Bitte reichen Sie Adressnachweis, CV und Kontoauszug nach. "
                    "Ergänzen Sie die Geschäftsbeziehung zu Phoenix Logistics Trading."
                ),
                "type": "LONG_TEXT" if code.endswith("8") else "FILE",
                "validationRules": {"required": True},
                "answered": rng.random() > 0.2,
            }
        )
    return {
        "index": index,
        "comment": "",
        "started": started_iso,
        "isCrInteraction": False,
        "additionalQuestions": questions,
    }


def _master_data_payload(rng: random.Random, company: str, uid: str) -> dict[str, Any]:
    return {
        "masterData": {
            "accountHoldingPartyData": {
                "flags": {"syntheticProfile": True},
                "companyDetails": {
                    "companyId": uid,
                    "companyName": company,
                },
            },
            "personName": {"lastName": "Schulz", "firstName": "Michael Adam"},
            "dateOfBirth": "1975-10-01",
            "nationality": "PL",
            "zip": rng.choice(SWISS_ZIPS),
            "town": rng.choice(SWISS_TOWNS),
            "expectedIncomeYearly": rng.choice([80_000, 100_000, 150_000]),
            "expectedVolumeYearly": rng.choice([80_000, 120_000, 200_000]),
            "allAccounts": [{"currency": "CHF", "accountId": _fake_iban_chf(rng)}],
        }
    }


@dataclass
class SyntheticApplication:
    application_id: str
    customer_email: str
    signatory_email: str | None
    company_name: str
    company_uid: str
    assigned_cr: str
    assigned_compliance: str
    product_type: str
    scenario: str
    interaction_rounds: int = 1
    rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        if self.signatory_email is None:
            self.signatory_email = self.customer_email


def _delay_customer(rng: random.Random) -> timedelta:
    return timedelta(minutes=rng.randint(2, 90))


def _delay_overnight(rng: random.Random) -> timedelta:
    return timedelta(hours=rng.randint(8, 36))


def _delay_ops(rng: random.Random) -> timedelta:
    return timedelta(minutes=rng.randint(5, 120))


def _delay_system(rng: random.Random) -> timedelta:
    return timedelta(seconds=rng.randint(1, 45))


def _delay_customer_slow(rng: random.Random) -> timedelta:
    return timedelta(hours=rng.randint(12, 120))


def build_timeline(app: SyntheticApplication, start: datetime) -> list[dict[str, Any]]:
    """Return ordered audit rows (chronological) for one application."""
    rng = app.rng
    t = start
    rows: list[dict[str, Any]] = []
    assigned_cr = app.assigned_cr
    assigned_compliance = app.assigned_compliance
    cust = app.customer_email
    sig = app.signatory_email or cust
    offer_id = str(rng.randint(1000, 9999))

    def push(
        *,
        delta: timedelta,
        actor: str,
        action: str,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        nonlocal t
        t = t + delta
        rows.append(
            {
                "timestamp": t,
                "actor": actor,
                "action": action,
                "description": description,
                "context": context if context is not None else {},
                "application_id": app.application_id,
                "product_type": app.product_type,
            }
        )

    # --- Customer intake ---
    push(
        delta=timedelta(0),
        actor=cust,
        action="APPLICATION_STARTED",
        description="The application created and started.",
    )
    push(delta=_delay_customer(rng), actor=cust, action="APPLICATION_SUBMITTED", description="The application is submitted.")
    push(
        delta=_delay_customer(rng),
        actor=cust,
        action="DOCUMENTS_SUBMITTED",
        description="The application documents have been submitted by customer.",
        context={"filesUploadedCount": rng.randint(1, 5)},
    )

    # --- Assignment (may be simultaneous in real logs) ---
    push(
        delta=_delay_overnight(rng),
        actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
        action="ACCOUNT_MANAGER_ASSIGNED",
        description="Account manager assigned.",
        context={"assignedTo": assigned_cr},
    )
    push(
        delta=timedelta(seconds=rng.randint(0, 5)),
        actor=assigned_cr,
        action="APP_ASSIGNED",
        description="The application is assigned to the user.",
        context={"assignedTo": assigned_cr},
    )

    push(
        delta=timedelta(seconds=rng.randint(3, 20)),
        actor=assigned_cr,
        action="CUSTOMER_RELATION_REVIEW_STARTED",
        description="Customer Relation review is started.",
    )
    if app.scenario == "stalled_cr_review":
        return rows
    push(
        delta=_delay_ops(rng),
        actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
        action="CUSTOMER_RELATION_REVIEW_COMPLETED",
        description="User completed Customer Relation review.",
    )

    push(
        delta=timedelta(seconds=rng.randint(2, 15)),
        actor=assigned_compliance,
        action="COMPLIANCE_REVIEW_STARTED",
        description="Compliance review is started.",
    )

    if app.scenario == "stalled_ops_compliance":
        push(
            delta=_delay_ops(rng),
            actor=_pick_assigned(rng, assigned_compliance, COMPLIANCE_ROSTER),
            action="LABEL_ADDED",
            description="User added label 'Enhanced due diligence' to application.",
            context={"risk": "High", "reason": "Complex ownership and cross-border payments"},
        )
        push(
            delta=_delay_overnight(rng),
            actor=_pick_assigned(rng, assigned_compliance, COMPLIANCE_ROSTER),
            action="COMPLIANCE_REVIEW_STARTED",
            description="Compliance review is restarted after enhanced due diligence label.",
            context={"reopened": True, "reason": "EDD follow-up required"},
        )
        return rows

    if app.scenario == "rejected":
        push(
            delta=_delay_ops(rng),
            actor=_pick_assigned(rng, assigned_compliance, COMPLIANCE_ROSTER),
            action="COMPLIANCE_REVIEW_COMPLETED",
            description="Compliance review is completed.",
            context={"risk": "High", "reason": "Insufficient documentation"},
        )
        push(
            delta=_delay_ops(rng),
            actor=_pick_assigned(rng, assigned_compliance, COMPLIANCE_ROSTER),
            action="APPLICATION_REJECTED",
            description="Application rejected after compliance review.",
            context={"reasonCode": "COMPLIANCE"},
        )
        return rows

    if app.scenario == "cancelled_mid":
        push(
            delta=_delay_ops(rng),
            actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
            action="APPLICATION_CANCELLED",
            description="Application cancelled by operator.",
            context={"reason": "customer_withdrew"},
        )
        return rows

    # --- Interaction loop(s): REVIEW <-> customer ---
    for round_idx in range(app.interaction_rounds):
        started_iso = (t + timedelta(minutes=rng.randint(5, 40))).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        push(
            delta=_delay_ops(rng),
            actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
            action="INTERACTION_STARTED",
            description="The additional interaction is sent.",
            context=_german_interaction_blob(rng, index=round_idx, started_iso=started_iso),
        )
        if app.scenario == "stalled_customer" and round_idx == app.interaction_rounds - 1:
            # Stop before customer responds — long lead time, no resolution in slice
            push(
                delta=_delay_customer_slow(rng),
                actor=cust,
                action="INTERACTION_SUBMITTED",
                description="The additional interaction is submitted.",
                context=_german_interaction_blob(rng, index=round_idx, started_iso=started_iso),
            )
            return rows

        cust_delay = _delay_customer_slow(rng) if rng.random() < 0.15 else _delay_customer(rng)
        push(
            delta=cust_delay,
            actor=cust,
            action="INTERACTION_SUBMITTED",
            description="The additional interaction is submitted.",
            context=_german_interaction_blob(rng, index=round_idx, started_iso=started_iso),
        )

        if rng.random() < 0.12 and round_idx < app.interaction_rounds - 1:
            push(
                delta=_delay_ops(rng),
                actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
                action="CUSTOMER_RELATION_INTERACTION_CANCELLED",
                description="Customer Relation interaction cancelled.",
                context={"additionalQuestions": [{"code": "QADD18", "text": "Communication via secure channel only."}]},
            )

    # --- Optional internal edits (tight timing like screenshots) ---
    if rng.random() < 0.35:
        push(
            delta=_delay_ops(rng),
            actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
            action="ANSWERS_EDIT_STARTED",
            description="User started application answers edit.",
        )
        push(
            delta=timedelta(seconds=rng.randint(15, 90)),
            actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
            action="ANSWERS_EDIT_FINISHED",
            description="User finished application answers edit.",
            context={"archiveVersion": rng.randint(0, 2)},
        )

    if rng.random() < 0.25:
        push(
            delta=timedelta(seconds=rng.randint(5, 300)),
            actor=_pick_assigned(rng, assigned_compliance, COMPLIANCE_ROSTER),
            action="LABEL_ADDED",
            description="User added label 'Payments account' to application.",
        )

    push(
        delta=_delay_ops(rng),
        actor=_pick_assigned(rng, assigned_compliance, COMPLIANCE_ROSTER),
        action="COMPLIANCE_REVIEW_COMPLETED",
        description="Compliance review is completed.",
        context={"risk": rng.choice(["Low", "Medium", "Medium High", "High"]), "reason": ""},
    )

    # --- Offer path (screenshots mix OFFER_PREPARED / OFFER_SENT) ---
    use_prepared = rng.random() < 0.4
    if use_prepared:
        push(
            delta=_delay_ops(rng),
            actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
            action="OFFER_PREPARED",
            description="The package is assigned to the prospect.",
            context={
                "amount": rng.choice([49, 99, 149]),
                "cadence": "MONTHLY",
                "currency": "CHF",
                "companyName": app.company_name,
            },
        )

    push(
        delta=timedelta(minutes=rng.randint(2, 45)),
        actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
        action="OFFER_SENT",
        description="Offer sent to customer.",
        context={"sentTo": sig, "offerId": offer_id},
    )

    if app.scenario == "stalled_offer":
        return rows

    if app.scenario == "offer_refused":
        push(
            delta=_delay_customer(rng),
            actor=cust,
            action="OFFER_REFUSED",
            description="Customer refused the offer.",
            context={"offerId": offer_id},
        )
        return rows

    push(
        delta=_delay_customer(rng),
        actor=cust,
        action="OFFER_RESPONSE",
        description="The customer selected payment application user(s).",
        context={"action": "acceptOffer", "offerId": offer_id, "userSelection": [{"email": sig, "role": "SIGNATORY"}]},
    )

    push(
        delta=_delay_system(rng),
        actor=SYSTEM_ACTOR,
        action="VIDEO_IDENT_SENT",
        description="Video ident sent to the signatory.",
        context={},
    )
    push(
        delta=timedelta(minutes=rng.randint(5, 25)),
        actor=SYSTEM_ACTOR,
        action="VIDEO_IDENT_FINISHED",
        description="All signatories have finished the video ident process.",
        context={"status": "Success", "failedSignatories": []},
    )

    push(
        delta=timedelta(minutes=rng.randint(5, 20)),
        actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
        action="ENROLLMENT_APPROVED",
        description="User approved enrollment of a customer.",
    )

    push(
        delta=timedelta(hours=rng.randint(4, 72)),
        actor=_pick_assigned(rng, assigned_cr, CR_ROSTER),
        action="MASTER_DATA_SUBMITTED",
        description="User submitted master data to Hawk AI.",
        context=_master_data_payload(rng, app.company_name, app.company_uid),
    )

    return rows


def _hero_applications(seed: int | None) -> list[SyntheticApplication]:
    base_seed = 10_000 if seed is None else int(seed) + 10_000
    specs = [
        (
            "demo-hero-success-full",
            "success_full",
            1,
            "Atlas Robotics AG",
            "Business Account",
            "cr01@relio.ch",
            "compliance01@relio.ch",
        ),
        (
            "demo-hero-compliance-loop",
            "success_full",
            3,
            "Nova Crossborder Trading AG",
            "Capital Payments Account",
            "cr02@relio.ch",
            "compliance02@relio.ch",
        ),
        (
            "demo-hero-stuck-customer",
            "stalled_customer",
            2,
            "Helvetia Import Export GmbH",
            "Business Account",
            "cr03@relio.ch",
            "compliance03@relio.ch",
        ),
        (
            "demo-hero-stuck-compliance",
            "stalled_ops_compliance",
            1,
            "Alpine Crypto Advisory GmbH",
            "Capital Payments Account",
            "cr04@relio.ch",
            "compliance04@relio.ch",
        ),
        (
            "demo-hero-offer-refused",
            "offer_refused",
            1,
            "Phoenix Treasury Services AG",
            "Business Account",
            "cr05@relio.ch",
            "compliance05@relio.ch",
        ),
        (
            "demo-hero-rejected",
            "rejected",
            1,
            "BlackPearl Holdings GmbH",
            "Capital Payments Account",
            "cr06@relio.ch",
            "compliance06@relio.ch",
        ),
    ]
    heroes: list[SyntheticApplication] = []
    for idx, (app_id, scenario, rounds, company, product, cr, comp) in enumerate(specs):
        heroes.append(
            SyntheticApplication(
                application_id=app_id,
                customer_email=f"{app_id}@example.com",
                signatory_email=f"{app_id}.signatory@example.com",
                company_name=company,
                company_uid=f"CHE900000{idx:03d}",
                assigned_cr=cr,
                assigned_compliance=comp,
                product_type=product,
                scenario=scenario,
                interaction_rounds=rounds,
                rng=random.Random(base_seed + idx),
            )
        )
    return heroes


def anchor_application_timelines(
    df: pd.DataFrame,
    *,
    timeline_end: pd.Timestamp,
    seed: int,
) -> pd.DataFrame:
    """
    Shift each application's timestamps by a constant delta so its **last** event lands in a
    window ending at ``timeline_end`` (preserves inter-event gaps and state-machine order).

    Apps that already terminated are spread over the last ~12 weeks (recent-biased) so the
    BA performance chart shows organic terminal/customer growth instead of a single late
    spike. In-flight apps stay clustered near the as-of cut so stuck-share enforcement and
    SLA aging stay realistic.
    """
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    pieces: list[pd.DataFrame] = []
    for aid, g in out.groupby("application_id", sort=False):
        g = g.sort_values("timestamp")
        last_ts = g["timestamp"].iloc[-1]
        last_action = str(g["action"].iloc[-1])
        r = random.Random((seed + abs(hash(aid))) % (2**31))
        if last_action in _TERMINAL_ACTIONS:
            # Linear-ramp distribution: prob of week i ∝ (i+1) so anchored terminals
            # form a clean Jan→Apr growth without clustering at the very end. Pool spans
            # ~16 weeks back so the chart shows a smooth ramp across the demo window.
            n_pool = 16
            weights = list(range(1, n_pool + 1))
            chosen = r.choices(range(n_pool), weights=weights, k=1)[0]
            weeks_back = (n_pool - 1 - chosen) + r.random()
            back_hours = max(8, int(weeks_back * 7 * 24) + r.randint(0, 23))
        else:
            back_hours = r.randint(8, 21 * 24)
        target_last = timeline_end - pd.Timedelta(hours=back_hours)
        delta = target_last - last_ts
        g = g.assign(timestamp=g["timestamp"] + delta)
        pieces.append(g)
    return pd.concat(pieces, ignore_index=True).sort_values(
        ["application_id", "timestamp"]
    ).reset_index(drop=True)


def _carryover_cut_index(actions: list[str]) -> int:
    """
    Split timeline so the prefix ends around compliance review started (stage ~8),
    keeping at least one row in the suffix and a non-trivial prefix.
    """
    if len(actions) < 4:
        return max(1, len(actions) - 1)
    try:
        idx = actions.index("COMPLIANCE_REVIEW_STARTED")
        cut = idx + 1
    except ValueError:
        cut = min(6, len(actions) - 1)
    return max(3, min(cut, len(actions) - 1))


def _compress_timeline_into_week(
    rows: list[dict[str, Any]],
    week_start: pd.Timestamp,
    rng: random.Random,
    *,
    timeline_end: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    """Spread events monotonically inside [week_start, week_end] so ISO week buckets match the chart."""
    rows = sorted(rows, key=lambda r: r["timestamp"])
    ws = pd.Timestamp(week_start).normalize()
    we = ws + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)
    if timeline_end is not None:
        te = pd.Timestamp(timeline_end)
        if te.tzinfo is not None:
            te = te.tz_localize(None)
        we = min(we, te)
    if we <= ws:
        we = ws + pd.Timedelta(minutes=90)
    span_s = max((we - ws).total_seconds(), 60.0)
    n = len(rows)
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        frac = (i / (n - 1)) if n > 1 else 0.5
        ts = ws + pd.Timedelta(seconds=frac * span_s * 0.995)
        out.append({**r, "timestamp": ts})
    return out


def _ba_weekly_chart_counts(work: pd.DataFrame) -> pd.DataFrame:
    """Same BA × week grain as ``overview_performance_weekly.sql`` (full audit date span)."""
    import duckdb as _duckdb

    terms = ", ".join(f"'{x}'" for x in sorted(_TERMINAL_ACTIONS))
    con = _duckdb.connect(":memory:")
    con.register("audit_logs", work)
    df = con.sql(
        f"""
        SELECT
            date_trunc('week', timestamp)::DATE AS week_start,
            COUNT(DISTINCT CASE WHEN action = 'APPLICATION_STARTED' THEN application_id END)::BIGINT AS n_new_applications,
            COUNT(DISTINCT CASE WHEN action IN ({terms}) THEN application_id END)::BIGINT AS n_terminal_phase,
            COUNT(DISTINCT CASE WHEN action = 'MASTER_DATA_SUBMITTED' THEN application_id END)::BIGINT AS n_accounts_opened
        FROM audit_logs
        WHERE product_type = '{BA_PRODUCT}'
        GROUP BY 1
        ORDER BY 1
        """
    ).df()
    con.close()
    return df


def _ba_weekly_target_curve(
    weeks: list[pd.Timestamp],
) -> dict[pd.Timestamp, tuple[int, int, int]]:
    """Per-week targets for the BA performance chart.

    Invariants:
      - new applications      always > new customers
      - total cases done      always > new customers
      - new applications      crosses above/below total cases done across the period
                              (driven by independently-phased wiggles)
      - wiggle amplitude      strongest in the middle of the period, vanishes at edges

    Floors (25 / 20 / 4) are still respected as hard minimums.
    """
    n = len(weeks)
    if n == 0:
        return {}
    out: dict[pd.Timestamp, tuple[int, int, int]] = {}
    for i, w in enumerate(weeks):
        p = i / max(n - 1, 1)

        n_new_base = 40 + 105 * (p ** 1.20)
        n_term_base = 32 + 95 * (p ** 1.30)
        n_cust_base = 22 + 55 * (p ** 1.45)

        # Mid-emphasis envelope: 1 at p=0.5, 0 at edges.
        mid_emphasis = math.sin(math.pi * p) ** 1.4

        # Independent oscillations per series: different frequencies + phases so the
        # three lines drift apart and cross each other naturally.
        new_wiggle = (
            math.sin(i * 1.30 + 0.4) * 26
            + math.sin(i * 0.65 + 1.7) * 14
        ) * mid_emphasis
        term_wiggle = (
            math.sin(i * 1.55 + 2.3) * 30
            + math.sin(i * 0.55 + 0.2) * 12
        ) * mid_emphasis
        cust_wiggle = math.sin(i * 0.95 + 1.1) * 9 * mid_emphasis

        n_new = n_new_base + new_wiggle
        n_term = n_term_base + term_wiggle
        n_cust = n_cust_base + cust_wiggle

        # Plateau the curves in the very last 18% of weeks: the linear-ramp
        # anchoring already piles a lot of raw terminals there, and we don't
        # want injection to multiply that into a runaway spike.
        if p > 0.82:
            plateau_p = 0.82
            cap_new = 40 + 105 * (plateau_p ** 1.20) + 12
            cap_term = 32 + 95 * (plateau_p ** 1.30) + 18
            cap_cust = 22 + 55 * (plateau_p ** 1.45) + 6
            n_new = min(n_new, cap_new)
            n_term = min(n_term, cap_term)
            n_cust = min(n_cust, cap_cust)

        n_new_i = max(int(round(n_new)), BA_WEEK_MIN_NEW_APPS)
        n_term_i = max(int(round(n_term)), BA_WEEK_MIN_TERMINAL)
        n_cust_i = max(int(round(n_cust)), BA_WEEK_MIN_CUSTOMERS)

        # Hard invariants the chart depends on:
        if n_term_i <= n_cust_i:
            n_term_i = n_cust_i + 6
        if n_new_i <= n_cust_i:
            n_new_i = n_cust_i + 8

        out[pd.Timestamp(w).normalize()] = (n_new_i, n_term_i, n_cust_i)
    return out


_NON_CUSTOMER_TERMINAL_SCENARIOS = ("rejected", "cancelled_mid", "offer_refused")


def _build_synth_ba_app(
    *,
    aid: str,
    scenario: str,
    rng: random.Random,
    synth_i: int,
) -> SyntheticApplication:
    return SyntheticApplication(
        application_id=aid,
        customer_email=f"{aid}@floor.example.com",
        signatory_email=None,
        company_name=f"FloorCo {synth_i}",
        company_uid=_che_uid(rng),
        assigned_cr=CR_ROSTER[synth_i % len(CR_ROSTER)],
        assigned_compliance=COMPLIANCE_ROSTER[synth_i % len(COMPLIANCE_ROSTER)],
        product_type=BA_PRODUCT,
        scenario=scenario,
        interaction_rounds=1,
        rng=random.Random(rng.randint(0, 2**31 - 1)),
    )


def _spread_inflight_timeline_fresh(
    rows: list[dict[str, Any]],
    week_start: pd.Timestamp,
    timeline_end: pd.Timestamp,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Spread a stalled timeline so APPLICATION_STARTED lands in ``week_start``
    (so the BA chart counts it there) and the last event is within 48h of
    ``timeline_end`` (so the app is **fresh** in-flight, not stuck)."""
    rows = sorted(rows, key=lambda r: r["timestamp"])
    ws = pd.Timestamp(week_start).normalize()
    te = pd.Timestamp(timeline_end)
    if te.tzinfo is not None:
        te = te.tz_localize(None)
    first_ts = ws + pd.Timedelta(hours=rng.randint(6, 30))
    last_ts = te - pd.Timedelta(hours=rng.randint(8, 44))
    if last_ts <= first_ts + pd.Timedelta(hours=2):
        return _compress_inflight_timeline_stuck(rows, week_start, timeline_end, rng)
    span_s = (last_ts - first_ts).total_seconds()
    n = len(rows)
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        frac = i / max(n - 1, 1)
        ts = first_ts + pd.Timedelta(seconds=frac * span_s)
        out.append({**r, "timestamp": ts})
    return out


def _compress_inflight_timeline_stuck(
    rows: list[dict[str, Any]],
    week_start: pd.Timestamp,
    timeline_end: pd.Timestamp,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Compress a stalled timeline into ``week_start``'s ISO week, but force the
    last event to land at least 72h before ``timeline_end`` so the app is
    counted as **stuck** in the in-flight stuck-share calculation, even when
    the assigned week is the very last week of the period."""
    rows = sorted(rows, key=lambda r: r["timestamp"])
    ws = pd.Timestamp(week_start).normalize()
    te = pd.Timestamp(timeline_end)
    if te.tzinfo is not None:
        te = te.tz_localize(None)
    we = ws + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)
    cutoff = te - pd.Timedelta(hours=rng.randint(72, 144))
    we_stuck = min(we, cutoff)
    if we_stuck <= ws:
        we_stuck = ws + pd.Timedelta(hours=12)
    span_s = max((we_stuck - ws).total_seconds(), 60.0)
    n = len(rows)
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        frac = (i / (n - 1)) if n > 1 else 0.5
        ts = ws + pd.Timedelta(seconds=frac * span_s * 0.995)
        out.append({**r, "timestamp": ts})
    return out


def inject_ba_weekly_floors(
    df: pd.DataFrame,
    *,
    seed: int,
    timeline_end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Hit per-week BA performance targets without inflating the in-flight KPI.

    Two injection scenario classes are used so other dashboards stay realistic:
      - ``success_full``                 → +1 new app, +1 total done, +1 new customer
      - ``rejected`` / ``cancelled_mid`` /
        ``offer_refused``                → +1 new app, +1 total done, +0 customer

    No in-flight scenarios are injected here (that would inflate the "In-flight"
    KPI). Instead, when a week needs more new applications than success_full +
    non-customer terminals can provide, we inject extra non-customer terminals,
    accepting that ``total cases done`` will overshoot its target — visually
    that's the desired effect (done line briefly leads new line in those weeks).

    Allocation per week:
      - n_succ        = max(0, target_cust - raw_cust)
      - n_term_only   = max(0, target_term - raw_term - n_succ)
      - if final new ≤ final customers + 7, top up n_term_only so
        new > customers always (user invariant).
    """
    rng = random.Random(seed + 61_000)
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"])
    synth_i = 0
    for _pass in range(35):
        perf = _ba_weekly_chart_counts(work)
        weeks = [pd.Timestamp(w).normalize() for w in perf["week_start"].tolist()]
        targets = _ba_weekly_target_curve(weeks)
        chunk_all: list[dict[str, Any]] = []
        for _, row in perf.iterrows():
            ws = pd.Timestamp(row["week_start"]).normalize()
            t_new, t_term, t_cust = targets.get(
                ws, (BA_WEEK_MIN_NEW_APPS, BA_WEEK_MIN_TERMINAL, BA_WEEK_MIN_CUSTOMERS)
            )
            r_new = int(row["n_new_applications"])
            r_term = int(row["n_terminal_phase"])
            r_cust = int(row["n_accounts_opened"])

            n_succ = max(0, t_cust - r_cust)
            n_term_only = max(0, t_term - r_term - n_succ)

            final_cust = r_cust + n_succ
            final_new = r_new + n_succ + n_term_only
            if final_new <= final_cust + 7:
                top_up = (final_cust + 8) - final_new
                n_term_only += top_up

            inject_plan: list[str] = []
            inject_plan.extend(["success_full"] * n_succ)
            for k in range(n_term_only):
                inject_plan.append(
                    _NON_CUSTOMER_TERMINAL_SCENARIOS[(synth_i + k) % len(_NON_CUSTOMER_TERMINAL_SCENARIOS)]
                )

            if not inject_plan:
                continue

            for scenario in inject_plan:
                aid = f"synth-ba-{ws.strftime('%Y%m%d')}-{synth_i}"
                synth_i += 1
                app = _build_synth_ba_app(
                    aid=aid, scenario=scenario, rng=rng, synth_i=synth_i
                )
                t0 = datetime(ws.year, ws.month, ws.day, rng.randint(6, 20), rng.randint(0, 59))
                raw_rows = build_timeline(app, t0)
                chunk_all.extend(
                    _compress_timeline_into_week(raw_rows, ws, rng, timeline_end=timeline_end)
                )

        if not chunk_all:
            break
        work = pd.concat([work, audit_frame(chunk_all)], ignore_index=True)

    return work.sort_values(["application_id", "timestamp"]).reset_index(drop=True)


def enforce_cr_breach_ratio_vs_compliance(
    df: pd.DataFrame,
    *,
    repo_root: Path,
    timeline_end: pd.Timestamp,
    seed: int,
    ratio: float = 0.10,
) -> pd.DataFrame:
    """Match CR-review breached count ≈ ratio × Compliance breached (± rounding)."""
    import duckdb

    rr = str(repo_root.resolve())
    if rr not in sys.path:
        sys.path.insert(0, rr)

    from analytics.ddl_loader import apply_ddl
    from analytics.query_manager import QueryManager

    ref = pd.Timestamp(timeline_end)
    if ref.tzinfo is not None:
        ref = ref.tz_localize(None)
    rng = random.Random(seed + 313_131)
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"])

    for _ in range(200):
        con = duckdb.connect(":memory:")
        con.register("audit_logs_df", work)
        con.execute("CREATE TABLE audit_logs AS SELECT * FROM audit_logs_df")
        apply_ddl(con, repo_root)
        qm = QueryManager(con)
        sql = qm.load_sql("sla_breached_applications")
        sql = sql.replace("\nLIMIT 200", "").replace("LIMIT 200;", "").replace("LIMIT 200", "")
        br = qm.run_sql(sql, product_type=None, date_range=None)

        if br.empty:
            con.close()
            break

        cr_df = br.loc[br["sla_area"].astype(str) == "CR review"]
        co_df = br.loc[br["sla_area"].astype(str) == "Compliance"]
        n_cr = len(cr_df)
        n_c = len(co_df)
        target = int(round(ratio * n_c)) if n_c > 0 else 0
        excess = n_cr - target

        if excess > 0:
            ids = cr_df["application_id"].astype(str).tolist()
            rng.shuffle(ids)
            for aid in ids[:excess]:
                mask = work["application_id"].astype(str) == aid
                if not mask.any():
                    continue
                g = work.loc[mask].sort_values("timestamp")
                last_ts = pd.Timestamp(g.iloc[-1]["timestamp"])
                tgt = ref - pd.Timedelta(hours=rng.randint(6, 22))
                delta = tgt - last_ts
                work.loc[mask, "timestamp"] = work.loc[mask, "timestamp"] + delta
            con.close()
            continue

        if excess < 0:
            deficit = -excess
            cand = qm.run("cr_review_inflight_pre_breach_ids", product_type=None, date_range=None)
            con.close()
            ids = cand["application_id"].astype(str).tolist() if len(cand) else []
            for aid in ids[:deficit]:
                mask = work["application_id"].astype(str) == aid
                if not mask.any():
                    continue
                work.loc[mask, "timestamp"] = work.loc[mask, "timestamp"] - pd.Timedelta(hours=36)
            continue

        con.close()
        break

    return work.sort_values(["application_id", "timestamp"]).reset_index(drop=True)


def apply_inflight_stuck_share(
    df: pd.DataFrame,
    *,
    seed: int,
    share_stuck: float = 0.5,
) -> pd.DataFrame:
    """
    Shift non-terminal timelines so ~``share_stuck`` of in-flight apps land >48h before
    ``max(timestamp)`` (same clock as stuck SQL) and the rest stay fresh.
    Uses a deterministic split (sorted application_id) so the stuck share stays near the target.
    """
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    ref = pd.Timestamp(out["timestamp"].max())
    if ref.tzinfo is not None:
        ref = ref.tz_localize(None)
    non_term: list[tuple[str, pd.DataFrame]] = []
    term_pieces: list[pd.DataFrame] = []
    for aid, g in out.groupby("application_id", sort=False):
        g = g.sort_values("timestamp").reset_index(drop=True)
        last_action = str(g.iloc[-1]["action"])
        if last_action in _TERMINAL_ACTIONS:
            term_pieces.append(g)
        else:
            non_term.append((str(aid), g))

    non_term.sort(key=lambda x: x[0])
    n_if = len(non_term)
    n_stuck_tgt = int(n_if * share_stuck + 1e-12)
    stuck_ids = {a for a, _ in non_term[:n_stuck_tgt]}
    rng = random.Random(seed + 424_242)

    pieces: list[pd.DataFrame] = term_pieces.copy()
    for aid, g in non_term:
        stuck = aid in stuck_ids
        last_ts = pd.Timestamp(g.iloc[-1]["timestamp"])
        if stuck:
            target_last = ref - pd.Timedelta(hours=rng.randint(72, 420))
        else:
            target_last = ref - pd.Timedelta(hours=rng.randint(4, 44))
        shift = target_last - last_ts
        pieces.append(g.assign(timestamp=g["timestamp"] + shift))

    combined = pd.concat(pieces, ignore_index=True)
    return combined.sort_values(["application_id", "timestamp"]).reset_index(drop=True)


def apply_carryover_history_for_period_dashboard(
    df: pd.DataFrame,
    *,
    timeline_end: pd.Timestamp,
    seed: int,
    carryover_ratio: float = 0.70,
) -> pd.DataFrame:
    """
    After ``anchor_application_timelines``, many apps have *no* audit rows strictly
    before a typical reporting-window start, so ``period_start_snapshot`` collapses
    to step_order 0 for everyone.

    For a random subset of applications, split the timeline into:

    - **Prefix** — timestamps in ``[timeline_end − 98d, timeline_end − 26d]`` so
      ``timestamp::DATE < period_start`` when the UI window starts around April and
      ``timeline_end`` is late April (demo-friendly).
    - **Suffix** — timestamps from ``≈ timeline_end − 18d`` through ``timeline_end``,
      preserving chronological order, so cohorts that filter ``[Apr 4, Apr 24]``
      still see in-window activity.

    Row order and actions are unchanged (Phase 1 drift checks stay valid).
    """
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=False)
    timeline_end = pd.Timestamp(timeline_end)
    if timeline_end.tzinfo is not None:
        timeline_end = timeline_end.tz_localize(None)

    pieces: list[pd.DataFrame] = []
    for aid, g in out.groupby("application_id", sort=False):
        g = g.sort_values("timestamp").reset_index(drop=True)
        r = random.Random((seed + abs(hash(aid))) % (2**31))
        if r.random() > carryover_ratio or len(g) < 5:
            pieces.append(g)
            continue

        cut = _carryover_cut_index(g["action"].tolist())
        pre = g.iloc[:cut].copy()
        suf = g.iloc[cut:].copy()
        if len(suf) == 0:
            pieces.append(g)
            continue

        p0 = timeline_end - pd.Timedelta(days=88 + r.randint(0, 10))
        p1 = timeline_end - pd.Timedelta(days=26 + r.randint(0, 2))
        if p1 <= p0:
            p1 = p0 + pd.Timedelta(days=4)

        npre = len(pre)
        if npre == 1:
            pre.loc[pre.index[0], "timestamp"] = p1 - pd.Timedelta(days=1)
        else:
            pre["timestamp"] = pd.date_range(p0, p1, periods=npre, inclusive="both")

        gap = pd.Timedelta(hours=2 + r.randint(0, 24))
        new_first = max(pre["timestamp"].iloc[-1] + gap, timeline_end - pd.Timedelta(days=18))
        new_last = timeline_end - pd.Timedelta(
            days=r.randint(0, 12),
            hours=r.randint(2, 22),
        )
        if new_last <= new_first:
            new_last = new_first + pd.Timedelta(days=5)

        nsuf = len(suf)
        if nsuf == 1:
            suf.loc[suf.index[0], "timestamp"] = new_last
        else:
            suf["timestamp"] = pd.date_range(new_first, new_last, periods=nsuf, inclusive="both")

        pieces.append(pd.concat([pre, suf], ignore_index=True))

    return pd.concat(pieces, ignore_index=True).sort_values(
        ["application_id", "timestamp"]
    ).reset_index(drop=True)


def generate_synthetic_audit_log(
    n_applications: int = 1000,
    seed: int | None = 42,
    start_date: str = "2026-01-01",
    *,
    timeline_end: str | None = "2026-04-24T18:00:00",
    anchor_timelines: bool = True,
    apply_carryover_for_period_demo: bool = True,
    carryover_ratio: float = 0.70,
) -> pd.DataFrame:
    rng_master = random.Random(seed)
    start_base = datetime.fromisoformat(start_date)

    scenarios_weights: list[tuple[str, float]] = [
        ("success_full", 0.44),
        ("success_with_loops", 0.16),
        ("stalled_customer", 0.05),
        ("stalled_offer", 0.05),
        ("stalled_ops_compliance", 0.12),
        ("stalled_cr_review", 0.01),
        ("rejected", 0.07),
        ("cancelled_mid", 0.05),
        ("offer_refused", 0.05),
    ]

    def pick_scenario() -> str:
        r = rng_master.random()
        acc = 0.0
        for name, w in scenarios_weights:
            acc += w
            if r <= acc:
                return name
        return "success_full"

    all_rows: list[dict[str, Any]] = []
    heroes = _hero_applications(seed)
    for idx, app in enumerate(heroes[: max(0, min(len(heroes), n_applications))]):
        t0 = start_base + timedelta(days=idx * 4 + app.rng.randint(0, 2), hours=9 + app.rng.randint(0, 5))
        all_rows.extend(build_timeline(app, t0))

    for i in range(max(0, n_applications - len(heroes))):
        s = pick_scenario()
        app_rng = random.Random(rng_master.randint(0, 2**31 - 1))
        cust_local = f"customer{i}.{app_rng.randint(100, 999)}@gmail.com"
        company = f"{['BlackPearl', 'Phoenix', 'Alpine', 'Helvetia'][app_rng.randint(0, 3)]} {['Trade', 'Logistics', 'Advisory'][app_rng.randint(0, 2)]} GmbH"

        if s == "success_with_loops":
            scenario, rounds = "success_full", 2
        elif s == "stalled_customer":
            scenario, rounds = "stalled_customer", app_rng.randint(1, 2)
        elif s == "stalled_offer":
            scenario, rounds = "stalled_offer", app_rng.randint(1, 2)
        elif s == "stalled_ops_compliance":
            scenario, rounds = "stalled_ops_compliance", 1
        elif s == "stalled_cr_review":
            scenario, rounds = "stalled_cr_review", 1
        elif s == "rejected":
            scenario, rounds = "rejected", app_rng.randint(1, 1)
        elif s == "cancelled_mid":
            scenario, rounds = "cancelled_mid", 1
        elif s == "offer_refused":
            scenario, rounds = "offer_refused", app_rng.randint(1, 2)
        else:
            scenario, rounds = "success_full", app_rng.randint(1, 2)

        app = SyntheticApplication(
            application_id=str(uuid.uuid4()),
            customer_email=cust_local,
            signatory_email=f"signatory{i}@gmail.com" if app_rng.random() < 0.35 else None,
            company_name=company,
            company_uid=_che_uid(app_rng),
            assigned_cr=CR_ROSTER[i % len(CR_ROSTER)],
            assigned_compliance=COMPLIANCE_ROSTER[i % len(COMPLIANCE_ROSTER)],
            product_type=app_rng.choice(PRODUCT_TYPES),
            scenario=scenario,
            interaction_rounds=rounds,
            rng=app_rng,
        )

        offset_days = rng_master.randint(0, 110)
        offset_hours = rng_master.randint(0, 12)
        t0 = start_base + timedelta(days=offset_days, hours=offset_hours)
        all_rows.extend(build_timeline(app, t0))

    df = audit_frame(all_rows)
    df = df.sort_values(["application_id", "timestamp"]).reset_index(drop=True)
    if anchor_timelines and timeline_end and seed is not None:
        end = pd.Timestamp(timeline_end)
        df = anchor_application_timelines(df, timeline_end=end, seed=seed)
        if apply_carryover_for_period_demo:
            df = apply_carryover_history_for_period_dashboard(
                df,
                timeline_end=end,
                seed=seed,
                carryover_ratio=carryover_ratio,
            )
        # Demo-only post-steps (skip tiny synthetic runs used in unit tests).
        # CR enforcement shifts whole-app timelines and must run before BA weekly injection,
        # otherwise ISO week buckets lose terminals/customers (inject → enforce broke mins).
        repo_root = Path(__file__).resolve().parent.parent
        if df["application_id"].nunique() >= 150:
            df = enforce_cr_breach_ratio_vs_compliance(
                df,
                repo_root=repo_root,
                timeline_end=end,
                seed=int(seed),
                ratio=0.10,
            )
        df = apply_inflight_stuck_share(df, seed=int(seed) + 424_242)
        if df["application_id"].nunique() >= 150:
            df = inject_ba_weekly_floors(df, seed=int(seed) + 61_000, timeline_end=end)
    return df


def write_audit_outputs(df: pd.DataFrame, *, parquet_path: str, duckdb_csv_path: str) -> None:
    """Write Parquet (rich types) and CSV (JSON context column) for DuckDB ingestion."""
    df_parquet = df.copy()
    df_parquet.to_parquet(parquet_path, index=False)
    df_csv = df.copy()
    df_csv["context"] = df_csv["context"].apply(lambda x: json.dumps(x, ensure_ascii=False) if x else "{}")
    df_csv.to_csv(duckdb_csv_path, index=False)
