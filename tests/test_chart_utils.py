# ABOUTME: Tests for pure chart data helper functions.
# ABOUTME: Validates aggregation logic without Streamlit/plotly dependencies.

from utils.chart import section_score_data, source_chart_data


def test_source_chart_data_status_counts():
    audit = [
        {"status": "LIVE", "domain_type": "news"},
        {"status": "LIVE", "domain_type": "academic"},
        {"status": "DEAD", "domain_type": "news"},
    ]
    status_counts, _ = source_chart_data(audit)
    assert status_counts == {"LIVE": 2, "DEAD": 1}


def test_source_chart_data_type_counts():
    audit = [
        {"status": "LIVE", "domain_type": "news"},
        {"status": "LIVE", "domain_type": "academic"},
        {"status": "DEAD", "domain_type": "news"},
    ]
    _, type_counts = source_chart_data(audit)
    assert type_counts == {"news": 2, "academic": 1}


def test_source_chart_data_empty():
    status_counts, type_counts = source_chart_data([])
    assert status_counts == {}
    assert type_counts == {}


def test_source_chart_data_missing_fields():
    audit = [{"status": "LIVE"}]  # no domain_type
    status_counts, type_counts = source_chart_data(audit)
    assert status_counts == {"LIVE": 1}
    assert type_counts == {"unknown": 1}


def test_section_score_data_sorted_ascending():
    grades = {"Intro": 8.0, "History": 5.0, "See also": 3.0}
    sections, scores = section_score_data(grades)
    assert sections == ["See also", "History", "Intro"]
    assert scores == [3.0, 5.0, 8.0]


def test_section_score_data_empty():
    sections, scores = section_score_data({})
    assert sections == []
    assert scores == []


def test_section_score_data_article_order():
    grades = {"Intro": 8.0, "History": 5.0, "See also": 3.0}
    order = ["Intro", "History", "See also"]
    sections, scores = section_score_data(grades, order)
    assert sections == ["Intro", "History", "See also"]
    assert scores == [8.0, 5.0, 3.0]


def test_section_score_data_partial_order():
    # sections not in order fall back to score-ascending at the end
    grades = {"Intro": 8.0, "History": 5.0, "Orphan": 2.0}
    order = ["Intro", "History"]
    sections, scores = section_score_data(grades, order)
    assert sections == ["Intro", "History", "Orphan"]
    assert scores == [8.0, 5.0, 2.0]
