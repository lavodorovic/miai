"""
E2E (real browser) sanity check for the Streamlit Period dashboard.

Goal: catch cases where the backend data is correct but the UI keeps showing a
collapsed start snapshot (e.g. stale cached DuckDB connection, wrong DB path,
or plotting mishaps).
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http(url: str, *, timeout_s: float = 25.0) -> None:
    import urllib.request

    start = time.time()
    last_err: Exception | None = None
    while time.time() - start < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
                if 200 <= int(resp.status) < 500:
                    return
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.5)
    raise RuntimeError(f"Streamlit did not become ready at {url}: {last_err}")


@pytest.mark.e2e
def test_period_dashboard_start_snapshot_is_not_collapsed(tmp_path: Path) -> None:
    """
    Requires:
      - `data/relio_analytics.db` exists (synthetic DB ok)
      - Playwright browsers installed (`python -m playwright install chromium`)
    """
    db = ROOT / "data" / "relio_analytics.db"
    if not db.is_file():
        pytest.skip("data/relio_analytics.db missing; run scripts/generate_synthetic_audit_log.py + scripts/db_setup.py")

    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    # Streamlit config via env (avoid user/global state).
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_SERVER_PORT"] = str(port)
    env["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"
    env["RELIO_E2E_DATE_RANGE"] = "2026-04-04,2026-04-24"

    proc = subprocess.Popen(  # noqa: S603
        ["python3", "-m", "streamlit", "run", "app/main.py"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_http(base, timeout_s=35.0)

        # Browser-level assertion: the UI metric we render above the start snapshot must be > 0.
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(base, wait_until="networkidle")

            # Ensure we are on the Period dashboard tab.
            page.get_by_role("tab", name="Period dashboard").click()
            page.wait_for_timeout(500)

            # The metric label must be present and its value must not be "0".
            label = "Start snapshot — apps with prior history (step_order ≠ 0)"
            page.get_by_text(label, exact=True).wait_for(timeout=15_000)

            # Streamlit renders a metric block as data-testid="stMetric".
            metric = page.locator('div[data-testid="stMetric"]').filter(has_text=label).first
            metric.wait_for(timeout=15_000)
            value = metric.locator('[data-testid="stMetricValue"]').first.inner_text().strip()
            # Normalize commas, e.g. "730" or "1,234"
            n = int(value.replace(",", ""))
            assert n > 0, f"expected non-collapsed start snapshot metric, got {value!r}"
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

