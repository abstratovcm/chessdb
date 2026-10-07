"""db/query.py only builds SQL strings, so these run without duckdb."""

from pathlib import Path

import pytest

from chessdb.db.export import ExportError, ExportSpec, MetricFilters, build_export_query
from chessdb.db.query import (
    QuerySpec,
    build_count_query,
    build_distribution_null_count_query,
    build_distribution_query,
    build_position_page_query,
)


def _spec(limit=100, offset=0, order_by=None, descending=False, **filter_overrides):
    filter_overrides.setdefault("metric_version", 1)
    return QuerySpec(
        filters=MetricFilters(**filter_overrides),
        limit=limit,
        offset=offset,
        order_by=order_by,
        descending=descending,
    )


def _where_clause(query):
    return query.rsplit("\nWHERE ", 1)[1].split("\nORDER BY")[0]


def test_page_query_where_matches_export_query_where():
    filters = MetricFilters(
        metric_version=1, engine_id=3, min_sign_flips=2, min_top_rung=64_000
    )
    page_query, _ = build_position_page_query(QuerySpec(filters=filters, limit=10))
    export_query, _ = build_export_query(
        ExportSpec(
            db=Path("x.db"),
            out=Path("out.parquet"),
            force=False,
            column_groups=("core",),
            filters=filters,
        )
    )
    assert _where_clause(page_query) == _where_clause(export_query)


def test_page_query_limit_offset_after_order_by():
    query, _ = build_position_page_query(_spec(limit=25, offset=50))
    assert "ORDER BY" in query
    assert query.rstrip().endswith("LIMIT 25 OFFSET 50")
    assert query.index("ORDER BY") < query.index("LIMIT 25")


def test_page_query_grain_columns_present():
    _query, columns = build_position_page_query(_spec())
    assert columns[:2] == ("position_id", "epd")
    assert "metric_version" in columns


def test_count_query_has_same_where_as_page_query():
    spec = _spec(engine_id=5, min_cp_range=100)
    page_query, _ = build_position_page_query(spec)
    count_query = build_count_query(spec)
    assert _where_clause(page_query) == _where_clause(count_query)


def test_count_query_has_no_limit_or_offset():
    query = build_count_query(_spec(limit=10, offset=5))
    assert "LIMIT" not in query
    assert "OFFSET" not in query


def test_generated_sql_has_no_spliced_user_strings():
    spec = _spec(engine_id=7, min_sign_flips=1, min_cp_range=1, max_settle_dev=1)
    page_query, _ = build_position_page_query(spec)
    count_query = build_count_query(spec)
    assert "'" not in page_query
    assert "'" not in count_query


def test_non_int_filter_value_rejected():
    with pytest.raises(TypeError):
        build_position_page_query(_spec(engine_id="1 OR 1=1"))


def test_order_by_column_leads_with_tiebreakers_following():
    query, _ = build_position_page_query(_spec(order_by="sign_flips"))
    order_clause = query.split("ORDER BY ")[1].split("\nLIMIT")[0]
    assert order_clause == "pm.sign_flips ASC, p.id, pm.engine_id, pm.metric_version"


def test_order_by_descending_flips_direction():
    query, _ = build_position_page_query(
        _spec(order_by="version_disagreement", descending=True)
    )
    order_clause = query.split("ORDER BY ")[1].split("\nLIMIT")[0]
    assert order_clause.startswith("pm.version_disagreement DESC, ")


def test_order_by_none_keeps_original_tiebreaker_only_order():
    query, _ = build_position_page_query(_spec())
    order_clause = query.split("ORDER BY ")[1].split("\nLIMIT")[0]
    assert order_clause == "p.id, pm.engine_id, pm.metric_version"


def test_order_by_mate_found_rung_is_whitelisted():
    query, _ = build_position_page_query(_spec(order_by="mate_found_rung"))
    order_clause = query.split("ORDER BY ")[1].split("\nLIMIT")[0]
    assert order_clause.startswith("pm.mate_found_rung ASC, ")


def test_order_by_unknown_column_raises_export_error():
    with pytest.raises(ExportError, match="unknown order_by column"):
        build_position_page_query(_spec(order_by="bogus"))


def test_distribution_query_bucket_expression_and_where():
    query = build_distribution_query("cp_range", metric_version=1, width=50)
    assert "SELECT (pm.cp_range // 50) * 50 AS start, COUNT(*) AS count" in query
    assert "pm.metric_version = 1" in query
    assert "pm.cp_range IS NOT NULL" in query
    assert "GROUP BY 1" in query
    assert "ORDER BY 1" in query


def test_distribution_query_width_zero_rejected():
    with pytest.raises(ExportError, match="width"):
        build_distribution_query("cp_range", metric_version=1, width=0)


def test_distribution_query_negative_width_rejected():
    with pytest.raises(ExportError, match="width"):
        build_distribution_query("cp_range", metric_version=1, width=-1)


def test_distribution_query_engine_filter_composes_with_and():
    query = build_distribution_query(
        "sign_flips", metric_version=2, width=1, engine_id=9
    )
    where_clause = query.split("WHERE ")[1].split("\nGROUP BY")[0]
    assert "pm.metric_version = 2" in where_clause
    assert "pm.engine_id = 9" in where_clause
    assert where_clause.count(" AND ") == 2


def test_distribution_unknown_metric_raises_export_error():
    with pytest.raises(ExportError, match="unknown metric"):
        build_distribution_query("bogus", metric_version=1, width=1)


def test_distribution_null_count_query_excludes_non_null():
    query = build_distribution_null_count_query("settle_dev", metric_version=1)
    assert "pm.settle_dev IS NULL" in query
    assert "COUNT(pm.position_id)" in query


def test_distribution_null_count_unknown_metric_raises_export_error():
    with pytest.raises(ExportError, match="unknown metric"):
        build_distribution_null_count_query("bogus", metric_version=1)
