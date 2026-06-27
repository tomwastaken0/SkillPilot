"""Tests for deterministic scoring (app/scoring.py)."""
import pytest

from app import scoring


def test_tokenize_drops_stopwords_and_shorts():
    toks = scoring.tokenize("The Python and SQL")
    assert "python" in toks
    assert "sql" in toks
    assert "the" not in toks  # stopword
    assert "and" not in toks


def test_cosine_identical_and_disjoint():
    a = scoring.bow("python data science")
    assert scoring.cosine(a, a) == pytest.approx(1.0)
    assert scoring.cosine(a, scoring.bow("cooking pastry")) == 0.0


def test_score_course_returns_full_breakdown():
    course = {
        "title": "Python for Data Science",
        "objective": "Learn python, pandas and machine learning for data analysis.",
        "content": "python pandas numpy machine learning",
        "totalCostOfTrainingPerTrainee": 300.0,
        "totalTrainingDurationHour": 24.0,
    }
    qbow = scoring.build_query_bow(["data scientist", "python", "machine learning"])
    score, breakdown, gap, overlap, reason = scoring.score_course(
        course, qbow, skills=["excel"], skill_gaps=["machine learning"],
        industry=None, focus_on_gaps=True,
    )
    assert 0.0 <= score
    assert breakdown["final"] == round(score, 4)
    assert 0.0 <= gap <= 1.0
    assert isinstance(reason, str) and reason


def test_existing_skill_penalty_lowers_score():
    course = {
        "title": "Advanced Excel",
        "objective": "Master excel spreadsheets and formulas",
        "content": "excel spreadsheets pivot tables formulas",
    }
    qbow = scoring.build_query_bow(["excel"])
    score_known, *_ = scoring.score_course(
        course, qbow, skills=["excel", "excel spreadsheets formulas pivot"],
        skill_gaps=[], industry=None, focus_on_gaps=True,
    )
    score_new, *_ = scoring.score_course(
        course, qbow, skills=["cooking"], skill_gaps=[],
        industry=None, focus_on_gaps=True,
    )
    # A course overlapping heavily with existing skills should not score higher.
    assert score_known <= score_new
