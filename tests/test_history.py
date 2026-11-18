"""The gap history file: what a run records and what is left alone."""

from datetime import date

import requests

from layerkit import history

FIELDS = ("missing", "matched")
SUMMARY = {"missing": 7, "matched": 3, "osm_date": "2026-09-28 22:03Z",
           "osm_stale": False}


def record(path, summary=SUMMARY, **kw):
    return history.record(summary, FIELDS, path=str(path), seed=lambda: False, **kw)


def test_a_live_run_appends_one_row_with_the_counts(tmp_path):
    path = tmp_path / "data" / "history.jsonl"
    record(path, day="2026-09-28")
    assert history.load(str(path)) == [
        {"date": "2026-09-28", "osm_date": "2026-09-28 22:03Z",
         "source": "live", "missing": 7, "matched": 3}]


def test_a_second_run_the_same_day_replaces_the_first(tmp_path):
    path = tmp_path / "history.jsonl"
    record(path, day="2026-09-28")
    record(path, {**SUMMARY, "missing": 6}, day="2026-09-28")
    assert [r["missing"] for r in history.load(str(path))] == [6]


def test_a_run_on_cached_osm_is_not_recorded(tmp_path):
    path = tmp_path / "history.jsonl"
    assert record(path, {**SUMMARY, "osm_stale": True}) is None
    assert history.load(str(path)) == []


def test_a_count_not_taken_is_zero_or_left_out(tmp_path):
    summary = {"missing": 7, "osm_stale": False}
    assert record(tmp_path / "a.jsonl", summary, day="2026-09-28")["matched"] == 0
    row = record(tmp_path / "b.jsonl", summary, day="2026-09-28", sparse=True)
    assert "matched" not in row


def test_rows_are_kept_oldest_first(tmp_path):
    path = tmp_path / "history.jsonl"
    record(path, day="2026-09-28")
    record(path, day="2026-09-21")
    assert [r["date"] for r in history.load(str(path))] == ["2026-09-21", "2026-09-28"]


def test_seed_starts_from_the_published_copy_once(tmp_path, monkeypatch):
    path = str(tmp_path / "data" / "history.jsonl")

    class Resp:
        status_code = 200
        text = '{"date": "2026-09-21", "missing": 9}'

    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    assert history.seed(path, "https://x.example/h.jsonl", "test") is True
    assert history.load(path) == [{"date": "2026-09-21", "missing": 9}]
    assert history.seed(path, "https://x.example/h.jsonl", "test") is False


def test_seed_is_best_effort(tmp_path, monkeypatch):
    def down(*a, **k):
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(requests, "get", down)
    assert history.seed(str(tmp_path / "h.jsonl"), "https://x.example/h", "t") is False


def test_dates_step_until_the_end():
    got = list(history.dates(date(2026, 6, 1), date(2026, 6, 20), 7))
    assert got == [date(2026, 6, 1), date(2026, 6, 8), date(2026, 6, 15)]
