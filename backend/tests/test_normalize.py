import pytest

from ajs.domain.normalize import normalize_company, normalize_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Novo Nordisk A/S", "novo nordisk"),
        ("  Acme   ApS ", "acme"),
        ("Acme, Inc.", "acme"),
        ("Widgets Ltd", "widgets"),
        ("Widgets Limited", "widgets"),
        ("Foo Bar ApS A/S", "foo bar"),
        ("LEGO", "lego"),
        ("Basis", "basis"),
        ("Ørsted A/S", "ørsted"),
        ("Tech &  Co", "tech &"),
    ],
)
def test_normalize_company(raw: str, expected: str) -> None:
    assert normalize_company(raw) == expected


def test_normalize_company_is_idempotent() -> None:
    once = normalize_company("Novo Nordisk A/S")
    assert normalize_company(once) == once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Senior  Data Engineer", "senior data engineer"),
        ("Data Scientist (m/f/d)", "data scientist"),
        ("Data Scientist (m/k)", "data scientist"),
        ("  BI-Analytiker ", "bi-analytiker"),
        ("C++ Developer", "c++ developer"),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected
