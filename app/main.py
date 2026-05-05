"""
Relio Operations Intelligence — Streamlit dashboard (DuckDB + QueryManager).

Run from repository root:
  streamlit run app/main.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics.query_manager import QueryManager  # noqa: E402
from app.tabs import sections  # noqa: E402
from app.tabs.shared import (  # noqa: E402
    pct_delta,
    previous_date_range,
    render_sidebar_client_filters,
)

DEFAULT_DB = PROJECT_ROOT / "data" / "relio_analytics.db"
BUILD_TAG = "build-2026-04-27-arrivals-chart"

# Tighten layout on phones / narrow viewports (Streamlit + embedded chart iframes).
_MOBILE_VIEWPORT_CSS = """
<style>
@media (max-width: 900px) {
  .stApp .main .block-container {
    padding-left: max(0.45rem, env(safe-area-inset-left, 0px)) !important;
    padding-right: max(0.45rem, env(safe-area-inset-right, 0px)) !important;
    padding-top: 0.45rem !important;
    padding-bottom: env(safe-area-inset-bottom, 0px) !important;
    max-width: 100% !important;
  }
  .stApp h1 { font-size: 1.2rem !important; line-height: 1.25 !important; }
  .stApp h2 { font-size: 1.05rem !important; }
  .stApp h3 { font-size: 1rem !important; }
  /* Let multi-column rows shrink instead of forcing horizontal scroll */
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    min-width: 0 !important;
  }
  /* ECharts / other embedded chart iframes: fill column width */
  div[data-testid="stElementContainer"] iframe {
    width: 100% !important;
    max-width: 100% !important;
  }
}
@media (max-width: 900px) and (pointer: coarse) {
  /* Sidebar controls: slightly easier to tap */
  section[data-testid="stSidebar"] .stSelectbox label,
  section[data-testid="stSidebar"] .stSlider label {
    font-size: 0.95rem;
  }
}
</style>
"""


def _connect_readonly(db_path: Path, *, db_mtime_ns: int) -> duckdb.DuckDBPyConnection:
    if not db_path.is_file():
        raise FileNotFoundError(
            f"Database not found: {db_path}. Run: python scripts/db_setup.py"
        )
    return duckdb.connect(str(db_path), read_only=True)


def _bootstrap_demo_duckdb(*, repo_root: Path, db_path: Path) -> None:
    """
    Streamlit Cloud / fresh clones often ship without data/relio_analytics.db (gitignored).
    Generate a small synthetic dataset + build DuckDB locally on first boot.

    Optional Streamlit secrets (toml):
      [bootstrap]
      n_applications = 1000
      seed = 42
      start_date = "2026-01-01"
      timeline_end = "2026-04-24T18:00:00"
      no_timeline_anchor = false
      no_carryover = false
      carryover_ratio = 0.70
    """
    if os.environ.get("RELIO_SKIP_BOOTSTRAP", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        return

    csv_path = (repo_root / "data" / "synthetic_logs.csv").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    cfg: dict[str, object] = {}
    try:
        cfg = dict(st.secrets.get("bootstrap", {}))  # type: ignore[arg-type]
    except Exception:
        cfg = {}

    n_apps = int(cfg.get("n_applications", 1000))
    seed = int(cfg.get("seed", 42))
    start_date = str(cfg.get("start_date", "2026-01-01"))
    timeline_end = str(cfg.get("timeline_end", "2026-04-24T18:00:00"))
    no_timeline_anchor = bool(cfg.get("no_timeline_anchor", False))
    no_carryover = bool(cfg.get("no_carryover", False))
    carryover_ratio = float(cfg.get("carryover_ratio", 0.70))

    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from synthetic_generator import generate_synthetic_audit_log, write_audit_outputs  # noqa: WPS433

    df = generate_synthetic_audit_log(
        n_applications=n_apps,
        seed=seed,
        start_date=start_date,
        timeline_end=None if no_timeline_anchor else timeline_end,
        anchor_timelines=not no_timeline_anchor,
        apply_carryover_for_period_demo=not no_carryover,
        carryover_ratio=carryover_ratio,
    )
    parquet_path = (repo_root / "data" / "synthetic_audit_log.parquet").resolve()
    write_audit_outputs(df, parquet_path=str(parquet_path), duckdb_csv_path=str(csv_path))

    from analytics.ddl_loader import apply_ddl  # noqa: WPS433

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
        apply_ddl(con, repo_root)
    finally:
        con.close()


def _sidebar_product_options(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.sql("SELECT DISTINCT product_type FROM audit_logs ORDER BY 1").fetchall()
    return ["(All)"] + [r[0] for r in rows if r[0]]


def _sidebar_date_bounds(con: duckdb.DuckDBPyConnection) -> tuple:
    return con.sql(
        "SELECT min(timestamp)::DATE, max(timestamp)::DATE FROM audit_logs"
    ).fetchone()


def _parse_product_filter(choice: str) -> str | None:
    return None if choice == "(All)" else choice



def main() -> None:
    st.set_page_config(
        page_title="Relio Operations Intelligence",
        layout="wide",
        # Narrow viewports: sidebar starts hidden; desktop starts expanded (Streamlit default behavior).
        initial_sidebar_state="auto",
        menu_items={
            "Get help": None,
            "Report a bug": None,
            "About": "# Relio ops\nInternal analytics demo.",
        },
    )
    st.markdown(_MOBILE_VIEWPORT_CSS, unsafe_allow_html=True)
    st.title("Relio Ops Intelligence")
    st.caption(f"UI {BUILD_TAG}")

    _PAGE_LABELS = [
        "Overview",
        "Period",
        "Bottleneck",
        "Rework",
        "Team",
        "SLA",
        "Capacity",
        "Cohort",
        "Investigate",
    ]
    nav = st.radio(
        "Navigate",
        _PAGE_LABELS,
        horizontal=True,
        label_visibility="collapsed",
        key="main_nav_page",
    )
    overview_mode = nav == "Overview"

    db_rel = st.sidebar.text_input(
        "DuckDB path (relative to project)",
        value="data/relio_analytics.db",
    )
    db_path = Path(db_rel)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    if not db_path.is_file():
        try:
            with st.spinner("First boot: generating demo dataset + DuckDB (may take ~30–90s on Cloud)…"):
                _bootstrap_demo_duckdb(repo_root=PROJECT_ROOT, db_path=db_path)
            st.success(f"Created demo database at `{db_path}`")
        except Exception as e:  # noqa: BLE001
            st.error(
                "Could not auto-create the DuckDB file. "
                "For local dev, run `python3 scripts/generate_synthetic_audit_log.py` then `python3 scripts/db_setup.py`."
            )
            st.exception(e)
            st.stop()

    db_mtime_ns = db_path.stat().st_mtime_ns if db_path.exists() else 0
    try:
        con = _connect_readonly(db_path, db_mtime_ns=db_mtime_ns)
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    qm = QueryManager(con)

    min_d, max_d = _sidebar_date_bounds(con)

    with st.sidebar:
        if overview_mode:
            st.caption("Overview uses all products and the full audit date range (no filters here).")
        else:
            st.header("Filters")
            product_choices = _sidebar_product_options(con)
            product_choice = st.selectbox("Product type", product_choices, key="sidebar_product_type")
            e2e_dr = os.environ.get("RELIO_E2E_DATE_RANGE", "").strip()
            if e2e_dr and "," in e2e_dr:
                try:
                    a, b = [s.strip() for s in e2e_dr.split(",", 1)]
                    default_dr = (pd.to_datetime(a).date(), pd.to_datetime(b).date())
                except Exception:  # noqa: BLE001
                    default_dr = (min_d, max_d)
            else:
                lookback_days = 21
                try:
                    start_d = max(min_d, (pd.to_datetime(max_d) - pd.Timedelta(days=lookback_days)).date())
                except Exception:  # noqa: BLE001
                    start_d = min_d
                default_dr = (start_d, max_d)
            dr = st.date_input(
                "Date range",
                value=default_dr,
                min_value=min_d,
                max_value=max_d,
            )
            if isinstance(dr, tuple) and len(dr) == 2:
                date_range = (str(dr[0]), str(dr[1]))
            elif hasattr(dr, "isoformat"):
                ds = dr.isoformat()[:10]
                date_range = (ds, ds)
            else:
                date_range = None
            product_filter = _parse_product_filter(product_choice)

    if overview_mode:
        date_range = (str(min_d), str(max_d))
        product_filter = None
        product_choice = "(All)"

    ui_filters = render_sidebar_client_filters(enabled=not overview_mode)

    if nav == "Overview":
        sections.run_overview(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )
    elif nav == "Period":
        sections.run_period(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )
    elif nav == "Bottleneck":
        sections.run_bottleneck(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )
    elif nav == "Rework":
        sections.run_rework(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )
    elif nav == "Team":
        sections.run_team(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )
    elif nav == "SLA":
        sections.run_sla(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )
    elif nav == "Capacity":
        sections.run_capacity(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )
    elif nav == "Cohort":
        sections.run_cohort(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )
    elif nav == "Investigate":
        sections.run_investigate(
            qm=qm,
            product_filter=product_filter,
            date_range=date_range,
            min_d=min_d,
            max_d=max_d,
            product_choice=product_choice,
            ui_filters=ui_filters,
        )

if __name__ == "__main__":
    main()
