"""Tests for agent tool dispatch (app/tools.py)."""
import asyncio
import json

from app import tools, ssg


def _run(coro):
    return asyncio.run(coro)


def test_search_courses_caches_and_returns_compact(monkeypatch):
    fake = [{
        "referenceNumber": "REF-1",
        "title": "Intro to Python",
        "trainingProviderAlias": "Acme",
        "totalCostOfTrainingPerTrainee": 200.0,
        "objective": "x" * 500,
    }]

    async def fake_search(keyword, page_size=10, page=0):
        return fake

    monkeypatch.setattr(ssg, "search_courses", fake_search)
    ctx = tools.AgentContext()
    out = _run(tools.dispatch("search_courses", json.dumps({"query": "python"}), ctx))

    assert out["final"] is None
    assert out["content"]["count"] == 1
    assert out["content"]["courses"][0]["course_ref"] == "REF-1"
    assert len(out["content"]["courses"][0]["objective"]) <= 300  # truncated
    assert "REF-1" in ctx.course_cache  # cached for later scoring
    assert ctx.tool_calls_made == 1


def test_search_requires_query(monkeypatch):
    ctx = tools.AgentContext()
    out = _run(tools.dispatch("search_courses", json.dumps({"query": "  "}), ctx))
    assert "error" in out["content"]


def test_bad_json_arguments_handled():
    ctx = tools.AgentContext()
    out = _run(tools.dispatch("search_courses", "{not json", ctx))
    assert "error" in out["content"]


def test_submit_recommendations_is_terminal():
    ctx = tools.AgentContext()
    recs = [{"course_ref": "REF-1", "reason": "great fit"}]
    out = _run(tools.dispatch("submit_recommendations", json.dumps({"recommendations": recs}), ctx))
    assert out["final"] == recs


def test_unknown_tool():
    ctx = tools.AgentContext()
    out = _run(tools.dispatch("does_not_exist", "{}", ctx))
    assert "error" in out["content"]
