#!/usr/bin/env python3
"""
Initialize DuckDB analytical store under data/relio_analytics.db.

Loads CSV exported for DuckDB (default: data/synthetic_logs.csv) into table audit_logs.
All paths are resolved relative to the repository root (parent of scripts/).

Typical flow:
  python scripts/generate_synthetic_audit_log.py
  python scripts/db_setup.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Load audit CSV into DuckDB (data/relio_analytics.db).")
    parser.add_argument(
        "--repo-root",
        type=str,
        default="",
        help="Repository root (default: inferred from script location).",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default="",
        help="Relative path to CSV under repo root (default: data/synthetic_logs.csv).",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="",
        help="Relative path to DuckDB file under repo root (default: data/relio_analytics.db).",
    )
    args = parser.parse_args()

    root = _repo_root(args.repo_root or None)
    csv_rel = Path(args.csv) if args.csv else Path("data") / "synthetic_logs.csv"
    db_rel = Path(args.db) if args.db else Path("data") / "relio_analytics.db"

    csv_path = (root / csv_rel).resolve()
    db_path = (root / db_rel).resolve()

    if not csv_path.is_file():
        print(f"Missing CSV: {csv_path}", file=sys.stderr)
        print("Generate it with: python scripts/generate_synthetic_audit_log.py", file=sys.stderr)
        sys.exit(1)

    db_path.parent.mkdir(parents=True, exist_ok=True)

    import duckdb

    from analytics.ddl_loader import apply_ddl

    con = duckdb.connect(str(db_path))
    try:
        con.execute("DROP VIEW IF EXISTS v_transitions;")
        con.execute("DROP VIEW IF EXISTS v_audit_staged;")
        con.execute("DROP TABLE IF EXISTS audit_logs;")
        con.execute(
            """
            CREATE TABLE audit_logs AS
            SELECT * FROM read_csv_auto(?, header = true)
            """,
            [str(csv_path)],
        )
        n = con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        print(f"Loaded {n} rows into audit_logs -> {db_path}")
        apply_ddl(con, root)
        print("Applied analytics/ddl views (v_audit_staged, v_transitions).")
    finally:
        con.close()

    # Mirror app/main.py bootstrap stamp so Cloud rebuilds when synth pipeline changes.
    try:
        sys.path.insert(0, str((root / "app").resolve()))
        from app.main import DATA_TAG  # type: ignore[import-not-found]

        (db_path.parent / ".bootstrap_tag").write_text(DATA_TAG, encoding="utf-8")
        print(f"Stamped bootstrap tag: {DATA_TAG}")
    except Exception as e:  # noqa: BLE001
        print(f"(skipped bootstrap tag stamp: {e})")


if __name__ == "__main__":
    main()
