# Deploy prototype to a public URL (Streamlit Community Cloud)

This app is wired for **[Streamlit Community Cloud](https://share.streamlit.io/)** (free). After a one-time link to GitHub, **every `git push` to your deploy branch triggers a rebuild** — no separate deploy step.

## One-time setup

1. Push this repository to GitHub (e.g. `origin` on `main`).
2. Sign in at [share.streamlit.io](https://share.streamlit.io/) with GitHub.
3. **New app** → pick the repo and branch (`main`).
4. **Main file path:** `app/main.py`
5. **Python version:** 3.11 (or match `.github/workflows/ci.yml`).
6. Deploy. Cloud installs dependencies from **`requirements.txt`** only (fast; no Playwright).

If the app is already connected to this repo, **skip the above** — only git matters from here.

**Where is the URL?** In Streamlit Cloud: workspace → your app → open the link (typically `https://*.streamlit.app`). That URL updates when the deploy finishes after each push.

Example (this prototype): `https://opsintel.streamlit.app`

The first boot may take a minute while it generates demo DuckDB from `RELIO_SKIP_BOOTSTRAP` logic in `app/main.py` if the DB file is missing.

## Ongoing workflow

```bash
git add -A && git commit -m "Your change" && git push origin main
```

Streamlit Cloud watches the branch and redeploys automatically (typically within a few minutes).

## Optional secrets

In the Cloud app **Settings → Secrets**, you can add a `[bootstrap]` block (see `app/main.py`) to tune synthetic data on first boot.

## Troubleshooting

- **Import errors:** Ensure `requirements.txt` includes all runtime imports (not dev-only tools).
- **Wrong UI version:** Hard-refresh the Cloud URL; check the `UI build-…` caption under the title matches your latest `BUILD_TAG` in `app/main.py`.
