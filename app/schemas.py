"""Pydantic request/response models shared across the app and FastAPI routes.

These are the public API contract consumed by the React frontend (index.html);
field names and shapes must stay stable.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------- Course models ----------
class Rolodex(BaseModel):
    display: bool
    numberOfLetters: int = Field(..., ge=1)


class Category(BaseModel):
    id: int
    name: str
    display: bool
    rolodex: Rolodex


class CategoriesOut(BaseModel):
    count: int
    categories: List[Category]


class CourseTag(BaseModel):
    text: str
    count: int


class CourseTagsOut(BaseModel):
    tags: List[CourseTag]
    total: int


class CourseItem(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    provider: Optional[str] = None
    url: Optional[str] = None
    price: Optional[float] = None
    duration_hours: Optional[float] = None
    tags: List[str] = []
    skills: List[str] = []
    unique_skills: List[str] = []
    bundles: List[str] = []
    area_of_training: Optional[str] = None
    suitable_job_roles: Optional[str] = None
    external_accreditations: List[str] = []
    objective: Optional[str] = None
    content: Optional[str] = None


class CourseDetail(CourseItem):
    """Detailed course information from the individual-course API."""
    entry_requirement: Optional[str] = None
    contact_persons: List[Dict[str, Any]] = []
    runs: List[Dict[str, Any]] = []
    faculty_name: Optional[str] = None
    specialisation: Optional[str] = None


class CourseSearchOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[CourseItem]


# ---------- Recommendation models ----------
class ResumePayload(BaseModel):
    Name: Optional[str] = None
    Skills: List[str] = []
    Education: Optional[List[Dict[str, Any]]] = None
    Goal: Optional[str] = None
    Experience: Optional[str] = None
    Industry: Optional[str] = None
    SkillGaps: Optional[List[str]] = []
    ExistingSkillLevel: Optional[Dict[str, str]] = {}


class RecommendReq(BaseModel):
    resume: ResumePayload
    page_size: int = 50
    budget_max: Optional[float] = None
    duration_max_hours: Optional[float] = None
    top_k: int = 5
    area_of_training: Optional[str] = None
    support_codes: Optional[List[str]] = None
    include_bundles: bool = True
    focus_on_gaps: bool = True


class RecItem(CourseItem):
    score: float
    score_breakdown: Dict[str, float]
    skill_gap_coverage: float
    existing_skill_overlap: float
    recommendation_reason: str


class RecommendOut(BaseModel):
    query_terms: List[str]
    items: List[RecItem]
    used_filters: Dict[str, Any]
    skill_gap_analysis: Dict[str, Any]
    debug_info: Optional[Dict[str, Any]] = None


# ---------- Resume scoring models ----------
class ResumeScoreBreakdown(BaseModel):
    contact_info: float = Field(description="Quality of contact information")
    summary_objective: float = Field(description="Quality of summary/objective section")
    experience: float = Field(description="Quality of work experience section")
    education: float = Field(description="Quality of education section")
    skills: float = Field(description="Quality of skills section")
    formatting: float = Field(description="Overall formatting and structure")
    keywords: float = Field(description="Industry-relevant keywords")
    quantifiable_achievements: float = Field(description="Presence of metrics and achievements")


class ResumeScore(BaseModel):
    overall_score: float = Field(description="Overall score out of 100")
    grade: str = Field(description="Letter grade (A+, A, B+, B, C+, C, D, F)")
    breakdown: ResumeScoreBreakdown
    strengths: List[str] = Field(description="Key strengths identified")
    improvement_areas: List[str] = Field(description="Areas for improvement")
    detailed_feedback: str = Field(description="Comprehensive feedback")
    industry_alignment: Optional[str] = Field(description="How well aligned with target industry")
    extracted_skills: List[str] = Field(description="Skills extracted from resume", default=[])


class ResumeHelperSuggestion(BaseModel):
    section: str = Field(description="Resume section (e.g., Experience, Skills, Summary)")
    current_text: Optional[str] = Field(default=None, description="Current text if provided")
    suggested_improvement: str = Field(description="Improved version")
    explanation: str = Field(description="Why this improvement helps")
    impact_level: str = Field(description="High/Medium/Low impact improvement")


class ResumeHelperResponse(BaseModel):
    suggestions: List[ResumeHelperSuggestion]
    overall_strategy: str = Field(description="Overall improvement strategy")
    priority_order: List[str] = Field(description="Order to tackle improvements")
