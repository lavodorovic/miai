#!/usr/bin/env python3
"""
CLI: generate synthetic audit logs into data/.

Writes:
  - data/synthetic_audit_log.parquet (rich nested context)
  - data/synthetic_logs.csv (flat context JSON; DuckDB ingestion via scripts/db_setup.py)

Run from repo root:
  python scripts/generate_synthetic_audit_log.py
"""

from __future__ import annotations

import argparse
import os
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from synthetic_generator import generate_synthetic_audit_log, write_audit_outputs  # noqa: E402


def default_paths(repo_root: str) -> tuple[str, str, str]:
    data_dir = os.path.join(repo_root, "data")
    parquet = os.path.join(data_dir, "synthetic_audit_log.parquet")
    duckdb_csv = os.path.join(data_dir, "synthetic_logs.csv")
    return data_dir, parquet, duckdb_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic Relio audit logs.")
    parser.add_argument("--n", type=int, default=1000, help="Number of synthetic applications.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--start-date", type=str, default="2026-01-01", help="Earliest cohort date (ISO date).")
    parser.add_argument(
        "--timeline-end",
        type=str,
        default="2026-04-24T18:00:00",
        help="Anchor each app's last event in the 14 days before this (ISO datetime).",
    )
    parser.add_argument(
        "--no-timeline-anchor",
        action="store_true",
        help="Keep raw spread timestamps (last events can be months in the past).",
    )
    parser.add_argument(
        "--no-carryover",
        action="store_true",
        help="Skip pre-window prefix rewrite (period start snapshot may collapse to step 0).",
    )
    parser.add_argument(
        "--carryover-ratio",
        type=float,
        default=0.70,
        help="Fraction of apps that get pre-window history (default 0.70).",
    )
    parser.add_argument("--repo-root", type=str, default="", help="Repository root (default: parent of scripts/).")
    args = parser.parse_args()

    repo_root = args.repo_root or os.path.dirname(_SCRIPTS_DIR)
    data_dir, parquet_path, duckdb_csv = default_paths(repo_root)
    os.makedirs(data_dir, exist_ok=True)

    df = generate_synthetic_audit_log(
        n_applications=args.n,
        seed=args.seed,
        start_date=args.start_date,
        timeline_end=None if args.no_timeline_anchor else args.timeline_end,
        anchor_timelines=not args.no_timeline_anchor,
        apply_carryover_for_period_demo=not args.no_carryover,
        carryover_ratio=args.carryover_ratio,
    )
    write_audit_outputs(df, parquet_path=parquet_path, duckdb_csv_path=duckdb_csv)

    print(f"Wrote {len(df)} rows, {df['application_id'].nunique()} applications -> {parquet_path}")
    print(f"DuckDB CSV -> {duckdb_csv}")
    if args.no_carryover:
        print(
            "Note: carryover history is DISABLED (--no-carryover). "
            "Period start snapshot may collapse to step_order=0."
        )
    else:
        print(f"Carryover history enabled for period demo (ratio={args.carryover_ratio:.2f}).")


if __name__ == "__main__":
    main()
