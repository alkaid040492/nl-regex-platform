"""
Page through a Parquet result with DuckDB.

Why not Spark? Serving a page is a latency-sensitive request in the web process, where
there is no SparkSession and starting one would take seconds. DuckDB reads Parquet
directly, pushes the projection/limit down to the row groups and answers in milliseconds,
even for tens of millions of rows.

Ordering: Spark writes one Parquet file per partition (part-00000, part-00001, ...) and
`monotonically_increasing_id` is increasing within and across partitions in that same
order. DuckDB scans the sorted file list with `preserve_insertion_order = true`, so
`LIMIT/OFFSET` without an ORDER BY is deterministic and identical to ordering by `_row_id`
— but avoids sorting millions of rows for every deep page (which took seconds).
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

import duckdb

from .loaders import ROW_ID_COLUMN
from .transforms import MATCHED_COLUMN

INTERNAL_COLUMNS = (ROW_ID_COLUMN, MATCHED_COLUMN)


class ResultNotFound(FileNotFoundError):
    pass


@dataclass(frozen=True)
class ResultPage:
    columns: list[str]
    rows: list[dict]
    page: int
    page_size: int
    total_rows: int
    total_pages: int


@dataclass(frozen=True)
class ResultStats:
    total_rows: int
    matched_rows: int
    columns: list[str]


class ResultReader:
    def __init__(self, path: str):
        if not os.path.isdir(path) or not glob.glob(os.path.join(path, "*.parquet")):
            raise ResultNotFound(f"No parquet result at {path}")
        self._glob = os.path.join(path, "*.parquet").replace("\\", "/")

    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(database=":memory:")
        con.execute("SET threads TO 2")
        con.execute("SET preserve_insertion_order = true")
        return con

    def columns(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{self._glob}')").fetchall()
        return [r[0] for r in rows if r[0] not in INTERNAL_COLUMNS]

    def stats(self) -> ResultStats:
        with self._connect() as con:
            total, matched = con.execute(
                f"SELECT count(*), coalesce(sum(CASE WHEN {MATCHED_COLUMN} THEN 1 ELSE 0 END), 0) "
                f"FROM read_parquet('{self._glob}')"
            ).fetchone()
        return ResultStats(total_rows=int(total), matched_rows=int(matched), columns=self.columns())

    def page(self, page: int, page_size: int, *, only_matched: bool = False, total_rows: int | None = None) -> ResultPage:
        page = max(page, 1)
        offset = (page - 1) * page_size
        where = f"WHERE {MATCHED_COLUMN}" if only_matched else ""
        with self._connect() as con:
            if total_rows is None or only_matched:
                total_rows = int(con.execute(f"SELECT count(*) FROM read_parquet('{self._glob}') {where}").fetchone()[0])
            cur = con.execute(
                f"SELECT * FROM read_parquet('{self._glob}') {where} LIMIT {int(page_size)} OFFSET {int(offset)}"
            )
            names = [d[0] for d in cur.description]
            data = cur.fetchall()

        visible = [n for n in names if n != ROW_ID_COLUMN]
        rows = [{n: v for n, v in zip(names, r) if n != ROW_ID_COLUMN} for r in data]
        total_pages = max(1, -(-total_rows // page_size))
        return ResultPage(
            columns=[c for c in visible if c != MATCHED_COLUMN],
            rows=rows,
            page=page,
            page_size=page_size,
            total_rows=total_rows,
            total_pages=total_pages,
        )
