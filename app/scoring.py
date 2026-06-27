"""Deterministic course scoring.

A single canonical scorer (the old codebase had two divergent ones plus a set of
hardcoded weights that silently overrode settings.py). This one is pure, fast,
and reads every weight from settings so behaviour is configurable in one place.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from settings import settings

STOP = set(
    "a an the and or for of to in on with by from at as is are was were be been being "
    "your you my me our their his her it they we".split()
)


# --------------------------------------------------------------------------- #
# Text similarity primitives
# --------------------------------------------------------------------------- #
def tokenize(s: str) -> List[str]:
    return [
        w for w in re.findall(r"[A-Za-z][A-Za-z0-9+\-_.]*", (s or "").lower())
        if w not in STOP and len(w) > 1
    ]


def bow(s: str) -> Counter:
    return Counter(tokenize(s))


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    inter = set(a) & set(b)
    num = sum(a[t] * b[t] for t in inter)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return (num / den) if den else 0.0


def skill_overlap(existing_skills: List[str], course_text: str) -> float:
    """How much course content overlaps with skills the person already has (0-1)."""
    if not existing_skills or not course_text:
        return 0.0
    existing = Counter()
    for skill in existing_skills:
        existing.update(tokenize(skill))
    return cosine(existing, bow(course_text))


def build_query_bow(terms: List[str]) -> Counter:
    return bow(" ".join(terms))


# --------------------------------------------------------------------------- #
# Course scoring
# --------------------------------------------------------------------------- #
def _course_texts(course: dict) -> Tuple[str, str, str]:
    """Return (core_text, secondary_text, tag_text) from a raw course dict."""
    title = course.get("title") or ""
    objective = course.get("objective") or ""
    content = course.get("content") or ""
    core = f"{title} {title} {objective} {content}"  # title repeated for emphasis

    skills_text = " ".join(
        wsq["competencyStandardDescription"]
        for wsq in (course.get("wsqFrameworks") or [])
        if wsq.get("competencyStandardDescription")
    )
    unique_skills = " ".join(s.get("title", "") for s in (course.get("UniqueSkills") or []))
    suitable_jobs = course.get("suitableJobRoles") or ""
    secondary = f"{skills_text} {unique_skills} {suitable_jobs}"

    tag_text = " ".join(
        t.get("description", "")
        for t in (course.get("taggings") or []) if isinstance(t, dict)
    ) + " " + " ".join(
        a.get("description", "")
        for a in (course.get("areaOfTrainings") or []) if isinstance(a, dict)
    )
    return core, secondary, tag_text


def _duration_hours(course: dict) -> Optional[float]:
    dur = course.get("totalTrainingDurationHour")
    if dur is not None:
        return dur
    if course.get("lengthOfCourseDuration") is not None:
        return float(course["lengthOfCourseDuration"]) * 8.0
    if course.get("numberOfTrainingDay") is not None:
        return float(course["numberOfTrainingDay"]) * 8.0
    return None


def score_course(
    course: dict,
    query_bow: Counter,
    *,
    skills: List[str],
    skill_gaps: List[str],
    industry: Optional[str],
    focus_on_gaps: bool,
    gap_coverage_override: Optional[float] = None,
) -> Tuple[float, Dict[str, float], float, float, str]:
    """Score one course.

    Returns: (final_score, score_breakdown, skill_gap_coverage, existing_skill_overlap, reason)
    """
    core, secondary, tag_text = _course_texts(course)
    full_text = f"{core} {secondary} {tag_text}"

    core_sim = cosine(bow(core), query_bow)
    secondary_sim = cosine(bow(secondary), query_bow)
    tag_sim = cosine(bow(tag_text), query_bow)
    sim_score = core_sim * 0.6 + secondary_sim * 0.3 + tag_sim * 0.1

    # Skill-gap coverage: explicit gaps if given, else alignment of the goal query with the course.
    if gap_coverage_override is not None:
        gap_coverage = max(0.0, min(1.0, gap_coverage_override))
    elif skill_gaps:
        gap_bow = Counter()
        for gap in skill_gaps:
            gap_bow.update(tokenize(gap))
        gap_coverage = cosine(bow(full_text), gap_bow)
    else:
        gap_coverage = core_sim

    existing_overlap = skill_overlap(skills, full_text) if skills else 0.0

    price = course.get("totalCostOfTrainingPerTrainee")
    price_score = 0.0 if price is None else max(0.0, min(1.0, 1.0 / (1.0 + price / 500.0)))

    dur = _duration_hours(course)
    dur_score = 0.0 if dur is None else max(0.0, min(1.0, 1.0 / (1.0 + dur / 40.0)))

    # Industry/area match bonus
    area_bonus = 0.0
    if industry and course.get("areaOfTrainings"):
        industry_tokens = set(tokenize(industry))
        for area in course["areaOfTrainings"]:
            if industry_tokens & set(tokenize(area.get("description", ""))):
                area_bonus = settings.AREA_MATCH_BONUS
                break

    gap_bonus = gap_coverage * settings.SKILL_GAP_BONUS if focus_on_gaps else 0.0

    overlap_penalty = 0.0
    if focus_on_gaps and existing_overlap > settings.EXISTING_SKILL_OVERLAP_THRESHOLD:
        overlap_penalty = (
            (existing_overlap - settings.EXISTING_SKILL_OVERLAP_THRESHOLD)
            * settings.EXISTING_SKILL_PENALTY
        )

    final_score = (
        settings.WEIGHT_SIMILARITY * sim_score
        + settings.WEIGHT_PRICE * price_score
        + settings.WEIGHT_DURATION * dur_score
        + gap_bonus
        + area_bonus
        - overlap_penalty
    )

    breakdown = {
        "content_similarity": round(core_sim, 3),
        "skills_similarity": round(secondary_sim, 3),
        "tag_similarity": round(tag_sim, 3),
        "combined_similarity": round(sim_score, 3),
        "price": round(price_score, 3),
        "duration": round(dur_score, 3),
        "skill_gap_bonus": round(gap_bonus, 3),
        "area_bonus": round(area_bonus, 3),
        "overlap_penalty": round(overlap_penalty, 3),
        "final": round(final_score, 4),
    }

    return final_score, breakdown, gap_coverage, existing_overlap, _reason(
        course, core_sim, gap_coverage, area_bonus, existing_overlap
    )


def _reason(course: dict, core_sim: float, gap_coverage: float, area_bonus: float, overlap: float) -> str:
    title = (course.get("title") or "").lower()
    parts: List[str] = []

    if any(w in title for w in ("certification", "certified", "exam", "qualification")):
        parts.append("Industry-recognized certification")
    elif any(w in title for w in ("professional", "advanced", "expert")):
        parts.append("Advanced training for professionals")
    elif any(w in title for w in ("fundamental", "basic", "introduction", "essentials")):
        parts.append("Builds essential foundation skills")
    else:
        parts.append("Relevant to your career objectives")

    if gap_coverage > 0.5:
        parts.append("addresses key skill gaps")
    elif core_sim > 0.4:
        parts.append("strong alignment with your goal")
    else:
        parts.append("expands your professional skill set")

    if area_bonus > 0:
        parts.append("matches your target industry")

    return " • ".join(parts[:3])
