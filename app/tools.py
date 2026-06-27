"""Agent tool definitions and dispatch.

These are the capabilities the LLM can actually invoke during the recommendation
loop. Each search caches the raw course payloads it sees in the shared
AgentContext, so the final `submit_recommendations` can be scored against real
data without re-fetching.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from settings import settings
from app import ssg


@dataclass
class AgentContext:
    """Mutable state shared across one agent run."""
    course_cache: Dict[str, dict] = field(default_factory=dict)  # course_ref -> raw course dict
    tool_calls_made: int = 0
    searches: List[str] = field(default_factory=list)


# OpenAI-compatible tool schemas advertised to the model.
TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_courses",
            "description": (
                "Search the Singapore SkillsFuture course directory by keyword. "
                "Use short skill/topic keywords (e.g. 'python data analysis'), not full sentences. "
                "Returns a list of candidate courses with their reference numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword(s) to search for."},
                    "limit": {
                        "type": "integer",
                        "description": f"Max courses to return (1-{settings.AGENT_SEARCH_PAGE_SIZE}).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_course_details",
            "description": "Get fuller details (objective, content, entry requirements) for one course by its reference number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "course_ref": {"type": "string", "description": "Course reference number from a search result."},
                },
                "required": ["course_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_recommendations",
            "description": (
                "Submit the final ranked course recommendations. Call this once you have enough "
                "strong candidates. Only use course reference numbers returned by search_courses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recommendations": {
                        "type": "array",
                        "description": "Best courses first.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "course_ref": {"type": "string"},
                                "reason": {"type": "string", "description": "Short, user-facing reason."},
                            },
                            "required": ["course_ref", "reason"],
                        },
                    },
                },
                "required": ["recommendations"],
            },
        },
    },
]


def _compact_course(r: dict) -> Dict[str, Any]:
    """A small view of a course for the model (keeps tokens down)."""
    objective = (r.get("objective") or "")[:300]
    ref = r.get("referenceNumber") or r.get("skillsConnectReferenceNumber")
    return {
        "course_ref": ref,
        "title": r.get("title"),
        "provider": r.get("trainingProviderAlias"),
        "price": r.get("totalCostOfTrainingPerTrainee"),
        "objective": objective,
    }


def _cache_courses(ctx: AgentContext, courses: List[dict]) -> None:
    for r in courses:
        ref = r.get("referenceNumber") or r.get("skillsConnectReferenceNumber")
        if ref:
            ctx.course_cache[ref] = r


async def dispatch(name: str, arguments: str, ctx: AgentContext) -> Dict[str, Any]:
    """Execute a tool call. Returns {"content": <json-able>, "final": <payload or None>}.

    `final` is set only for submit_recommendations, which terminates the loop.
    Tool errors are returned as content (not raised) so the model can recover.
    """
    ctx.tool_calls_made += 1
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return {"content": {"error": "Invalid JSON arguments."}, "final": None}

    if name == "search_courses":
        query = (args.get("query") or "").strip()
        if not query:
            return {"content": {"error": "query is required"}, "final": None}
        limit = int(args.get("limit") or settings.AGENT_SEARCH_PAGE_SIZE)
        limit = max(1, min(limit, settings.AGENT_SEARCH_PAGE_SIZE))
        ctx.searches.append(query)
        try:
            courses = await ssg.search_courses(query, page_size=limit)
        except ssg.SSGError as err:
            return {"content": {"error": f"search failed: {err.detail}"}, "final": None}
        _cache_courses(ctx, courses)
        return {
            "content": {
                "query": query,
                "count": len(courses),
                "courses": [_compact_course(r) for r in courses],
            },
            "final": None,
        }

    if name == "get_course_details":
        ref = (args.get("course_ref") or "").strip()
        if not ref:
            return {"content": {"error": "course_ref is required"}, "final": None}
        try:
            detail = await ssg.get_course_detail_raw(ref)
        except ssg.SSGError as err:
            return {"content": {"error": f"detail fetch failed: {err.detail}"}, "final": None}
        if not detail:
            return {"content": {"error": "course not found"}, "final": None}
        _cache_courses(ctx, [detail])
        d = _compact_course(detail)
        d["content"] = (detail.get("content") or "")[:400]
        d["entry_requirement"] = detail.get("entryRequirement")
        return {"content": d, "final": None}

    if name == "submit_recommendations":
        recs = args.get("recommendations") or []
        return {"content": {"received": len(recs)}, "final": recs}

    return {"content": {"error": f"unknown tool: {name}"}, "final": None}
