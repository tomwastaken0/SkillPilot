"""SkillPilot API — thin FastAPI layer.

All business logic lives in the app/ package:
  app.agent   - agentic course recommendation (tool-calling loop)
  app.resume  - resume scoring + improvement helper
  app.ssg     - SSG-WSG course directory client
  app.scoring - deterministic scoring
  app.llm     - provider-agnostic (OpenAI-compatible) LLM client

This module only wires HTTP routes to that logic and preserves the API contract
consumed by the React frontend (index.html).
"""
import os
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

load_dotenv()

from app import agent, resume as resume_mod, ssg  # noqa: E402
from app.schemas import (  # noqa: E402
    CategoriesOut, Category, CourseDetail, CourseSearchOut, CourseTag, CourseTagsOut,
    RecommendOut, RecommendReq, ResumeHelperResponse, ResumeScore, Rolodex,
)
from app.ssg import SSGError, ssg_get  # noqa: E402
from settings import settings  # noqa: E402

app = FastAPI(title="SkillPilot Course Recommendation API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)


@app.exception_handler(SSGError)
async def _ssg_error_handler(_request: Request, exc: SSGError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# --------------------------------------------------------------------------- #
# Frontend + health
# --------------------------------------------------------------------------- #
@app.get("/")
async def serve_index():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    return FileResponse(html_path)


@app.get("/ping")
def ping():
    return {"ok": True, "message": "API server is healthy"}


@app.get("/whoami")
def whoami():
    return {
        "env": settings.ENV,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.LLM_MODEL,
        "ssg_base": str(settings.SSG_API_BASE),
        "api_version": settings.SSG_API_VERSION,
    }


@app.get("/api/info")
async def api_info():
    return {
        "message": "SkillPilot Course Recommendation API",
        "version": "3.0",
        "status": "running",
        "llm": {"provider": settings.LLM_PROVIDER, "model": settings.LLM_MODEL},
        "features": [
            "Agentic course recommendation (tool-calling loop)",
            "Course search with advanced filtering",
            "Individual course details, tags, and categories",
            "Resume scoring and improvement helper",
            "Provider-agnostic LLM (Groq / Ollama / OpenRouter / any OpenAI-compatible API)",
        ],
    }


# --------------------------------------------------------------------------- #
# Resume endpoints
# --------------------------------------------------------------------------- #
async def _read_pdf(file: UploadFile) -> str:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    text = resume_mod.extract_text_from_pdf(await file.read())
    if not text:
        raise HTTPException(status_code=400, detail="Could not extract text from PDF")
    return text


@app.post("/resume/score", response_model=ResumeScore)
async def score_resume(
    file: UploadFile = File(..., description="Resume PDF file"),
    target_role: Optional[str] = None,
    target_industry: Optional[str] = None,
    experience_level: Optional[str] = None,
    specific_concerns: Optional[str] = None,
):
    resume_text = await _read_pdf(file)
    try:
        return await resume_mod.analyze_resume(resume_text, target_role, target_industry)
    except (ValueError, KeyError) as err:
        raise HTTPException(status_code=502, detail=f"Could not parse resume analysis: {err}")


@app.post("/resume/helper", response_model=ResumeHelperResponse)
async def resume_helper(
    file: UploadFile = File(..., description="Resume PDF file"),
    target_role: Optional[str] = None,
    target_industry: Optional[str] = None,
    specific_sections: Optional[str] = None,
    current_content: Optional[str] = None,
):
    resume_text = await _read_pdf(file)
    try:
        return await resume_mod.resume_helper(
            resume_text, target_role, target_industry, specific_sections, current_content
        )
    except (ValueError, KeyError) as err:
        raise HTTPException(status_code=502, detail=f"Could not parse resume helper response: {err}")


# --------------------------------------------------------------------------- #
# Recommendation
# --------------------------------------------------------------------------- #
@app.post("/recommend", response_model=RecommendOut)
async def recommend(req: RecommendReq):
    return await agent.recommend(req)


@app.options("/recommend")
async def recommend_options():
    return {"message": "OK"}


# --------------------------------------------------------------------------- #
# Course catalog endpoints
# --------------------------------------------------------------------------- #
@app.get("/categories", response_model=CategoriesOut)
async def get_categories(keyword: str = Query(..., min_length=3, description="Min 3 chars")):
    raw = await ssg_get("/courses/categories", params={"keyword": keyword})
    data = raw.get("data") or {}
    categories_raw = data.get("categories") or []
    meta = raw.get("meta") or {}
    total = int(meta.get("total") or len(categories_raw))

    categories: List[Category] = []
    for row in categories_raw:
        rolodex = row.get("rolodex") or {}
        categories.append(Category(
            id=int(row.get("id")),
            name=str(row.get("name")),
            display=bool(row.get("display")),
            rolodex=Rolodex(
                display=bool(rolodex.get("display")),
                numberOfLetters=int(rolodex.get("numberOfLetters") or 1),
            ),
        ))
    return CategoriesOut(count=total, categories=categories)


@app.get("/course-tags", response_model=CourseTagsOut)
async def get_course_tags(sort_by: int = Query(0, description="0=by text, 1=by count")):
    raw = await ssg_get("/courses/tags", params={"sortBy": sort_by}, api_version="v1")
    data = raw.get("data") or {}
    tags_raw = data.get("tags") or []
    meta = raw.get("meta") or {}
    total = int(meta.get("total") or len(tags_raw))
    tags = [CourseTag(text=t["text"], count=t["count"]) for t in tags_raw]
    return CourseTagsOut(tags=tags, total=total)


@app.get("/course/{course_ref}", response_model=CourseDetail)
async def get_course_detail(course_ref: str, include_expired: bool = Query(True)):
    detail = await ssg.get_course_detail_raw(course_ref, include_expired=include_expired)
    if not detail:
        raise HTTPException(status_code=404, detail="Course not found")
    return ssg.extract_course_detail(detail)


@app.get("/courses", response_model=CourseSearchOut)
async def search_courses(
    page_size: int = Query(10, ge=1, le=50, alias="pageSize"),
    page: int = Query(0, ge=0),
    keyword: Optional[str] = Query(None, min_length=3, description="Keyword search"),
    taggingCodes: Optional[str] = Query(None, description="Comma-separated tagging codes"),
    courseSupportEndDate: Optional[str] = Query(None, regex=r"^\d{8}$", description="YYYYMMDD"),
    retrieveType: Optional[str] = Query(None, regex=r"^(FULL|DELTA)$", description="Required with taggingCodes"),
    lastUpdateDate: Optional[str] = Query(None, regex=r"^\d{8}$", description="YYYYMMDD"),
):
    if bool(keyword) == bool(taggingCodes):
        raise HTTPException(status_code=400, detail="Provide either keyword OR taggingCodes.")

    params = {"pageSize": page_size, "page": page}
    if keyword:
        params["keyword"] = keyword
    else:
        params["taggingCodes"] = taggingCodes
        if not (courseSupportEndDate and retrieveType):
            raise HTTPException(status_code=400, detail="courseSupportEndDate and retrieveType required with taggingCodes.")
        params["courseSupportEndDate"] = courseSupportEndDate
        params["retrieveType"] = retrieveType
        if retrieveType == "DELTA":
            if not lastUpdateDate:
                raise HTTPException(status_code=400, detail="lastUpdateDate required when retrieveType=DELTA.")
            params["lastUpdateDate"] = lastUpdateDate

    raw = await ssg_get("/courses/directory", params=params)
    data = raw.get("data") or {}
    meta = data.get("meta") or {}
    total = int(meta.get("total") or 0)
    items = [ssg.extract_course_item(r) for r in (data.get("courses") or [])]
    return CourseSearchOut(total=total, page=page, page_size=page_size, items=items)


@app.get("/test-search")
async def test_search(keyword: str = Query("python", description="Test keyword")):
    """Quick SSG connectivity check."""
    try:
        courses = await ssg.search_courses(keyword, page_size=10)
        return {
            "success": True,
            "keyword_used": keyword,
            "courses_count": len(courses),
            "sample_titles": [c.get("title") for c in courses[:3]],
        }
    except SSGError as err:
        return {"success": False, "error": err.detail, "keyword_used": keyword}


if __name__ == "__main__":
    import threading
    import time
    import webbrowser

    import uvicorn

    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=open_browser, daemon=True).start()
    # reload=True auto-restarts the server when you edit backend code.
    # It requires the app passed as an import string ("main:app"), not the object.
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
