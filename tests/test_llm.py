"""Tests for the LLM client (app/llm.py) in offline mock mode."""
import asyncio
import json

from app import llm


def test_extract_json_plain():
    assert llm.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = "```json\n{\"a\": 1, \"b\": [2, 3]}\n```"
    assert llm.extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_json_embedded_in_prose():
    text = "Sure! Here it is: {\"score\": 0.5} hope that helps"
    assert llm.extract_json(text) == {"score": 0.5}


def test_mock_resume_score(monkeypatch):
    # Force mock mode regardless of environment.
    monkeypatch.setattr(llm, "is_live", lambda: False)
    out = asyncio.run(llm.chat("Please score this resume", json_mode=True))
    data = json.loads(out)
    assert "overall_score" in data
    assert "breakdown" in data
    assert "extracted_skills" in data


def test_mock_json_mode_returns_parseable(monkeypatch):
    monkeypatch.setattr(llm, "is_live", lambda: False)
    out = asyncio.run(llm.chat("some unrelated prompt", json_mode=True))
    json.loads(out)  # must not raise
