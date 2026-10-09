from textkit import title_case


def test_title_case_basic():
    assert title_case("hello world") == "Hello World"


def test_title_case_mixed():
    assert title_case("hELLO wORLD") == "Hello World"
