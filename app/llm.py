"""Provider-agnostic LLM client.

Talks to any OpenAI-compatible Chat Completions endpoint (Groq by default, but
Ollama / OpenRouter / vLLM / LM Studio all work by changing settings only).

Replaces the old AWS Bedrock integration. Two entry points:
  - chat(...)            : single text/JSON completion
  - chat_with_tools(...) : a turn of the agent loop (may return tool calls)

If no API key is configured the client runs in offline "mock mode" so the app
still boots and degrades gracefully instead of crashing.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from settings import settings

_client: Optional[AsyncOpenAI] = None


def is_live() -> bool:
    """True when a real API key is configured (i.e. not in mock mode)."""
    key = (settings.LLM_API_KEY or "").strip()
    return bool(key) and key.lower() not in {"replace with groq api key", "none"}


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY or "not-needed",
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,  # we handle retries/backoff ourselves
        )
    return _client


def extract_json(text: str) -> Any:
    """Parse JSON from a model response that may be wrapped in prose or ``` fences."""
    if text is None:
        raise ValueError("No text to parse")
    s = text.strip()
    if s.startswith("```"):
        # strip leading ```json / ``` and trailing ```
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # fall back to the first {...} object or [...] array in the text
        match = re.search(r"\{.*\}|\[.*\]", s, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def _build_messages(messages: List[Dict[str, Any]], system: Optional[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system.strip()})
    out.extend(messages)
    return out


async def _with_retry(coro_factory):
    """Run an async LLM call with exponential backoff on transient errors.

    Fixes the old bug where retries used a blocking time.sleep() inside async code.
    """
    last_err: Optional[Exception] = None
    for attempt in range(settings.LLM_MAX_RETRIES):
        try:
            return await coro_factory()
        except (RateLimitError, APITimeoutError, APIConnectionError) as err:
            last_err = err
        except APIStatusError as err:
            # only retry server-side errors; re-raise 4xx (bad request, auth, etc.)
            if err.status_code < 500 and err.status_code != 429:
                raise
            last_err = err
        if attempt < settings.LLM_MAX_RETRIES - 1:
            delay = settings.LLM_RETRY_BASE_DELAY * (2 ** attempt)
            print(f"[llm] transient error ({last_err}); retry {attempt + 1} in {delay:.1f}s")
            await asyncio.sleep(delay)
    raise last_err  # type: ignore[misc]


async def chat(
    prompt: str,
    *,
    system: Optional[str] = None,
    json_mode: bool = False,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Single-shot completion. Returns the assistant text.

    Replaces every old get_bedrock_completion(...) call.
    """
    if not is_live():
        return _mock_completion(prompt, json_mode=json_mode)

    messages = _build_messages([{"role": "user", "content": prompt}], system)
    kwargs: Dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    client = _get_client()

    async def _call():
        return await client.chat.completions.create(**kwargs)

    try:
        resp = await _with_retry(_call)
        return resp.choices[0].message.content or ""
    except Exception as err:  # noqa: BLE001 - graceful degradation for callers
        print(f"[llm] chat failed, using mock fallback: {err}")
        return _mock_completion(prompt, json_mode=json_mode)


async def chat_with_tools(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    *,
    system: Optional[str] = None,
    tool_choice: str = "auto",
):
    """One turn of the agent loop. Returns the raw assistant message object,
    which may contain `.tool_calls`. Raises on hard failure so the agent can
    fall back to the deterministic path.
    """
    full = _build_messages(messages, system)
    client = _get_client()

    async def _call():
        return await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=full,
            tools=tools,
            tool_choice=tool_choice,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    resp = await _with_retry(_call)
    return resp.choices[0].message


# --------------------------------------------------------------------------- #
# Offline mock mode (no API key) — keeps the app usable without an LLM.
# --------------------------------------------------------------------------- #
def _mock_completion(prompt: str, *, json_mode: bool) -> str:
    p = prompt.lower()

    if "resume" in p and "score" in p:
        return json.dumps({
            "overall_score": 78.0,
            "grade": "C+",
            "breakdown": {
                "contact_info": 85.0, "summary_objective": 60.0, "experience": 75.0,
                "education": 85.0, "skills": 75.0, "formatting": 80.0,
                "keywords": 65.0, "quantifiable_achievements": 60.0,
            },
            "strengths": [
                "Relevant technical skills are present",
                "Clear education background",
                "Logical structure and readable formatting",
            ],
            "improvement_areas": [
                "Add quantifiable achievements with concrete metrics",
                "Strengthen the professional summary",
                "Include more role-specific keywords for ATS",
            ],
            "detailed_feedback": (
                "CURRENT STRENGTHS:\n- Solid technical foundation\n- Clear education section\n\n"
                "GAPS TO ADDRESS:\n- Missing measurable impact\n- Summary needs sharpening\n\n"
                "RECOMMENDED ACTIONS:\n- Add metrics to experience\n- Pursue relevant certifications\n\n"
                "CAREER ALIGNMENT:\n- Good fit for technical roles (offline estimate)"
            ),
            "industry_alignment": "Moderate alignment (offline mock — set LLM_API_KEY for real analysis)",
            "extracted_skills": ["Communication", "Problem Solving", "Teamwork"],
        })

    if "suggestions" in p or ("resume" in p and "improve" in p):
        return json.dumps({
            "suggestions": [{
                "section": "Summary",
                "current_text": None,
                "suggested_improvement": "Results-driven professional with measurable impact across projects.",
                "explanation": "Impact-focused language reads stronger to recruiters and ATS.",
                "impact_level": "High",
            }],
            "overall_strategy": "Quantify achievements and add role-specific keywords. (offline mock)",
            "priority_order": ["Experience", "Summary", "Skills", "Education"],
        })

    if json_mode:
        return "{}"
    return "Offline mock response — set LLM_API_KEY in .env for real AI output."
