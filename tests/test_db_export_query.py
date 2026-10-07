"""build_export_query only builds SQL strings, so these run without duckdb."""

from pathlib import Path

import pytest

from chessdb.db.export import ExportError, ExportSpec, MetricFilters, build_export_query

_FILTER_FIELDS = (
    "metric_version",
    "engine_id",
    "min_sign_flips",
    "min_cp_range",
    "max_settle_dev",
    "min_top_rung",
    "has_mate",
    "min_mate_found_rung",
)


def _spec(**overrides):
    defaults = {
        "db": Path("x.db"),
        "out": Path("out.parquet"),
        "force": False,
        "column_groups": ("core",),
        "metric_version": 1,
    }
    defaults.update(overrides)
    filter_kwargs = {k: defaults.pop(k) for k in _FILTER_FIELDS if k in defaults}
    return ExportSpec(filters=MetricFilters(**filter_kwargs), **defaults)


def _main_where_clause(query):
    # the outer filter is the WHERE right before ORDER BY, not the pivot CTE's
    return query.rsplit("\nWHERE ", 1)[1].split("\nORDER BY")[0]


def test_default_filter_is_just_metric_version():
    query, _ = build_export_query(_spec())
    assert "WHERE pm.metric_version = 1" in query
    assert " AND " not in _main_where_clause(query)


def test_filters_compose_with_and():
    query, _ = build_export_query(
        _spec(
            engine_id=3,
            min_sign_flips=2,
            min_cp_range=100,
            max_settle_dev=50,
            min_top_rung=64_000,
            has_mate=1,
            min_mate_found_rung=4_000,
        )
    )
    where_clause = _main_where_clause(query)
    for expected in (
        "pm.metric_version = 1",
        "pm.engine_id = 3",
        "pm.sign_flips >= 2",
        "pm.cp_range >= 100",
        "pm.settle_dev <= 50",
        "pm.top_rung >= 64000",
        "pm.mate_found_rung IS NOT NULL",
        "pm.mate_found_rung >= 4000",
    ):
        assert expected in where_clause
    assert where_clause.count(" AND ") == 7


def test_has_mate_zero_means_is_null():
    query, _ = build_export_query(_spec(has_mate=0))
    assert "pm.mate_found_rung IS NULL" in _main_where_clause(query)


def test_has_mate_invalid_value_raises_export_error():
    with pytest.raises(ExportError, match="has_mate must be 0 or 1"):
        build_export_query(_spec(has_mate=2))


def test_limit_appended_after_order_by():
    query, _ = build_export_query(_spec(limit=10))
    assert query.rstrip().endswith("LIMIT 10")
    assert query.index("ORDER BY") < query.index("LIMIT 10")


def test_no_limit_means_no_limit_clause():
    query, _ = build_export_query(_spec())
    assert "LIMIT" not in query


def test_generated_sql_has_no_spliced_user_strings():
    # filters are validated ints, never quoted user strings
    query, _ = build_export_query(
        _spec(engine_id=7, min_sign_flips=1, min_cp_range=1, max_settle_dev=1)
    )
    assert "'" not in query


def test_unknown_column_group_raises_export_error_without_duckdb():
    with pytest.raises(ExportError, match="unknown --columns group"):
        build_export_query(_spec(column_groups=("bogus",)))


def test_grain_columns_always_present_regardless_of_groups():
    _query, columns = build_export_query(_spec(column_groups=("raw",)))
    assert columns[:3] == ("position_id", "engine_id", "metric_version")
    assert "score_kind_1000" in columns


def test_non_int_filter_value_rejected():
    with pytest.raises(TypeError):
        build_export_query(_spec(engine_id="1 OR 1=1"))
