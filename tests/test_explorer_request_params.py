from podcast_network.web.explorer.request_params import (
    parse_date_filter,
    parse_int,
    parse_int_list,
    parse_string_list,
)


def test_parse_int_returns_none_for_missing_or_invalid_values() -> None:
    assert parse_int(None) is None
    assert parse_int("") is None
    assert parse_int("abc") is None
    assert parse_int("42") == 42


def test_parse_list_params_preserve_order_and_drop_duplicates() -> None:
    assert parse_int_list(["3", "bad", "3", "4"]) == [3, 4]
    assert parse_string_list([" comedy ", "", "news", "comedy"]) == ["comedy", "news"]


def test_parse_date_filter_accepts_iso_dates_only() -> None:
    assert parse_date_filter("2024-02-03") == "2024-02-03"
    assert parse_date_filter("2024-02-03T10:20:30") == "2024-02-03"
    assert parse_date_filter("not-a-date") is None
