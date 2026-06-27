"""Resume PDF extraction and LLM-backed analysis/helper logic."""
from __future__ import annotations

import re
from io import BytesIO
from typing import Optional

import PyPDF2

from app import llm, prompts
from app.schemas import ResumeHelperResponse, ResumeScore


def extract_text_from_pdf(pdf_content: bytes) -> Optional[str]:
    """Extract plain text from PDF bytes, or None if it can't be read."""
    try:
        reader = PyPDF2.PdfReader(BytesIO(pdf_content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        text = text.strip()
        return text or None
    except Exception as err:  # noqa: BLE001 - upstream PDFs are unpredictable
        print(f"[resume] error reading PDF: {err}")
        return None


async def analyze_resume(
    resume_text: str,
    target_role: Optional[str] = None,
    target_industry: Optional[str] = None,
) -> ResumeScore:
    """Score a resume and return a validated ResumeScore."""
    raw = await llm.chat(
        prompts.resume_analysis_user(resume_text, target_role, target_industry),
        system=prompts.RESUME_ANALYSIS_SYSTEM,
        json_mode=True,
    )
    data = llm.extract_json(raw)

    # Preserve newlines in feedback but strip control characters.
    if isinstance(data.get("detailed_feedback"), str):
        data["detailed_feedback"] = re.sub(
            r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", "", data["detailed_feedback"]
        )
    # industry_alignment must be a string (models sometimes emit an object).
    if isinstance(data.get("industry_alignment"), dict):
        data["industry_alignment"] = "; ".join(str(v) for v in data["industry_alignment"].values())

    return ResumeScore(**data)


async def resume_helper(
    resume_text: str,
    target_role: Optional[str] = None,
    target_industry: Optional[str] = None,
    specific_sections: Optional[str] = None,
    current_content: Optional[str] = None,
) -> ResumeHelperResponse:
    """Return actionable resume-improvement suggestions."""
    raw = await llm.chat(
        prompts.resume_helper_user(
            resume_text, target_role, target_industry, specific_sections, current_content
        ),
        system=prompts.RESUME_HELPER_SYSTEM,
        json_mode=True,
    )
    data = llm.extract_json(raw)
    return ResumeHelperResponse(**data)
