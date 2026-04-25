"""Apply ordered DDL from analytics/ddl/ (views after audit_logs exist)."""

from __future__ import annotations

from pathlib import Path


def apply_ddl(con, repo_root: Path) -> None:
    ddl_dir = repo_root / "analytics" / "ddl"
    if not ddl_dir.is_dir():
        return
    for path in sorted(ddl_dir.glob("*.sql")):
        con.execute(path.read_text(encoding="utf-8"))
