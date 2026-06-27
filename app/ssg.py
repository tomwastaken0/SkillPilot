"""SSG-WSG (Singapore SkillsFuture) course directory API client.

Handles OAuth2 client-credentials token caching, raw API calls, and extraction
of the messy upstream payloads into our clean CourseItem / CourseDetail models.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from settings import settings
from app.schemas import CourseDetail, CourseItem

TIMEOUT = httpx.Timeout(12.0, connect=5.0)
_SKILLSFUTURE_COURSE_URL = (
    "https://www.myskillsfuture.gov.sg/content/portal/en/training-exchange/"
    "course-directory/course-detail.html?courseReferenceNumber={ref}"
)

_token_cache: Dict[str, Any] = {"access_token": None, "expires_at": datetime.min}


class SSGError(Exception):
    """Raised for SSG API failures; carries an HTTP-ish status code."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# --------------------------------------------------------------------------- #
# Auth + raw calls
# --------------------------------------------------------------------------- #
async def get_token() -> str:
    if _token_cache["access_token"] and datetime.utcnow() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            str(settings.SSG_TOKEN_URL),
            data={"grant_type": "client_credentials"},
            auth=(settings.SSG_CLIENT_ID, settings.SSG_CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as err:
            raise SSGError(502, f"SSG token request failed: {err.response.text}") from err
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise SSGError(502, f"No access_token in SSG response: {resp.text}")
        _token_cache["access_token"] = token
        _token_cache["expires_at"] = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 300))
        return token


async def ssg_get(path: str, params: Optional[Dict[str, Any]] = None, api_version: Optional[str] = None) -> dict:
    """Authenticated GET against the SSG API. Returns the parsed JSON body."""
    token = await get_token()
    base = str(settings.SSG_API_BASE).rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    headers = {
        "Accept": "application/json",
        "x-api-version": api_version or settings.SSG_API_VERSION,
        "Authorization": f"Bearer {token}",
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code == 429:
            raise SSGError(429, "Rate limited by SSG")
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as err:
            raise SSGError(err.response.status_code, f"SSG error: {err.response.text}") from err
        try:
            return resp.json()
        except ValueError as err:
            raise SSGError(502, f"SSG returned non-JSON response: {resp.text[:200]}") from err


# --------------------------------------------------------------------------- #
# High-level helpers
# --------------------------------------------------------------------------- #
def _course_url(ref: Optional[str]) -> Optional[str]:
    return _SKILLSFUTURE_COURSE_URL.format(ref=ref) if ref else None


def _duration_hours(r: dict) -> Optional[float]:
    hours = r.get("totalTrainingDurationHour")
    if hours is not None:
        return hours
    if r.get("lengthOfCourseDuration") is not None:
        return float(r["lengthOfCourseDuration"]) * 8.0
    if r.get("numberOfTrainingDay") is not None:
        return float(r["numberOfTrainingDay"]) * 8.0
    return None


def _tags(r: dict) -> List[str]:
    tags: List[str] = []
    for t in (r.get("taggings") or []):
        if isinstance(t, dict) and t.get("description"):
            tags.append(t["description"])
    for a in (r.get("areaOfTrainings") or []):
        if isinstance(a, dict) and a.get("description"):
            tags.append(a["description"])
    return tags


def _wsq_skills(r: dict) -> List[str]:
    return [
        wsq["competencyStandardDescription"]
        for wsq in (r.get("wsqFrameworks") or [])
        if wsq.get("competencyStandardDescription")
    ]


def extract_course_item(r: dict) -> CourseItem:
    """Map a raw directory course into a CourseItem (no LLM calls — fast)."""
    course_ref = r.get("referenceNumber") or r.get("skillsConnectReferenceNumber")

    unique_skills = [s["title"] for s in (r.get("UniqueSkills") or []) if s.get("title")]
    bundles = [b["description"] for b in (r.get("bundles") or []) if b.get("description")]

    area_of_training = None
    areas = r.get("areaOfTrainings") or []
    if areas:
        area_of_training = areas[0].get("description")

    external_accreditations = [
        acc["accreditingAgency"]["name"]
        for acc in (r.get("externalAccreditations") or [])
        if acc.get("accreditingAgency", {}).get("name")
    ]

    return CourseItem(
        id=course_ref,
        title=r.get("title"),
        provider=r.get("trainingProviderAlias"),
        url=_course_url(course_ref),
        price=r.get("totalCostOfTrainingPerTrainee"),
        duration_hours=_duration_hours(r),
        tags=_tags(r)[:10],
        skills=_wsq_skills(r),
        unique_skills=unique_skills,
        bundles=bundles,
        area_of_training=area_of_training,
        suitable_job_roles=r.get("suitableJobRoles"),
        external_accreditations=external_accreditations,
        objective=r.get("objective"),
        content=r.get("content"),
    )


def extract_course_detail(r: dict) -> CourseDetail:
    """Map a raw individual-course payload into a CourseDetail."""
    course_ref = r.get("referenceNumber") or r.get("skillsConnectReferenceNumber")
    tp = r.get("trainingProvider")
    return CourseDetail(
        id=course_ref,
        title=r.get("title"),
        provider=(tp or {}).get("name") if isinstance(tp, dict) else None,
        url=_course_url(course_ref),
        price=r.get("totalCostOfTrainingPerTrainee"),
        duration_hours=_duration_hours(r),
        tags=_tags(r),
        skills=_wsq_skills(r),
        objective=r.get("objective"),
        content=r.get("content"),
        entry_requirement=r.get("entryRequirement"),
        contact_persons=r.get("contactPerson", []) or [],
        runs=r.get("runs", []) or [],
        faculty_name=r.get("facultyName"),
        specialisation=r.get("specialisation"),
    )


async def search_courses(keyword: str, page_size: int = 10, page: int = 0) -> List[dict]:
    """Return raw course dicts for a keyword search (empty list if none)."""
    params = {"pageSize": page_size, "page": page, "keyword": keyword}
    raw = await ssg_get("/courses/directory", params=params)
    data = raw.get("data") or {}
    return data.get("courses") or []


async def get_course_detail_raw(course_ref: str, include_expired: bool = True) -> Optional[dict]:
    """Return the raw course-detail dict, or None if not found."""
    params = {"includeExpiredCourses": include_expired}
    raw = await ssg_get(f"/courses/directory/{course_ref}", params=params, api_version="v1.2")
    data = raw.get("data") or {}
    courses = data.get("courses") or []
    return courses[0] if courses else None
