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
def test_bottleneck_radar_renders_table() -> None:
    db = ROOT / "data" / "relio_analytics.db"
    if not db.is_file():
        pytest.skip("data/relio_analytics.db missing; run scripts/generate_synthetic_audit_log.py + scripts/db_setup.py")

    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
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

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(base, wait_until="networkidle")
            page.get_by_role("tab", name="Bnk").click()
            page.wait_for_timeout(700)

            # Ensure we are on the Bottleneck radar tab (tab click succeeded).
            page.get_by_role("heading", name="Bottleneck").first.wait_for(timeout=15_000)
            # Table container should be attached (may be inside a scrollable region in headless mode).
            page.locator('div[data-testid="stDataFrame"]').first.wait_for(state="attached", timeout=15_000)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

