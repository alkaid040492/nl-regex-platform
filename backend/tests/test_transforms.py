import pytest

from apps.engine import transforms
from apps.engine.transforms import MATCHED_COLUMN, TransformError, escape_java_replacement

from .conftest import EMAIL_PATTERN

pytestmark = pytest.mark.spark


def _rows(df, *cols):
    return [tuple(r[c] for c in cols) for r in df.orderBy("_row_id").collect()]


def test_replace_masks_emails_and_flags_rows(sample_df):
    out = transforms.replace(sample_df, ["Email"], EMAIL_PATTERN, "REDACTED")
    rows = _rows(out, "Email", MATCHED_COLUMN)
    assert rows[:3] == [("REDACTED", True)] * 3
    assert rows[3] == (None, False)  # Spark reads empty CSV cells as null
    assert set(out.columns) == set(sample_df.columns) | {MATCHED_COLUMN}


def test_replace_treats_replacement_literally(sample_df):
    out = transforms.replace(sample_df, ["Email"], EMAIL_PATTERN, r"$1 \ costs $5")
    assert _rows(out, "Email")[0][0] == r"$1 \ costs $5"


def test_replace_multiple_columns(sample_df):
    out = transforms.replace(sample_df, ["Email", "Name"], r"o", "0")
    rows = _rows(out, "Name", "Email")
    assert rows[0] == ("J0hn D0e", "j0hn.d0e@example.c0m")


def test_extract_whole_match_and_group(sample_df):
    out = transforms.extract(sample_df, ["Email"], r"@([A-Za-z0-9.-]+)", "domain", group=1)
    assert [r[0] for r in _rows(out, "domain")] == ["example.com", "domain.com", "website.org", None]
    out2 = transforms.extract(sample_df, ["JoinDate"], r"\d{4}", "year")
    assert [r[0] for r in _rows(out2, "year")] == ["2024", "2023", "2024", "2022"]


def test_extract_multiple_columns_suffixes_names(sample_df):
    out = transforms.extract(sample_df, ["Email", "Name"], r"[A-Z]", "first_upper")
    assert "Email_first_upper" in out.columns and "Name_first_upper" in out.columns


def test_normalize_reorders_groups(sample_df):
    out = transforms.normalize(sample_df, ["JoinDate"], r"(\d{4})/(\d{2})/(\d{2})", "$3-$2-$1")
    assert [r[0] for r in _rows(out, "JoinDate")] == ["05-01-2024", "30-11-2023", "17-03-2024", "01-07-2022"]
    assert all(r[0] for r in _rows(out, MATCHED_COLUMN))


def test_unknown_column_raises(sample_df):
    with pytest.raises(TransformError):
        transforms.replace(sample_df, ["Nope"], "x", "y")


def test_extract_requires_name_and_no_collision(sample_df):
    with pytest.raises(TransformError):
        transforms.extract(sample_df, ["Email"], "x", "")
    with pytest.raises(TransformError):
        transforms.extract(sample_df, ["Email"], "x", "Name")


def test_escape_java_replacement():
    assert escape_java_replacement(r"$1\x") == r"\$1\\x"


def test_apply_transform_dispatch(sample_df):
    out = transforms.apply_transform(
        sample_df, transform_type="REPLACE", columns=["Email"], pattern=EMAIL_PATTERN, replacement="X"
    )
    assert _rows(out, "Email")[0][0] == "X"
    with pytest.raises(TransformError):
        transforms.apply_transform(sample_df, transform_type="NOPE", columns=["Email"], pattern="x")
