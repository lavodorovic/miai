"""
Load SQL from analytics/queries/, inject filters, run on DuckDB, return pandas.

Placeholders
------------
``{{PRODUCT_TYPE_FILTER}}``
    ``TRUE`` when unfiltered; else ``product_type = '…'`` (escaped).

``{{APP_ID_FILTER}}``
    ``application_id = '…'`` when an ID is provided; else ``FALSE`` (returns no rows).
    Use in drill-down queries only.

``{{DATE_RANGE_FILTER}}``
    ``TRUE`` when unset; else ``timestamp::DATE BETWEEN DATE '…' AND DATE '…'``.

``{{PERIOD_START_DATE}}`` / ``{{PERIOD_END_DATE}}``
    Literal ``DATE 'YYYY-MM-DD'`` bounds derived from the same ``date_range`` tuple.
    Required whenever these placeholders appear (raises if ``date_range`` is unset).

``{{AS_OF_DATE}}``
    Literal ``DATE '…'`` from ``run(..., as_of_date='YYYY-MM-DD')`` when the placeholder is present.

``{{ANCHOR_TS}}``
    Qualified column reference (e.g. ``anchors.anchor_submitted``) from ``anchor_kind`` in
    ``run(..., anchor_kind='submitted'|'enrollment'|'assigned'|'compliance')``.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import duckdb

FILTER_PLACEHOLDER = "{{PRODUCT_TYPE_FILTER}}"
APP_ID_PLACEHOLDER = "{{APP_ID_FILTER}}"
DATE_RANGE_PLACEHOLDER = "{{DATE_RANGE_FILTER}}"
PERIOD_START_PLACEHOLDER = "{{PERIOD_START_DATE}}"
PERIOD_END_PLACEHOLDER = "{{PERIOD_END_DATE}}"
AS_OF_DATE_PLACEHOLDER = "{{AS_OF_DATE}}"
ANCHOR_TS_PLACEHOLDER = "{{ANCHOR_TS}}"
_QUERIES_DIR = Path(__file__).resolve().parent / "queries"

_ANCHOR_TS_SQL: dict[str, str] = {
    "submitted": "anchors.anchor_submitted",
    "enrollment": "anchors.anchor_enrollment",
    "assigned": "anchors.anchor_assigned",
    "compliance": "anchors.anchor_compliance",
}


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _product_type_predicate(product_type: str | None) -> str:
    if product_type is None:
        return "TRUE"
    s = str(product_type).strip()
    if not s or s == "(All)":
        return "TRUE"
    return f"product_type = {_sql_string_literal(s)}"


def _app_id_predicate(application_id: str | None) -> str:
    if application_id is None:
        return "FALSE"
    s = str(application_id).strip()
    if not s:
        return "FALSE"
    return f"application_id = {_sql_string_literal(s)}"


def _date_range_predicate(date_range: tuple[str, str] | None) -> str:
    if not date_range or len(date_range) != 2:
        return "TRUE"
    start, end = (str(date_range[0])[:10], str(date_range[1])[:10])
    return (
        "(timestamp::DATE BETWEEN DATE "
        f"{_sql_string_literal(start)} AND DATE {_sql_string_literal(end)})"
    )


def _inject_product_filter(sql: str, product_type: str | None) -> str:
    predicate = _product_type_predicate(product_type)
    if FILTER_PLACEHOLDER in sql:
        return sql.replace(FILTER_PLACEHOLDER, predicate)
    warnings.warn(
        f"SQL does not contain {FILTER_PLACEHOLDER!r}; product_type filter was not applied.",
        stacklevel=2,
    )
    return sql


def _inject_app_id_filter(sql: str, application_id: str | None) -> str:
    if APP_ID_PLACEHOLDER not in sql:
        return sql
    return sql.replace(APP_ID_PLACEHOLDER, _app_id_predicate(application_id))


def _inject_date_range_filter(sql: str, date_range: tuple[str, str] | None) -> str:
    if DATE_RANGE_PLACEHOLDER not in sql:
        return sql
    return sql.replace(DATE_RANGE_PLACEHOLDER, _date_range_predicate(date_range))


def _inject_period_date_literals(sql: str, date_range: tuple[str, str] | None) -> str:
    if PERIOD_START_PLACEHOLDER not in sql and PERIOD_END_PLACEHOLDER not in sql:
        return sql
    if not date_range or len(date_range) != 2:
        raise ValueError(
            "Queries using {{PERIOD_START_DATE}} or {{PERIOD_END_DATE}} require "
            "date_range=(start_iso, end_iso)."
        )
    start, end = (str(date_range[0])[:10], str(date_range[1])[:10])
    start_lit = f"DATE {_sql_string_literal(start)}"
    end_lit = f"DATE {_sql_string_literal(end)}"
    return (
        sql.replace(PERIOD_START_PLACEHOLDER, start_lit).replace(PERIOD_END_PLACEHOLDER, end_lit)
    )


def _inject_as_of_date(sql: str, as_of_date: str | None) -> str:
    if AS_OF_DATE_PLACEHOLDER not in sql:
        return sql
    if not as_of_date or not str(as_of_date).strip():
        raise ValueError("Queries using {{AS_OF_DATE}} require as_of_date='YYYY-MM-DD'.")
    d = str(as_of_date).strip()[:10]
    return sql.replace(AS_OF_DATE_PLACEHOLDER, f"DATE {_sql_string_literal(d)}")


def _inject_anchor_ts(sql: str, anchor_kind: str | None) -> str:
    if ANCHOR_TS_PLACEHOLDER not in sql:
        return sql
    if not anchor_kind or anchor_kind not in _ANCHOR_TS_SQL:
        raise ValueError(
            "Queries using {{ANCHOR_TS}} require anchor_kind in "
            f"{sorted(_ANCHOR_TS_SQL)!r}."
        )
    return sql.replace(ANCHOR_TS_PLACEHOLDER, _ANCHOR_TS_SQL[anchor_kind])


def _inject_all(
    sql: str,
    *,
    product_type: str | None,
    application_id: str | None,
    date_range: tuple[str, str] | None,
    as_of_date: str | None = None,
    anchor_kind: str | None = None,
) -> str:
    sql = _inject_app_id_filter(sql, application_id)
    sql = _inject_product_filter(sql, product_type)
    sql = _inject_date_range_filter(sql, date_range)
    sql = _inject_period_date_literals(sql, date_range)
    sql = _inject_as_of_date(sql, as_of_date)
    sql = _inject_anchor_ts(sql, anchor_kind)
    return sql


class QueryManager:
    """
    Discover and run ``.sql`` files under ``analytics/queries/`` against a DuckDB connection.
    """

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        queries_dir: Path | None = None,
    ) -> None:
        self._con = connection
        self._queries_dir = Path(queries_dir) if queries_dir is not None else _QUERIES_DIR

    @property
    def queries_dir(self) -> Path:
        return self._queries_dir

    def list_queries(self) -> list[str]:
        """Basenames of ``*.sql`` files (without ``.sql``), sorted."""
        return sorted(p.stem for p in self._queries_dir.glob("*.sql"))

    def load_sql(self, name: str) -> str:
        """Load raw SQL text for ``name`` (stem, e.g. ``event_counts``)."""
        path = self._queries_dir / f"{name}.sql"
        if not path.is_file():
            raise FileNotFoundError(f"No query file: {path}")
        return path.read_text(encoding="utf-8")

    def render(
        self,
        name: str,
        *,
        product_type: str | None = None,
        application_id: str | None = None,
        date_range: tuple[str, str] | None = None,
        as_of_date: str | None = None,
        anchor_kind: str | None = None,
    ) -> str:
        """Load query ``name`` and substitute placeholders."""
        return _inject_all(
            self.load_sql(name),
            product_type=product_type,
            application_id=application_id,
            date_range=date_range,
            as_of_date=as_of_date,
            anchor_kind=anchor_kind,
        )

    def run(
        self,
        name: str,
        *,
        product_type: str | None = None,
        application_id: str | None = None,
        date_range: tuple[str, str] | None = None,
        as_of_date: str | None = None,
        anchor_kind: str | None = None,
    ) -> pd.DataFrame:
        """Execute named query after placeholder substitution."""
        sql = self.render(
            name,
            product_type=product_type,
            application_id=application_id,
            date_range=date_range,
            as_of_date=as_of_date,
            anchor_kind=anchor_kind,
        )
        return self._con.execute(sql).df()

    def run_sql(
        self,
        sql: str,
        *,
        product_type: str | None = None,
        application_id: str | None = None,
        date_range: tuple[str, str] | None = None,
        as_of_date: str | None = None,
        anchor_kind: str | None = None,
    ) -> pd.DataFrame:
        """Execute arbitrary SQL with the same placeholder substitution."""
        return self._con.execute(
            _inject_all(
                sql,
                product_type=product_type,
                application_id=application_id,
                date_range=date_range,
                as_of_date=as_of_date,
                anchor_kind=anchor_kind,
            )
        ).df()
