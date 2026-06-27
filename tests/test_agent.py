"""Tests for the recommendation agent loop (app/agent.py)."""
import asyncio
import json

from app import agent, llm, ssg
from app.schemas import RecommendReq, ResumePayload


# --- Fakes that mimic the OpenAI chat-completion message shape -------------- #
class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.type = "function"
        self.function = _Fn(name, arguments)


class _Msg:
    def __init__(self, tool_calls=None, content=None):
        self.tool_calls = tool_calls
        self.content = content

    def model_dump(self, exclude_none=False):
        d = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in self.tool_calls
            ]
        if exclude_none:
            d = {k: v for k, v in d.items() if v is not None}
        return d


FAKE_COURSE = {
    "referenceNumber": "REF-DS-1",
    "title": "Data Science Foundations",
    "trainingProviderAlias": "Acme Academy",
    "totalCostOfTrainingPerTrainee": 400.0,
    "totalTrainingDurationHour": 32.0,
    "objective": "Learn python, statistics and machine learning for data science roles.",
    "content": "python pandas statistics machine learning",
}


def _req():
    return RecommendReq(
        resume=ResumePayload(
            Goal="become a data scientist",
            Skills=["excel"],
            SkillGaps=["machine learning"],
        ),
        top_k=5,
    )


def test_agentic_loop_searches_then_submits(monkeypatch):
    monkeypatch.setattr(llm, "is_live", lambda: True)

    async def fake_search(keyword, page_size=10, page=0):
        return [FAKE_COURSE]

    monkeypatch.setattr(ssg, "search_courses", fake_search)

    # Turn 1: search; Turn 2: submit the found course.
    scripted = [
        _Msg(tool_calls=[_ToolCall("c1", "search_courses", json.dumps({"query": "data science python"}))]),
        _Msg(tool_calls=[_ToolCall("c2", "submit_recommendations", json.dumps(
            {"recommendations": [{"course_ref": "REF-DS-1", "reason": "Covers ML you need"}]}))]),
    ]
    calls = {"n": 0}

    async def fake_chat_with_tools(messages, tools_, system=None, tool_choice="auto"):
        msg = scripted[calls["n"]]
        calls["n"] += 1
        return msg

    monkeypatch.setattr(llm, "chat_with_tools", fake_chat_with_tools)

    out = asyncio.run(agent.recommend(_req()))

    assert out.debug_info["mode"] == "agentic"
    assert len(out.items) == 1
    item = out.items[0]
    assert item.id == "REF-DS-1"
    assert item.recommendation_reason == "Covers ML you need"  # agent's reason preserved
    assert "score" in item.model_dump()


def test_falls_back_to_deterministic_when_offline(monkeypatch):
    monkeypatch.setattr(llm, "is_live", lambda: False)

    async def fake_search(keyword, page_size=10, page=0):
        return [FAKE_COURSE]

    monkeypatch.setattr(ssg, "search_courses", fake_search)

    out = asyncio.run(agent.recommend(_req()))
    assert out.debug_info["mode"] == "deterministic_fallback"
    assert len(out.items) == 1
    assert out.items[0].id == "REF-DS-1"


def test_agent_exception_falls_back(monkeypatch):
    monkeypatch.setattr(llm, "is_live", lambda: True)

    async def boom(*a, **k):
        raise RuntimeError("llm down")

    async def fake_search(keyword, page_size=10, page=0):
        return [FAKE_COURSE]

    monkeypatch.setattr(llm, "chat_with_tools", boom)
    monkeypatch.setattr(ssg, "search_courses", fake_search)

    out = asyncio.run(agent.recommend(_req()))
    assert out.debug_info["mode"] == "deterministic_fallback"
    assert len(out.items) == 1
