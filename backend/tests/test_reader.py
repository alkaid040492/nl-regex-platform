import pytest

from apps.engine import transforms, writer
from apps.engine.reader import ResultNotFound, ResultReader

from .conftest import EMAIL_PATTERN

pytestmark = pytest.mark.spark


@pytest.fixture
def written(spark, sample_pdf, tmp_path):
    """Two source files → two Spark partitions → two Parquet files, like a real multi-partition run."""
    from apps.engine.loaders import load_csv

    src = tmp_path / "src"
    src.mkdir()
    sample_pdf.iloc[:2].to_csv(src / "part-a.csv", index=False)
    sample_pdf.iloc[2:].to_csv(src / "part-b.csv", index=False)
    df = load_csv(spark, str(src))
    assert df.rdd.getNumPartitions() == 2
    out = transforms.replace(df, ["Email"], EMAIL_PATTERN, "REDACTED")
    return writer.write_parquet(out, str(tmp_path / "result"))


def test_stats_and_columns(written):
    reader = ResultReader(written)
    stats = reader.stats()
    assert stats.total_rows == 4
    assert stats.matched_rows == 3
    assert stats.columns == ["ID", "Name", "Email", "Phone", "JoinDate"]


def test_paging_is_deterministic_and_ordered(written):
    reader = ResultReader(written)
    p1 = reader.page(1, 3, total_rows=4)
    p2 = reader.page(2, 3, total_rows=4)
    assert p1.total_pages == 2 and p2.total_pages == 2
    assert [r["ID"] for r in p1.rows] == ["1", "2", "3"]
    assert [r["ID"] for r in p2.rows] == ["4"]
    assert p1.columns == ["ID", "Name", "Email", "Phone", "JoinDate"]
    assert "_row_id" not in p1.rows[0] and p1.rows[0]["_matched"] is True
    # same call twice → same order, and order matches _row_id across the two files
    assert reader.page(1, 3).rows == p1.rows
    ids = [r["ID"] for r in reader.page(1, 50).rows]
    assert ids == ["1", "2", "3", "4"]


def test_only_matched_filter(written):
    page = ResultReader(written).page(1, 50, only_matched=True)
    assert page.total_rows == 3
    assert all(r["Email"] == "REDACTED" for r in page.rows)


def test_missing_result(tmp_path):
    with pytest.raises(ResultNotFound):
        ResultReader(str(tmp_path / "nope"))
