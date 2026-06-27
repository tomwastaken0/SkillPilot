"""The course-recommendation agent.

A real tool-calling loop: the LLM searches the catalog, inspects courses, refines
its queries, and submits a final ranked set. If no LLM is configured, or the loop
errors/stalls, we fall back to a deterministic search+score pipeline so the
/recommend endpoint always returns something sensible.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from settings import settings
from app import llm, prompts, scoring, ssg
from app.schemas import RecItem, RecommendOut, RecommendReq
from app.tools import TOOL_SCHEMAS, AgentContext, dispatch

_TRANSITION_STOPWORDS = {
    "want", "become", "work", "career", "job", "position", "role", "professional",
    "get", "find", "looking", "seeking", "interested", "pursue", "transition",
    "and", "the", "for", "with", "into", "from", "that", "this", "have", "as", "in",
}


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
async def recommend(req: RecommendReq) -> RecommendOut:
    """Produce course recommendations, agentically when possible."""
    if llm.is_live():
        try:
            return await _agentic_recommend(req)
        except Exception as err:  # noqa: BLE001 - never 500 the endpoint
            print(f"[agent] agentic path failed ({err}); falling back to deterministic search")
    return await _deterministic_recommend(req, fallback_reason="llm_unavailable")


# --------------------------------------------------------------------------- #
# Agentic path
# --------------------------------------------------------------------------- #
async def _agentic_recommend(req: RecommendReq) -> RecommendOut:
    resume = req.resume
    ctx = AgentContext()

    user_msg = prompts.agent_user_context(
        goal=resume.Goal or "",
        skills=resume.Skills or [],
        industry=resume.Industry,
        skill_gaps=resume.SkillGaps or [],
        top_k=req.top_k,
    )
    messages: List[Dict[str, Any]] = [{"role": "user", "content": user_msg}]
    final_recs: Optional[List[dict]] = None
    steps_used = 0

    for step in range(settings.AGENT_MAX_STEPS):
        steps_used = step + 1
        # Force a decision on the last step.
        last_step = step == settings.AGENT_MAX_STEPS - 1
        msg = await llm.chat_with_tools(
            messages,
            TOOL_SCHEMAS,
            system=prompts.AGENT_SYSTEM,
            tool_choice="required" if last_step else "auto",
        )
        messages.append(msg.model_dump(exclude_none=True))

        tool_calls = msg.tool_calls or []
        if not tool_calls:
            break  # model gave a plain answer; we'll rank whatever it found

        for call in tool_calls:
            out = await dispatch(call.function.name, call.function.arguments, ctx)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(out["content"])[:4000],
            })
            if out["final"] is not None:
                final_recs = out["final"]

        if final_recs is not None:
            break
        if ctx.tool_calls_made >= settings.AGENT_MAX_TOOL_CALLS:
            break

    selected = _resolve_recommendations(final_recs, ctx)
    debug = {
        "mode": "agentic",
        "steps_used": steps_used,
        "tool_calls_made": ctx.tool_calls_made,
        "searches": ctx.searches,
        "courses_seen": len(ctx.course_cache),
        "submitted_count": len(final_recs) if final_recs else 0,
    }

    if not selected:
        # Agent found nothing usable — fall back deterministically but keep the debug trail.
        result = await _deterministic_recommend(req, fallback_reason="agent_no_results")
        result.debug_info = {**(result.debug_info or {}), "agent_debug": debug}
        return result

    return _build_output(req, selected, query_terms=ctx.searches or [resume.Goal or ""], debug=debug)


def _resolve_recommendations(
    final_recs: Optional[List[dict]], ctx: AgentContext
) -> List[Tuple[dict, Optional[str]]]:
    """Map the agent's submitted refs to cached raw courses, preserving order.

    If the agent never submitted, fall back to every course it saw (so a stalled
    run still yields ranked results).
    """
    selected: List[Tuple[dict, Optional[str]]] = []
    seen: set = set()

    if final_recs:
        for rec in final_recs:
            ref = (rec or {}).get("course_ref")
            if ref and ref in ctx.course_cache and ref not in seen:
                selected.append((ctx.course_cache[ref], rec.get("reason")))
                seen.add(ref)

    if not selected:
        selected = [(course, None) for course in ctx.course_cache.values()]

    return selected


# --------------------------------------------------------------------------- #
# Deterministic fallback path
# --------------------------------------------------------------------------- #
async def _deterministic_recommend(req: RecommendReq, *, fallback_reason: str) -> RecommendOut:
    resume = req.resume
    terms = _basic_terms(resume.Goal or "", resume.Industry, resume.SkillGaps or [])
    query = " ".join(terms) or "professional development"

    strategies = [
        query,
        " ".join(terms[:2]),
        resume.Goal or "professional development",
        "professional development",
    ]

    rows: List[dict] = []
    used_strategy = None
    for strat in strategies:
        if not strat.strip():
            continue
        try:
            found = await ssg.search_courses(strat, page_size=req.page_size)
        except ssg.SSGError as err:
            print(f"[agent] fallback search '{strat}' failed: {err.detail}")
            continue
        if found:
            rows, used_strategy = found, strat
            break

    selected = [(r, None) for r in rows]
    debug = {
        "mode": "deterministic_fallback",
        "reason": fallback_reason,
        "search_strategy_used": used_strategy,
        "courses_found": len(rows),
    }
    return _build_output(req, selected, query_terms=terms, debug=debug, sort_by_score=True)


def _basic_terms(goal: str, industry: Optional[str], skill_gaps: List[str]) -> List[str]:
    words = [w for w in re.findall(r"\b[a-zA-Z]{3,}\b", goal.lower()) if w not in _TRANSITION_STOPWORDS]
    terms = words[:6]
    for gap in skill_gaps[:2]:
        terms.extend([w for w in re.findall(r"\b[a-zA-Z]{3,}\b", gap.lower()) if len(w) > 2][:2])
    if industry:
        terms.extend([w for w in re.findall(r"\b[a-zA-Z]{3,}\b", industry.lower()) if w not in _TRANSITION_STOPWORDS][:2])
    # de-dupe, preserve order
    out, seen = [], set()
    for t in terms:
        if t not in seen and len(t) > 2:
            out.append(t)
            seen.add(t)
    return out[:8] or ["professional", "development"]


# --------------------------------------------------------------------------- #
# Shared result builder
# --------------------------------------------------------------------------- #
def _build_output(
    req: RecommendReq,
    selected: List[Tuple[dict, Optional[str]]],
    *,
    query_terms: List[str],
    debug: Dict[str, Any],
    sort_by_score: bool = False,
) -> RecommendOut:
    resume = req.resume
    query_bow = scoring.build_query_bow([resume.Goal or ""] + (resume.SkillGaps or []) + query_terms)

    items: List[RecItem] = []
    filtered_out = 0
    for course, agent_reason in selected:
        # Budget filter (generous, like the original).
        price = course.get("totalCostOfTrainingPerTrainee")
        if req.budget_max is not None and price is not None and price > req.budget_max * 1.5:
            filtered_out += 1
            continue

        score, breakdown, gap_cov, overlap, reason = scoring.score_course(
            course,
            query_bow,
            skills=resume.Skills or [],
            skill_gaps=resume.SkillGaps or [],
            industry=resume.Industry,
            focus_on_gaps=req.focus_on_gaps,
        )
        item = ssg.extract_course_item(course)
        items.append(RecItem(
            **item.model_dump(),
            score=round(score, 4),
            score_breakdown=breakdown,
            skill_gap_coverage=round(gap_cov, 3),
            existing_skill_overlap=round(overlap, 3),
            recommendation_reason=agent_reason or reason,
        ))

    if sort_by_score:
        items.sort(key=lambda x: x.score, reverse=True)

    items = items[:req.top_k]

    used_filters = {
        "budget_max": req.budget_max,
        "duration_max_hours": req.duration_max_hours,
        "area_of_training": req.area_of_training,
        "focus_on_gaps": req.focus_on_gaps,
        "courses_filtered_out": filtered_out,
        "courses_after_filtering": len(items),
    }
    skill_gap_analysis: Dict[str, Any] = {
        "identified_gaps": resume.SkillGaps or [],
        "existing_skills": resume.Skills or [],
        "gap_focused_search": req.focus_on_gaps,
    }
    if items:
        threshold = settings.EXISTING_SKILL_OVERLAP_THRESHOLD
        skill_gap_analysis.update({
            "avg_gap_coverage": round(sum(i.skill_gap_coverage for i in items) / len(items), 3),
            "avg_existing_overlap": round(sum(i.existing_skill_overlap for i in items) / len(items), 3),
            "high_gap_coverage_courses": len([i for i in items if i.skill_gap_coverage > 0.4]),
            "low_overlap_courses": len([i for i in items if i.existing_skill_overlap < threshold]),
        })

    return RecommendOut(
        query_terms=query_terms,
        items=items,
        used_filters=used_filters,
        skill_gap_analysis=skill_gap_analysis,
        debug_info=debug,
    )
