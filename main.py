
# Standard library imports
import asyncio
import json
import math
import os
import random
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional

# Third-party imports
import boto3
import httpx
import PyPDF2
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Local imports (you need to create this file)
from settings import settings


app = FastAPI(title="Enhanced SSG Course Recommendation API", version="2.5")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)


TIMEOUT = httpx.Timeout(12.0, connect=5.0)
_token_cache = {"access_token": None, "expires_at": datetime.min}

STOP = set("a an the and or for of to in on with by from at as is are was were be been being your you my me our their his her it they we".split())

# Initialize Bedrock client for resume analysis
def get_bedrock_client():
    """Initialize Bedrock client with environment variables"""
    try:
        return boto3.client(
            service_name='bedrock-runtime',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            aws_session_token=os.getenv('AWS_SESSION_TOKEN'),
            region_name='us-east-1'
        )
    except Exception as e:
        print(f"Warning: Could not initialize Bedrock client: {e}")
        return None
    
# Generate serach terms with AI    
def generate_search_terms_with_ai(goal: str, industry: Optional[str] = None) -> List[str]:
    """Use AI to generate relevant search terms for any career goal"""
    
    if not goal:
        return ["professional", "development"]
    
    system_prompt = """
    You are an expert career counselor who understands how to find relevant courses for any career goal.
    Generate 6-8 search terms that would help find courses relevant to the user's career goal.
    Focus on skills, knowledge areas, certifications, and industry-specific terms.
    """
    
    industry_context = f" in the {industry} industry" if industry else ""
    
    user_prompt = f"""
    Career Goal: {goal}{industry_context}

    Analyze this career goal and generate SMART search terms that will find the most relevant SkillsFuture courses.

    ANALYSIS REQUIRED:
    1. What specific skills are needed for this career goal?
    2. What certifications or qualifications are typically required?
    3. What tools, software, or technologies are commonly used?
    4. What are the foundational skills someone would need to build first?
    5. What are advanced skills for career progression?

    SEARCH STRATEGY:
    - Include both broad category terms (e.g., "data science") and specific skill terms (e.g., "python programming")
    - Consider skill progression levels (beginner to advanced)
    - Include industry-standard certifications and tools
    - Think about Singapore's specific industry landscape

    Return a JSON array of 8-10 search terms ranked by importance:
    ["most_important_term", "second_most_important", ...]

    Examples:
    - Goal "become a chef": ["culinary", "cooking", "food safety", "kitchen management", "pastry", "nutrition", "restaurant operations", "hospitality"]
    - Goal "data scientist": ["data science", "python", "machine learning", "statistics", "sql", "data visualization", "analytics", "artificial intelligence"]
    - Goal "digital marketer": ["digital marketing", "social media", "google analytics", "content marketing", "seo", "paid advertising", "marketing automation", "conversion optimization"]

    Be specific and strategic about term selection.
    """
    
    try:
        response = get_bedrock_completion(user_prompt, system_prompt)
        response = response.strip()
        
        # Clean up the response
        if response.startswith('```json'):
            response = response[7:-3]
        elif response.startswith('```'):
            response = response[3:-3]
        elif response.startswith('[') and response.endswith(']'):
            pass  # Already clean
        else:
            # Try to extract JSON array from response
            import re
            json_match = re.search(r'\[.*?\]', response)
            if json_match:
                response = json_match.group()
        
        terms = json.loads(response)
        
        # Validate and clean terms
        valid_terms = []
        for term in terms:
            if isinstance(term, str) and len(term.strip()) > 2:
                valid_terms.append(term.strip().lower())
        
        print(f"[DEBUG] AI generated search terms for '{goal}': {valid_terms}")
        return valid_terms[:8]  # Limit to 8 terms
        
    except Exception as e:
        print(f"[DEBUG] AI search term generation failed: {e}")
        # Fallback to basic term extraction
        return extract_basic_terms_from_goal(goal, industry)

# Extract serach terms with AI  
def extract_basic_terms_from_goal(goal: str, industry: Optional[str] = None) -> List[str]:
    """Fallback method to extract search terms from goal text"""
    
    terms = []
    goal_lower = goal.lower()
    
    # Extract meaningful words from the goal
    words = re.findall(r'\b[a-zA-Z]{3,}\b', goal_lower)
    
    # Filter out common words
    stop_words = {
        'want', 'become', 'work', 'career', 'job', 'position', 'role', 'professional',
        'get', 'find', 'looking', 'seeking', 'interested', 'pursue', 'transition',
        'and', 'the', 'for', 'with', 'into', 'from', 'that', 'this', 'have',
        'will', 'would', 'could', 'should', 'can', 'may', 'might'
    }
    
    meaningful_words = [word for word in words if word not in stop_words and len(word) > 3]
    terms.extend(meaningful_words[:6])
    
    # Add industry terms if provided
    if industry:
        industry_words = re.findall(r'\b[a-zA-Z]{3,}\b', industry.lower())
        terms.extend([word for word in industry_words if word not in stop_words][:2])
    
    # Ensure we have at least some terms
    if not terms:
        terms = ["professional", "development", "training"]
    
    print(f"[DEBUG] Fallback search terms for '{goal}': {terms}")
    return terms[:8]

def get_targeted_resume_analysis(resume_text: str, target_role: Optional[str] = None, 
                                target_industry: Optional[str] = None) -> str:
    """Generate targeted resume analysis based on specific career goals"""
    
    system_prompt = """
    You are an expert career counselor and resume reviewer specializing in Singapore's job market.
    You excel at analyzing career transitions and identifying specific gaps between current backgrounds and target roles.
    For ANY target role provided, you must analyze the transition requirements dynamically.
    ALWAYS return valid JSON - never refuse or ask for clarification.
    """
    
    # Build context for specific career analysis
    career_context = ""
    if target_role:
        career_context += f"Target Role: {target_role}\n"
    if target_industry:
        career_context += f"Target Industry: {target_industry}\n"
    
    # Universal transition analysis - let AI determine requirements
    if target_role:
        universal_analysis_prompt = f"""
        CAREER TRANSITION ANALYSIS FOR: {target_role}
        
        CRITICAL: This person wants to become a {target_role}. Your analysis must focus on this career transition.
        
        1. CURRENT vs TARGET ROLE ANALYSIS:
        - What does their current background show?
        - What are the specific requirements for {target_role} roles in Singapore?
        - What are the gaps between current skills and {target_role} requirements?
        - What certifications, courses, or experience do they need for {target_role}?
        
        2. TRANSITION STRATEGY FOR {target_role}:
        - Immediate steps to start transitioning to {target_role}
        - Specific SkillsFuture courses they should take for {target_role}
        - Industry certifications or qualifications needed for {target_role}
        - Practical experience requirements (internships, projects, etc.) for {target_role}
        - Networking and professional development specific to {target_role}
        
        3. {target_role} MARKET CONTEXT IN SINGAPORE:
        - Job market demand for {target_role} in Singapore
        - Salary expectations and career progression for {target_role}
        - Key employers and industries hiring {target_role}
        - Local certification bodies and training providers for {target_role}
        
        4. ACTIONABLE RECOMMENDATIONS FOR {target_role}:
        - Specific courses to take (prioritize SkillsFuture options)
        - Certifications to pursue for {target_role}
        - Experience-building opportunities in {target_role}
        - Timeline for transition to {target_role}
        
        Be specific about what they need to do to successfully transition to {target_role}.
        Focus on actionable advice specific to {target_role}, not generic feedback.
        Mention specific SkillsFuture courses if relevant to {target_role}.
        """
    else:
        universal_analysis_prompt = """
        GENERAL PROFESSIONAL ANALYSIS:
        Since no target role is specified, provide:
        - Overall professional assessment and resume quality
        - Identification of strongest skill areas and experience domains
        - 2-3 potential career paths based on current background
        - Transferable skills and growth opportunities
        - Educational background utilization
        - Quantifiable achievements and areas for improvement
        """
    
    user_prompt = f"""
    Analyze this resume and provide comprehensive scoring and feedback.
    
    {career_context}
    
    {universal_analysis_prompt}
    
    <resume>
    {resume_text}
    </resume>
    
    CRITICAL INSTRUCTIONS:
    1. You must ALWAYS return valid JSON - never refuse or ask for clarification
    2. Extract a comprehensive list of technical and professional skills from the resume text
    3. If a target role is specified, your analysis MUST be specific to that exact role:
       - Research what {target_role if target_role else 'the role'} actually requires
       - Identify specific gaps between current background and role requirements
       - Provide concrete, actionable transition steps
       - Address industry-specific challenges and requirements
       - Consider Singapore market context
    4. Be specific, not generic - research the actual requirements for the target role
    5. If no target role specified, provide general analysis with career path suggestions
    6. IMPORTANT: industry_alignment must be a single string, not an object or dictionary
    
    Return ONLY valid JSON in this exact format:
    {{
        "overall_score": 75.5,
        "grade": "B+",
        "breakdown": {{
            "contact_info": 90.0,
            "summary_objective": 70.0,
            "experience": 65.0,
            "education": 80.0,
            "skills": 60.0,
            "formatting": 85.0,
            "keywords": 45.0,
            "quantifiable_achievements": 55.0
        }},
        "strengths": [
            "List specific strengths from the resume",
            "Focus on transferable skills if career transition",
            "Highlight relevant experience and education",
            "Note problem-solving and analytical abilities"
        ],
        "improvement_areas": [
            "Specific to target role: mention exact certifications needed",
            "Identify experience gaps and how to fill them",
            "Note skill development requirements",
            "Suggest portfolio or project needs"
        ],
        "detailed_feedback": "Format your response as clean text with section headers and bullet points. Use this exact structure without any special characters or symbols:\\n\\nCURRENT STRENGTHS:\\n- Complete sentence describing first strength\\n- Complete sentence describing second strength\\n- Complete sentence describing third strength\\n\\nGAPS TO ADDRESS:\\n- Complete sentence describing first gap\\n- Complete sentence describing second gap\\n- Complete sentence describing third gap\\n\\nRECOMMENDED ACTIONS:\\n- Immediate actions in 1-3 months\\n- Medium-term goals for 3-12 months\\n- Long-term objectives for 1-2 years\\n\\nCAREER ALIGNMENT:\\n- Assessment of career fit and potential paths\\n- Specific role recommendations\\n- Market considerations\\n\\nRules: No asterisks, no bullet symbols, no special formatting. Each bullet point must be one complete coherent sentence. Use simple dashes for bullets.",
        "industry_alignment": "Assessment of alignment with target role and industry as a single descriptive string"
        "extracted_skills": [
            "Python Programming",
            "Project Management",
            "Data Analysis",
            "Microsoft Excel",
            "Communication Skills",
            "Leadership",
            "Art Curating",
            "Microbiology",
            "Lab Techniques"
        ]
    }}
    
    CRITICAL: The industry_alignment field must be a single string describing the alignment, 
    NOT an object or dictionary. Examples:
    - "Strong alignment with data science field due to analytical background"
    - "Moderate alignment requiring additional healthcare certifications"
    - "Limited alignment - significant career transition needed"
    
    Scoring Guidelines (adjust based on target role alignment):
    - Contact Info (0-100): Completeness and professionalism
    - Summary/Objective (0-100): Clarity, relevance to target role, transition strategy
    - Experience (0-100): Relevance to target role and transferable skills
    - Education (0-100): Relevance to target career path and additional needs
    - Skills (0-100): Alignment with target role requirements and gaps
    - Formatting (0-100): Structure, readability, and consistency
    - Keywords (0-100): Industry-specific terms for target role (score low if different industry)
    - Quantifiable Achievements (0-100): Use of metrics and measurable results
    
    Grades: A+ (95-100), A (90-94), B+ (85-89), B (80-84), C+ (75-79), C (70-74), D (60-69), F (<60)
    """
    
    return get_bedrock_completion(user_prompt, system_prompt)


def generate_course_recommendation_reason(course_title: str, course_objective: str, target_role: str, 
                                        skill_gap_coverage: float, existing_overlap: float, score: float) -> str:
    """Generate specific explanation for any career goal"""
    
    if not target_role:
        return f"Professional development opportunity with {skill_gap_coverage:.1%} skill gap coverage."
    
    # Use the AI-powered reason generation
    return generate_recommendation_reason_ai(target_role, course_title, course_objective, skill_gap_coverage, score)


def _tok(s: str):
    return [w for w in re.findall(r"[A-Za-z][A-Za-z0-9+\-_.]*", s.lower()) if w not in STOP and len(w) > 1]

def _bow(s: str) -> Counter:
    return Counter(_tok(s))

def _cos(a: Counter, b: Counter) -> float:
    if not a or not b: return 0.0
    inter = set(a) & set(b)
    num = sum(a[t]*b[t] for t in inter)
    den = math.sqrt(sum(v*v for v in a.values())) * math.sqrt(sum(v*v for v in b.values()))
    return (num/den) if den else 0.0

def _skill_overlap(existing_skills: List[str], course_content: str) -> float:
    """Calculate how much the course content overlaps with existing skills (0-1)"""
    if not existing_skills or not course_content:
        return 0.0
    
    existing_bow = Counter()
    for skill in existing_skills:
        existing_bow.update(_tok(skill))
    
    course_bow = _bow(course_content)
    overlap = _cos(existing_bow, course_bow)
    return overlap

def _extract_skill_gaps(existing_skills: List[str], target_skills: List[str]) -> List[str]:
    """Extract skills that are in target but not well covered in existing"""
    existing_tokens = set()
    for skill in existing_skills:
        existing_tokens.update(_tok(skill))
    
    gaps = []
    for target_skill in target_skills:
        target_tokens = set(_tok(target_skill))
        # If less than 30% of target skill tokens are in existing skills, consider it a gap
        if len(target_tokens & existing_tokens) / max(len(target_tokens), 1) < 0.3:
            gaps.append(target_skill)
    
    return gaps

def calculate_relevance_bonus_ai(goal: str, course_title: str, course_objective: str) -> float:
    """Calculate relevance bonus for any career goal"""
    if not goal:
        return 0.0
    
    goal_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', goal.lower()))
    title_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', course_title.lower()))
    objective_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', course_objective.lower()))
    
    title_overlap = len(goal_words & title_words) / max(len(goal_words), 1)
    objective_overlap = len(goal_words & objective_words) / max(len(goal_words), 1)
    
    return min(1.0, (title_overlap * 0.6 + objective_overlap * 0.4))

def generate_recommendation_reason_ai(goal: str, course_title: str, course_objective: str, 
                                    skill_gap_coverage: float, content_similarity: float) -> str:
    """Generate human-friendly reasons"""
    if not goal:
        return "Provides valuable professional development opportunities."
    
    reasons = []
    title_lower = course_title.lower()
    
    if any(word in title_lower for word in ['certification', 'exam', 'certified']):
        reasons.append("Industry-recognized certification")
    elif any(word in title_lower for word in ['professional', 'advanced']):
        reasons.append("Advanced training for professionals")
    elif any(word in title_lower for word in ['fundamental', 'basic', 'introduction']):
        reasons.append("Builds essential foundation skills")
    else:
        reasons.append("Directly relevant to your career objectives")
    
    if skill_gap_coverage > 0.6:
        reasons.append("Addresses critical skill gaps")
    elif content_similarity > 0.5:
        reasons.append("Strong alignment with your goals")
    else:
        reasons.append("Expands your professional skill set")
    
    return " • ".join(reasons[:2])

# ---------- OAuth2 client-credentials token (cached) ----------
async def get_token() -> str:
    if _token_cache["access_token"] and datetime.utcnow() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        resp = await c.post(
            str(settings.SSG_TOKEN_URL),
            data={"grant_type": "client_credentials"},
            auth=(settings.SSG_CLIENT_ID, settings.SSG_CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise HTTPException(status_code=502, detail=f"No access_token in SSG response: {resp.text}")
        _token_cache["access_token"] = token
        _token_cache["expires_at"] = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 300))
        return token

# ---------- Enhanced Pydantic output models ----------
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
    """Detailed course information from individual course API"""
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

class ResumePayload(BaseModel):
    Name: Optional[str] = None
    Skills: List[str] = []
    Education: Optional[List[Dict[str, Any]]] = None
    Goal: Optional[str] = None
    Experience: Optional[str] = None  # Added for better matching
    Industry: Optional[str] = None    # Added for industry-specific courses
    # New fields for better skill gap analysis
    SkillGaps: Optional[List[str]] = []  # Skills user wants to learn
    ExistingSkillLevel: Optional[Dict[str, str]] = {}  # skill -> proficiency level

class RecommendReq(BaseModel):
    resume: ResumePayload
    page_size: int = 50  # Increased for better filtering
    budget_max: Optional[float] = None
    duration_max_hours: Optional[float] = None
    top_k: int = 5
    # Enhanced filtering options
    area_of_training: Optional[str] = None
    support_codes: Optional[List[str]] = None  # e.g., ["SFC", "UTAP"]
    include_bundles: bool = True
    # New option to prioritize skill gaps over existing skills
    focus_on_gaps: bool = True

class RecItem(CourseItem):
    score: float
    score_breakdown: Dict[str, float]  # Show individual scores
    # New fields for transparency
    skill_gap_coverage: float  # How well it covers skill gaps
    existing_skill_overlap: float  # How much it overlaps with existing skills
    recommendation_reason: str  # Why this course was recommended

class RecommendOut(BaseModel):
    query_terms: List[str]
    items: List[RecItem]
    used_filters: Dict[str, Any]
    # New analysis fields
    skill_gap_analysis: Dict[str, Any]
    # Debug information
    debug_info: Optional[Dict[str, Any]] = None

# ---------- NEW RESUME SCORING MODELS ----------
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
    current_text: Optional[str] = Field(description="Current text if provided")
    suggested_improvement: str = Field(description="Improved version")
    explanation: str = Field(description="Why this improvement helps")
    impact_level: str = Field(description="High/Medium/Low impact improvement")

class ResumeHelperResponse(BaseModel):
    suggestions: List[ResumeHelperSuggestion]
    overall_strategy: str = Field(description="Overall improvement strategy")
    priority_order: List[str] = Field(description="Order to tackle improvements")

def extract_text_from_pdf(pdf_content: bytes) -> Optional[str]:
    """Extract text from PDF bytes"""
    try:
        pdf_file = BytesIO(pdf_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        full_text = ""
        for page in pdf_reader.pages:
            text = page.extract_text()
            full_text += text + "\n"
        return full_text.strip()
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None



def get_bedrock_completion(prompt: str, system_prompt: Optional[str] = None) -> str:
    """Get completion from Claude via Bedrock with robust throttling protection"""
    bedrock_client = get_bedrock_client()
    if not bedrock_client:
    # Fallback mock response for demo purposes when AWS credentials are not available
        print("[INFO] Using mock response - AWS credentials not configured")
        
        if "resume" in prompt.lower() and "score" in prompt.lower():
            return '''{
                "overall_score": 82.3,
                "grade": "B+",
                "breakdown": {
                    "contact_info": 90.0,
                    "summary_objective": 75.0,
                    "experience": 85.0,
                    "education": 80.0,
                    "skills": 88.0,
                    "formatting": 82.0,
                    "keywords": 70.0,
                    "quantifiable_achievements": 68.0
                },
                "strengths": [
                    "Professional contact information clearly displayed",
                    "Clear work experience progression shown",
                    "Strong technical skills section with relevant technologies",
                    "Good overall formatting and structure"
                ],
                "improvement_areas": [
                    "Add specific metrics and quantifiable achievements to work experience",
                    "Strengthen professional summary with more impact-focused language",
                    "Include more industry-specific keywords for ATS optimization",
                    "Highlight leadership examples and measurable business impact"
                ],
                "detailed_feedback": "CURRENT STRENGTHS:\\n- Strong analytical background demonstrated through data analysis projects\\n- Excellent quantifiable achievements including inventory management\\n- Technical versatility with programming skills\\n\\nGAPS TO ADDRESS:\\n- Missing professional summary that would frame experience\\n- Limited civilian professional experience\\n- Skills section needs better organization\\n\\nRECOMMENDED ACTIONS:\\n- Immediate (1-3 months): Add professional summary, reorganize skills\\n- Medium-term (3-12 months): Pursue internships, gain certifications\\n- Long-term (1-2 years): Develop specialized expertise\\n\\nCAREER ALIGNMENT:\\n- Strong potential for data analytics roles\\n- Good foundation for engineering positions",
                "industry_alignment": "Good alignment for technical roles with room for keyword optimization"
            }'''
        
        elif "suggestions" in prompt.lower():
            return '''{
                "suggestions": [
                    {
                        "section": "Summary",
                        "current_text": "Professional with experience in various projects",
                        "suggested_improvement": "Results-driven professional with 3+ years of experience delivering data-driven solutions that improved operational efficiency by 30%.",
                        "explanation": "More specific and impact-focused language",
                        "impact_level": "High"
                    }
                ],
                "overall_strategy": "Focus on quantifying achievements with specific metrics",
                "priority_order": ["Experience", "Summary", "Skills", "Education"]
            }'''
        
        return "Mock response for testing - please configure AWS credentials for full functionality"
    
    max_retries = 8
    base_delay = 10
    
    for attempt in range(max_retries):
        try:
            modelId = 'us.anthropic.claude-3-7-sonnet-20250219-v1:0'
            inference_config = {
                "temperature": 0.2,
                "maxTokens": 5000
            }
            additional_model_fields = {"top_p": 0.8}
            
            converse_api_params = {
                "modelId": modelId,
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": inference_config,
                "additionalModelRequestFields": additional_model_fields
            }
            
            if system_prompt:
                converse_api_params["system"] = [{"text": system_prompt}]
            
            response = bedrock_client.converse(**converse_api_params)
            return response['output']['message']['content'][0]['text']
            
        except Exception as err:
            if "ThrottlingException" in str(err) or "TooManyRequestsException" in str(err):
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(1, 5)
                    print(f"Rate limited (attempt {attempt + 1}/{max_retries}), waiting {delay:.1f} seconds...")
                    time.sleep(delay)  # This is OK here since it's in the retry loop
                    continue
                else:
                    print("All retries exhausted, using fallback response")
                    return get_fallback_response(prompt)
            else:
                print(f"Error calling Bedrock: {err}")
                raise HTTPException(status_code=503, detail=f"Error calling Bedrock: {str(err)}")

def get_fallback_response(prompt: str) -> str:
    """Fallback response when Bedrock is completely unavailable"""
    if "resume" in prompt.lower() and "score" in prompt.lower():
        return '''{
            "overall_score": 78.5,
            "grade": "C+",
            "breakdown": {
                "contact_info": 85.0,
                "summary_objective": 40.0,
                "experience": 75.0,
                "education": 90.0,
                "skills": 70.0,
                "formatting": 80.0,
                "keywords": 75.0,
                "quantifiable_achievements": 85.0
            },
            "strengths": ["Strong academic credentials", "Quantifiable achievements", "Technical skills"],
            "improvement_areas": ["Add professional summary", "Gain more experience", "Organize skills better"],
            "detailed_feedback": "CURRENT STRENGTHS:\\n- Strong analytical background\\n- Good technical skills\\n\\nGAPS TO ADDRESS:\\n- Need professional summary\\n- Limited work experience\\n\\nRECOMMENDED ACTIONS:\\n- Add summary section\\n- Pursue internships\\n\\nCAREER ALIGNMENT:\\n- Good potential for technical roles",
            "industry_alignment": "Moderate alignment with technical fields"
        }'''
    return "Fallback response - please try again in a few minutes"

def _build_enhanced_query_terms(skills: List[str], goal: Optional[str], 
                               experience: Optional[str] = None, industry: Optional[str] = None,
                               skill_gaps: Optional[List[str]] = None, 
                               focus_on_gaps: bool = True) -> List[str]:
    """Enhanced query term building using AI for any career goal"""
    
    if not goal:
        return ["professional", "development"]
    
    # Prioritize the stated career goal over existing skills
    ai_terms = generate_search_terms_with_ai(goal, industry)
    
    # If focusing on gaps and this is a career transition, heavily weight the goal
    if focus_on_gaps and goal:
        goal_words = re.findall(r'\b[a-zA-Z]{3,}\b', goal.lower())
        # Remove common transition words
        goal_words = [w for w in goal_words if w not in ['want', 'become', 'work', 'as', 'in', 'the']]
        
        # Combine AI terms with goal words, prioritizing goal
        combined_terms = goal_words[:4] + ai_terms[:4]
    else:
        combined_terms = ai_terms
    
    # Add skill gap terms if specified
    if skill_gaps:
        gap_terms = []
        for gap in skill_gaps[:2]:
            gap_words = re.findall(r'\b[a-zA-Z]{3,}\b', gap.lower())
            gap_terms.extend(gap_words[:2])
        combined_terms.extend(gap_terms)
    
    # Remove duplicates while preserving order
    unique_terms = []
    seen = set()
    for term in combined_terms:
        if term.lower() not in seen and len(term) > 2:
            unique_terms.append(term)
            seen.add(term.lower())
    
    return unique_terms[:8]

async def ssg_get(path: str, params: dict | None = None, api_version: str = None) -> dict:
    """Enhanced SSG API call with version control and better error handling"""
    token = await get_token()
    base = str(settings.SSG_API_BASE).rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    headers = {
        "Accept": "application/json",
        "x-api-version": api_version or settings.SSG_API_VERSION,
        "Authorization": f"Bearer {token}",
    }
    
    print(f"[DEBUG] Making API call to: {url}")
    print(f"[DEBUG] With params: {params}")
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(url, headers=headers, params=params)
        
        print(f"[DEBUG] API Response Status: {r.status_code}")
        print(f"[DEBUG] API Response Headers: {dict(r.headers)}")
        
        if r.status_code == 429:
            raise HTTPException(status_code=429, detail="Rate limited by SSG")
        try:
            r.raise_for_status()
            response_data = r.json()
            print(f"[DEBUG] API Response Keys: {list(response_data.keys()) if isinstance(response_data, dict) else 'Not a dict'}")
            if isinstance(response_data, dict) and 'data' in response_data:
                data = response_data['data']
                if isinstance(data, dict) and 'courses' in data:
                    print(f"[DEBUG] Number of courses returned: {len(data['courses'])}")
                    if data['courses']:
                        print(f"[DEBUG] First course title: {data['courses'][0].get('title', 'No title')}")
            return response_data
        except httpx.HTTPStatusError as e:
            print(f"[DEBUG] HTTP Error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=f"SSG error: {e.response.text}")

# ---------- Enhanced API Endpoints ----------
@app.get("/")
async def serve_index():
    import os
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    return FileResponse(html_path)

# ---------- ENHANCED RESUME SCORING ENDPOINTS ----------
@app.post("/resume/score", response_model=ResumeScore)
async def score_resume(
    file: UploadFile = File(..., description="Resume PDF file"),
    target_role: Optional[str] = None,
    target_industry: Optional[str] = None,
    experience_level: Optional[str] = None,
    specific_concerns: Optional[str] = None
):
    """Score a resume with enhanced career-specific analysis"""
    
    await asyncio.sleep(2)
    # Validate file
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Extract text
    pdf_content = await file.read()
    resume_text = extract_text_from_pdf(pdf_content)
    
    if not resume_text:
        raise HTTPException(status_code=400, detail="Could not extract text from PDF")
    
    # Use enhanced analysis function
    response = get_targeted_resume_analysis(resume_text, target_role, target_industry)
    
    try:
        response = response.strip()
        if response.startswith('```json'):
            response = response[7:-3]
        elif response.startswith('```'):
            response = response[3:-3]
        
        # Parse JSON first
        temp_result = json.loads(response)
        
        # Minimal cleaning - preserve line breaks but remove control characters
        if 'detailed_feedback' in temp_result:
            feedback = temp_result['detailed_feedback']
            
            # Only remove problematic control characters, keep \n
            feedback = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', feedback)
            
            temp_result['detailed_feedback'] = feedback
        
        result = temp_result
        return ResumeScore(**result)
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        print(f"Raw response: {response}")
        raise HTTPException(status_code=500, detail="Error parsing resume analysis")

@app.post("/resume/helper", response_model=ResumeHelperResponse)
async def resume_helper(
    file: UploadFile = File(..., description="Resume PDF file"),
    target_role: Optional[str] = None,
    target_industry: Optional[str] = None,
    specific_sections: Optional[str] = None,
    current_content: Optional[str] = None
):
    """Get specific suggestions to improve resume sections"""
    
    # Validate file
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Extract text
    pdf_content = await file.read()
    resume_text = extract_text_from_pdf(pdf_content)
    
    if not resume_text:
        raise HTTPException(status_code=400, detail="Could not extract text from PDF")
    
    # Build helper prompt
    system_prompt = """
    You are an expert resume writer and career coach specializing in Singapore's job market.
    Provide specific, actionable suggestions to improve resume sections.
    Focus on practical improvements that will make the resume more compelling to employers and ATS systems.
    """
    
    helper_context = ""
    if target_role:
        helper_context += f"Target Role: {target_role}\n"
    if target_industry:
        helper_context += f"Target Industry: {target_industry}\n"
    if specific_sections:
        sections_list = [s.strip() for s in specific_sections.split(',')]
        helper_context += f"Focus Sections: {', '.join(sections_list)}\n"
    if current_content:
        helper_context += f"Current Content Notes: {current_content}\n"
    
    user_prompt = f"""
    Analyze this resume and provide specific improvement suggestions for each major section.
    
    {helper_context}
    
    <resume>
    {resume_text}
    </resume>
    
    Return ONLY valid JSON in this exact format:
    {{
        "suggestions": [
            {{
                "section": "Summary",
                "current_text": "Current summary text if identifiable",
                "suggested_improvement": "Improved version with specific changes",
                "explanation": "Why this improvement helps",
                "impact_level": "High"
            }},
            {{
                "section": "Experience",
                "current_text": "First experience entry text",
                "suggested_improvement": "Improved version with action verbs and metrics",
                "explanation": "More impactful language and quantifiable results",
                "impact_level": "High"
            }}
        ],
        "overall_strategy": "Focus on quantifying achievements and adding industry keywords to improve ATS compatibility and showcase impact",
        "priority_order": ["Experience", "Summary", "Skills", "Education", "Formatting"]
    }}
    
    Guidelines:
    - Provide 3-6 specific suggestions focusing on highest impact improvements
    - Include actual text improvements, not just general advice
    - Prioritize changes that improve both human readability and ATS compatibility
    - Consider Singapore job market preferences
    - Impact levels: High (major improvement), Medium (moderate improvement), Low (minor polish)
    """
    
    response = get_bedrock_completion(user_prompt, system_prompt)
    
    try:
        response = response.strip()
        if response.startswith('```json'):
            response = response[7:-3]
        elif response.startswith('```'):
            response = response[3:-3]
        
        result = json.loads(response)
        return ResumeHelperResponse(**result)
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        print(f"Raw response: {response}")
        raise HTTPException(status_code=500, detail="Error parsing resume helper response")

@app.get("/test-search")
async def test_search(keyword: str = Query("python", description="Test keyword")):
    """Test endpoint to verify SSG API connectivity and search functionality"""
    print(f"[DEBUG] Testing search with keyword: {keyword}")
    
    try:
        params = {"pageSize": 10, "page": 0, "keyword": keyword}
        raw = await ssg_get("/courses/directory", params=params)
        
        result = {
            "success": True,
            "keyword_used": keyword,
            "raw_response_keys": list(raw.keys()) if isinstance(raw, dict) else "Not a dict",
            "raw_response_type": str(type(raw)),
        }
        
        if isinstance(raw, dict):
            data = raw.get("data", {})
            meta = raw.get("meta", {})
            courses = data.get("courses", []) if isinstance(data, dict) else []
            
            result.update({
                "data_keys": list(data.keys()) if isinstance(data, dict) else "Not a dict",
                "meta_content": meta,
                "courses_count": len(courses),
                "first_course_title": courses[0].get("title", "No title") if courses else "No courses"
            })
            
            # Show first few course titles for verification
            if courses:
                result["sample_courses"] = [
                    {
                        "title": course.get("title", "No title"),
                        "provider": course.get("trainingProvider", {}).get("name", "No provider") if isinstance(course.get("trainingProvider"), dict) else "No provider"
                    }
                    for course in courses[:3]
                ]
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": str(type(e)),
            "keyword_used": keyword
        }

@app.get("/ping")
def ping():
    return {"ok": True, "message": "API server is healthy"}

@app.get("/whoami")
def whoami():
    return {
        "env": settings.ENV,
        "ssg_base": str(settings.SSG_API_BASE),
        "api_version": settings.SSG_API_VERSION,
    }

@app.get("/categories", response_model=CategoriesOut)
async def get_categories(keyword: str = Query(..., min_length=3, description="Min 3 chars")):
    """Existing categories endpoint"""
    raw = await ssg_get("/courses/categories", params={"keyword": keyword})
    data = raw.get("data") or {}
    categories_raw = data.get("categories") or []
    meta = raw.get("meta") or {}
    total = int(meta.get("total") or len(categories_raw))

    categories: List[Category] = []
    for row in categories_raw:
        rolodex = row.get("rolodex") or {}
        categories.append(
            Category(
                id=int(row.get("id")),
                name=str(row.get("name")),
                display=bool(row.get("display")),
                rolodex=Rolodex(
                    display=bool(rolodex.get("display")),
                    numberOfLetters=int(rolodex.get("numberOfLetters") or 1),
                ),
            )
        )

    return CategoriesOut(count=total, categories=categories)

@app.get("/course-tags", response_model=CourseTagsOut)
async def get_course_tags(sort_by: int = Query(0, description="0=by text, 1=by count")):
    """Get course tags for better filtering"""
    raw = await ssg_get("/courses/tags", params={"sortBy": sort_by}, api_version="v1")
    data = raw.get("data") or {}
    tags_raw = data.get("tags") or []
    meta = raw.get("meta") or {}
    total = int(meta.get("total") or len(tags_raw))
    
    tags = [CourseTag(text=tag["text"], count=tag["count"]) for tag in tags_raw]
    return CourseTagsOut(tags=tags, total=total)

@app.get("/course/{course_ref}", response_model=CourseDetail)
async def get_course_detail(course_ref: str, include_expired: bool = Query(True)):
    """Get detailed information about a specific course"""
    params = {"includeExpiredCourses": include_expired}
    raw = await ssg_get(f"/courses/directory/{course_ref}", params=params, api_version="v1.2")
    
    data = raw.get("data") or {}
    courses = data.get("courses") or []
    
    if not courses:
        raise HTTPException(status_code=404, detail="Course not found")
    
    r = courses[0]  # Should only be one course
    
    # Extract enhanced information
    tp = r.get("trainingProvider") if isinstance(r, dict) else None
    
    # Always generate SkillsFuture URL using course reference number
    course_ref_num = r.get("referenceNumber") or r.get("skillsConnectReferenceNumber")
    skillsfuture_url = None
    if course_ref_num:
        skillsfuture_url = f"https://www.myskillsfuture.gov.sg/content/portal/en/training-exchange/course-directory/course-detail.html?courseReferenceNumber={course_ref_num}"
    
    hours = r.get("totalTrainingDurationHour")
    if hours is None:
        if r.get("lengthOfCourseDuration") is not None:
            hours = float(r["lengthOfCourseDuration"]) * 8.0
        elif r.get("numberOfTrainingDay") is not None:
            hours = float(r["numberOfTrainingDay"]) * 8.0

    # Extract tags and skills
    tags = []
    for t in (r.get("taggings") or []):
        if isinstance(t, dict) and t.get("description"):
            tags.append(t["description"])
    for a in (r.get("areaOfTrainings") or []):
        if isinstance(a, dict) and a.get("description"):
            tags.append(a["description"])

    # Extract WSQ skills if available
    skills = []
    for wsq in (r.get("wsqFrameworks") or []):
        if wsq.get("competencyStandardDescription"):
            skills.append(wsq["competencyStandardDescription"])

    return CourseDetail(
        id=course_ref_num,
        title=r.get("title"),
        provider=(tp or {}).get("name") if isinstance(tp, dict) else None,
        url=skillsfuture_url,  # Always use SkillsFuture URL
        price=r.get("totalCostOfTrainingPerTrainee"),
        duration_hours=hours,
        tags=tags,
        skills=skills,
        objective=r.get("objective"),
        content=r.get("content"),
        entry_requirement=r.get("entryRequirement"),
        contact_persons=r.get("contactPerson", []),
        runs=r.get("runs", []),
        faculty_name=r.get("facultyName"),
        specialisation=r.get("specialisation"),
    )

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
    """Enhanced course search with better data extraction"""
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
    courses = data.get("courses") or []

    items = []
    for r in courses:
        items.append(_extract_course_item(r))

    return CourseSearchOut(total=total, page=page, page_size=page_size, items=items)

def _extract_course_item(r: dict) -> CourseItem:
    """Extract CourseItem from raw course data with enhanced fields including course content"""
    provider_name = r.get("trainingProviderAlias")
    tp = r.get("trainingProvider")
    
    # Always generate SkillsFuture URL using course reference number
    course_ref = r.get("referenceNumber") or r.get("skillsConnectReferenceNumber")
    skillsfuture_url = None
    if course_ref:
        skillsfuture_url = f"https://www.myskillsfuture.gov.sg/content/portal/en/training-exchange/course-directory/course-detail.html?courseReferenceNumber={course_ref}"
    
    hours = r.get("totalTrainingDurationHour")
    if hours is None:
        if r.get("lengthOfCourseDuration") is not None:
            hours = float(r["lengthOfCourseDuration"]) * 8.0
        elif r.get("numberOfTrainingDay") is not None:
            hours = float(r["numberOfTrainingDay"]) * 8.0

    # Extract tags
    tags = []
    for t in (r.get("taggings") or []):
        if isinstance(t, dict) and t.get("description"):
            tags.append(t["description"])
    for a in (r.get("areaOfTrainings") or []):
        if isinstance(a, dict) and a.get("description"):
            tags.append(a["description"])

    # Extract skills (WSQ frameworks)
    skills = []
    for wsq in (r.get("wsqFrameworks") or []):
        if wsq.get("competencyStandardDescription"):
            skills.append(wsq["competencyStandardDescription"])

    # Extract unique skills (if available)
    unique_skills = []
    for skill in (r.get("UniqueSkills") or []):
        if skill.get("title"):
            unique_skills.append(skill["title"])

    # Extract bundles
    bundles = []
    for bundle in (r.get("bundles") or []):
        if bundle.get("description"):
            bundles.append(bundle["description"])

    # Extract area of training
    area_of_training = None
    if r.get("areaOfTrainings") and len(r["areaOfTrainings"]) > 0:
        area_of_training = r["areaOfTrainings"][0].get("description")

    # Extract external accreditations
    external_accreditations = []
    for acc in (r.get("externalAccreditations") or []):
        if acc.get("accreditingAgency", {}).get("name"):
            external_accreditations.append(acc["accreditingAgency"]["name"])

    return CourseItem(
        id=course_ref,
        title=r.get("title"),
        provider=provider_name,
        url=skillsfuture_url,
        price=r.get("totalCostOfTrainingPerTrainee"),
        duration_hours=hours,
        tags=tags[:10],
        skills=skills,
        unique_skills=unique_skills,
        bundles=bundles,
        area_of_training=area_of_training,
        suitable_job_roles=r.get("suitableJobRoles"),
        external_accreditations=external_accreditations,
        objective=summarize_course_objective(r.get("objective", "")),
        content=r.get("content")
    )

def calculate_skill_gap_coverage_ai(goal: str, course_text: str) -> float:
    """Use AI to determine how well a course covers skill gaps for any career goal"""
    
    if not goal or not course_text:
        return 0.0
    
    system_prompt = """
    You are an expert in career development and course evaluation.
    Analyze how well a course addresses the skill requirements for a specific career goal.
    Return a score between 0.0 and 1.0.
    """
    
    user_prompt = f"""
    Career Goal: {goal}
    
    Course Information: {course_text[:500]}
    
    Question: How well does this course address the skills needed for this career goal?
    
    Consider:
    - Direct skill relevance
    - Industry requirements
    - Professional development value
    - Certification importance
    
    Return ONLY a number between 0.0 (not relevant) and 1.0 (highly relevant).
    Examples: 0.8, 0.3, 0.6, 0.1
    """
    
    try:
        response = get_bedrock_completion(user_prompt, system_prompt)
        score = float(response.strip())
        return max(0.0, min(1.0, score))
    except:
        # Fallback to basic text matching
        goal_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', goal.lower()))
        course_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', course_text.lower()))
        overlap = len(goal_words & course_words)
        return min(1.0, overlap / max(len(goal_words), 1) * 2)
    
def calculate_relevance_bonus_ai(goal: str, course_title: str, course_objective: str) -> float:
    """Use AI to calculate relevance bonus for any career goal"""
    
    if not goal:
        return 0.0
    
    # Simple keyword matching as fallback
    goal_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', goal.lower()))
    title_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', course_title.lower()))
    objective_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', course_objective.lower()))
    
    title_overlap = len(goal_words & title_words) / max(len(goal_words), 1)
    objective_overlap = len(goal_words & objective_words) / max(len(goal_words), 1)
    
    return min(1.0, (title_overlap * 0.6 + objective_overlap * 0.4))

def generate_recommendation_reason_ai(goal: str, course_title: str, course_objective: str, 
                                    skill_gap_coverage: float, content_similarity: float) -> str:
    """Generate human-friendly reasons without technical stats - works for any career goal"""
    
    if not goal:
        return "Provides valuable professional development opportunities."
    
    reasons = []
    
    # Analyze course type from title
    title_lower = course_title.lower()
    objective_lower = course_objective.lower()
    
    # Certification/qualification courses
    if any(word in title_lower for word in ['certification', 'exam', 'certified', 'qualification']):
        reasons.append("Industry-recognized certification that enhances professional credibility")
    
    # Professional level courses
    elif any(word in title_lower for word in ['professional', 'advanced', 'expert']):
        reasons.append("Advanced training designed for experienced professionals")
    
    # Foundation/beginner courses
    elif any(word in title_lower for word in ['fundamental', 'basic', 'introduction', 'essentials']):
        reasons.append("Builds essential foundation skills for career development")
    
    # Workshop/practical courses
    elif any(word in title_lower for word in ['workshop', 'hands-on', 'practical']):
        reasons.append("Practical, hands-on training with immediate application")
    
    else:
        reasons.append("Directly relevant to your career objectives")
    
    # Skill gap analysis
    if skill_gap_coverage > 0.6:
        reasons.append("Addresses critical skill gaps in your current profile")
    elif skill_gap_coverage > 0.3:
        reasons.append("Develops skills that complement your existing experience")
    else:
        reasons.append("Expands your professional skill set")
    
    # Content relevance
    if content_similarity > 0.5:
        reasons.append("Strong alignment with your stated career goals")
    elif any(word in objective_lower for word in ['singapore', 'local', 'industry']):
        reasons.append("Tailored for Singapore's job market requirements")
    else:
        reasons.append("Provides transferable skills valuable across industries")
    
    return " • ".join(reasons[:3])  # Return max 3 reasons


def _calculate_enhanced_score_with_explanation(course_data: dict, query_bow: Counter, req: RecommendReq) -> tuple[float, dict, float, float, str]:
    """Universal scoring algorithm that works for any career goal"""
    # Enhanced analysis using career transition context
    search_strategy = create_enhanced_search_strategy(req)
    transition_type = search_strategy["focus"]

    # Adjust scoring weights based on transition type
    if transition_type == "foundational":
        w_sim, w_gap, w_rel = 0.3, 0.4, 0.2  # Prioritize skill building
    elif transition_type == "advancement": 
        w_sim, w_gap, w_rel = 0.5, 0.2, 0.2  # Focus on content match
    else:  # transition
        w_sim, w_gap, w_rel = 0.2, 0.5, 0.3  # Heavily weight gap coverage
    
    title = course_data.get("title", "").lower()
    objective = course_data.get("objective", "").lower()
    content = course_data.get("content", "").lower()
    goal = req.resume.Goal or ""
    
    # Build comprehensive course text
    full_course_text = f"{title} {objective} {content}"
    for wsq in (course_data.get("wsqFrameworks") or []):
        if wsq.get("competencyStandardDescription"):
            full_course_text += f" {wsq['competencyStandardDescription']}"
    
    # Calculate content similarity
    core_bow = _bow(f"{title} {title} {objective} {content}")  # Emphasize title
    content_similarity = _cos(core_bow, query_bow)
    
    # Calculate skill gap coverage using AI-generated understanding
    skill_gap_coverage = calculate_skill_gap_coverage_ai(goal, full_course_text)
    
    # Calculate existing skill overlap
    existing_skill_overlap = 0.0
    if req.resume.Skills:
        existing_skill_overlap = _skill_overlap(req.resume.Skills, full_course_text)
    
    # Base metrics
    price = course_data.get("totalCostOfTrainingPerTrainee")
    price_score = 0.0 if price is None else max(0.0, min(1.0, 1.0/(1.0 + price/500.0)))
    
    dur = course_data.get("totalTrainingDurationHour")
    if dur is None:
        if course_data.get("lengthOfCourseDuration") is not None:
            dur = float(course_data["lengthOfCourseDuration"]) * 8.0
        elif course_data.get("numberOfTrainingDay") is not None:
            dur = float(course_data["numberOfTrainingDay"]) * 8.0
    dur_score = 0.0 if dur is None else max(0.0, min(1.0, 1.0/(1.0 + dur/40.0)))
    
    
    # Relevance bonus based on AI analysis
    relevance_bonus = calculate_relevance_bonus_ai(goal, course_data.get("title", ""), objective)
    
    # Final score calculation
    w_sim = 0.4
    w_price = 0.1  
    w_dur = 0.1
    w_gap = 0.2
    w_rel = 0.1
    
    final_score = (
        w_sim * content_similarity + 
        w_price * price_score + 
        w_dur * dur_score + 
        w_gap * skill_gap_coverage +
        w_rel * relevance_bonus
    )
    
    # Generate recommendation reason
    recommendation_reason = generate_recommendation_reason_ai(goal, course_data.get("title", ""), objective, skill_gap_coverage, content_similarity)
    
    score_breakdown = {
        "content_similarity": round(content_similarity, 3),
        "skill_gap_coverage": round(skill_gap_coverage, 3),
        "relevance_bonus": round(relevance_bonus, 3),
        "price": round(price_score, 3),
        "duration": round(dur_score, 3),
        "final": round(final_score, 4)
    }
    
    return final_score, score_breakdown, skill_gap_coverage, existing_skill_overlap, recommendation_reason

def _calculate_enhanced_score(course_data: dict, query_bow: Counter, req: RecommendReq) -> tuple[float, dict, float, float, str]:
    """Enhanced scoring algorithm that prioritizes course content and objectives over tags"""
    
    # Build course text with weighted importance - prioritize title, objective, and content
    title = course_data.get("title") or ""
    objective = course_data.get("objective") or ""
    content = course_data.get("content") or ""
    
    # Core content (high weight)
    core_text = f"{title} {title} {objective} {content}"  # Duplicate title for emphasis
    
    # Secondary content (medium weight)
    skills_text = ""
    for wsq in (course_data.get("wsqFrameworks") or []):
        if wsq.get("competencyStandardDescription"):
            skills_text += f" {wsq['competencyStandardDescription']}"
    
    unique_skills_text = " ".join([skill.get("title", "") for skill in (course_data.get("UniqueSkills") or [])])
    suitable_jobs = course_data.get("suitableJobRoles") or ""
    
    # Tags (lower weight) - use as bonus, not primary match
    tag_text = ""
    for t in (course_data.get("taggings") or []):
        if isinstance(t, dict) and t.get("description"):
            tag_text += f" {t['description']}"
    for a in (course_data.get("areaOfTrainings") or []):
        if isinstance(a, dict) and a.get("description"):
            tag_text += f" {a['description']}"
    
    # Calculate similarity with different weights
    core_bow = _bow(core_text)
    secondary_bow = _bow(f"{skills_text} {unique_skills_text} {suitable_jobs}")
    tag_bow = _bow(tag_text)
    
    # Weighted similarity calculation
    core_similarity = _cos(core_bow, query_bow)
    secondary_similarity = _cos(secondary_bow, query_bow) 
    tag_similarity = _cos(tag_bow, query_bow)
    
    # Combined similarity with weights favoring content over tags
    sim_score = (
        core_similarity * 0.6 +          # Title, objective, content get 60%
        secondary_similarity * 0.3 +      # Skills and job roles get 30% 
        tag_similarity * 0.1              # Tags get only 10%
    )
    
    # Calculate skill gap coverage using all course text
    full_course_text = f"{core_text} {skills_text} {unique_skills_text} {suitable_jobs} {tag_text}"
    skill_gap_coverage = 0.0
    if req.resume.SkillGaps:
        gap_bow = Counter()
        for gap in req.resume.SkillGaps:
            gap_bow.update(_tok(gap))
        skill_gap_coverage = _cos(_bow(full_course_text), gap_bow)
    
    # Calculate existing skill overlap
    existing_skill_overlap = 0.0
    if req.resume.Skills:
        existing_skill_overlap = _skill_overlap(req.resume.Skills, full_course_text)
    
    # Price score (inverse - lower price is better)
    price = course_data.get("totalCostOfTrainingPerTrainee")
    price_score = 0.0 if price is None else max(0.0, min(1.0, 1.0/(1.0 + price/500.0)))
    
    # Duration score (inverse - shorter duration might be preferred)
    dur = course_data.get("totalTrainingDurationHour")
    if dur is None:
        if course_data.get("lengthOfCourseDuration") is not None:
            dur = float(course_data["lengthOfCourseDuration"]) * 8.0
        elif course_data.get("numberOfTrainingDay") is not None:
            dur = float(course_data["numberOfTrainingDay"]) * 8.0
    dur_score = 0.0 if dur is None else max(0.0, min(1.0, 1.0/(1.0 + dur/40.0)))
    
    # Industry/area match bonus (small bonus, not requirement)
    area_bonus = 0.0
    if req.resume.Industry and course_data.get("areaOfTrainings"):
        user_industry = req.resume.Industry.lower()
        for area in course_data["areaOfTrainings"]:
            area_desc = area.get("description", "").lower()
            if any(word in area_desc for word in _tok(user_industry)):
                area_bonus = getattr(settings, 'AREA_MATCH_BONUS', 0.2)
                break
    
    # Skill gap bonus (prioritize courses that fill gaps)
    gap_bonus = skill_gap_coverage * getattr(settings, 'SKILL_GAP_BONUS', 0.3) if req.focus_on_gaps else 0.0
    
    # Existing skill penalty (reduce score if too much overlap with existing skills)
    overlap_penalty = 0.0
    overlap_threshold = getattr(settings, 'EXISTING_SKILL_OVERLAP_THRESHOLD', 0.5)
    if req.focus_on_gaps and existing_skill_overlap > overlap_threshold:
        overlap_penalty = (existing_skill_overlap - overlap_threshold) * getattr(settings, 'EXISTING_SKILL_PENALTY', 0.2)
    
    # Calculate weighted score
    w_sim = settings.WEIGHT_SIMILARITY
    w_price = settings.WEIGHT_PRICE
    w_dur = settings.WEIGHT_DURATION
    
    final_score = (w_sim * sim_score + 
                   w_price * price_score + 
                   w_dur * dur_score + 
                   gap_bonus + 
                   area_bonus -
                   overlap_penalty)
    
    # Generate recommendation reason with content focus
    reason_parts = []
    if core_similarity > 0.4:
        reason_parts.append(f"Strong content match ({core_similarity:.2f})")
    if skill_gap_coverage > 0.3:
        reason_parts.append(f"Addresses skill gaps ({skill_gap_coverage:.2f})")
    if tag_similarity > 0.3:
        reason_parts.append(f"Tag alignment ({tag_similarity:.2f})")
    if area_bonus > 0:
        reason_parts.append("Industry match")
    if existing_skill_overlap > overlap_threshold:
        reason_parts.append(f"High overlap with existing skills ({existing_skill_overlap:.2f})")
    
    recommendation_reason = "; ".join(reason_parts) if reason_parts else "General match to query"
    
    score_breakdown = {
        "content_similarity": round(core_similarity, 3),
        "skills_similarity": round(secondary_similarity, 3),
        "tag_similarity": round(tag_similarity, 3),
        "combined_similarity": round(sim_score, 3),
        "price": round(price_score, 3),
        "duration": round(dur_score, 3),
        "skill_gap_bonus": round(gap_bonus, 3),
        "area_bonus": round(area_bonus, 3),
        "overlap_penalty": round(overlap_penalty, 3),
        "final": round(final_score, 4)
    }
    
    return final_score, score_breakdown, skill_gap_coverage, existing_skill_overlap, recommendation_reason

def create_enhanced_search_strategy(req: RecommendReq) -> Dict[str, Any]:
    """Create intelligent search strategy based on resume analysis"""
    
    # Analyze career transition type
    existing_skills = req.resume.Skills or []
    goal = req.resume.Goal or ""
    experience_level = req.resume.Experience or "Mid"
    
    # Determine search focus
    if not existing_skills:
        focus = "foundational"
        search_approach = "broad_beginner"
    elif any(skill.lower() in goal.lower() for skill in existing_skills):
        focus = "advancement" 
        search_approach = "specialized_intermediate"
    else:
        focus = "transition"
        search_approach = "career_change"
    
    # Generate context-aware prompt for AI
    context_prompt = f"""
    RESUME ANALYSIS:
    - Current Skills: {', '.join(existing_skills[:10])}
    - Career Goal: {goal}
    - Experience Level: {experience_level}
    - Search Focus: {focus}
    
    SEARCH STRATEGY: {search_approach}
    
    Based on this analysis, what are the 8 most strategic search terms to find courses that will:
    1. Bridge the gap between current skills and career goal
    2. Provide practical, applicable knowledge
    3. Offer recognized certifications
    4. Match Singapore's industry standards
    
    Consider skill prerequisites and learning progression.
    """
    
    return {
        "focus": focus,
        "approach": search_approach, 
        "context": context_prompt
    }

def summarize_course_objective(objective: str) -> str:
    """Use AI to create clean, consistent course objective summaries"""
    
    if not objective or len(objective.strip()) < 20:
        return objective
    
    system_prompt = """
    You are an expert at summarizing course objectives clearly and concisely.
    Create a 2-3 sentence summary that captures the key learning outcomes.
    Use simple, professional language that anyone can understand.
    """
    
    user_prompt = f"""
    Summarize this course objective in 2-3 clear sentences:
    
    {objective}
    
    Focus on:
    - What skills students will learn
    - What they'll be able to do after the course
    - Keep it concise and professional
    
    Return only the summary, no extra text.
    """
    
    try:
        summary = get_bedrock_completion(user_prompt, system_prompt)
        return summary.strip()
    except:
        # Fallback: clean up the original objective
        cleaned = objective.replace('•', '').replace('-', '').replace('\n', ' ')
        sentences = [s.strip() for s in cleaned.split('.') if s.strip()]
        return '. '.join(sentences[:3]) + '.' if sentences else objective


@app.post("/recommend", response_model=RecommendOut)
async def recommend(req: RecommendReq):
    """Enhanced recommendation endpoint with career transition detection"""
    
    # STEP 1: Detect career transition type
    existing_skills_text = " ".join(req.resume.Skills or [])
    goal_text = req.resume.Goal or ""
    
    # Simple but effective transition detection
    existing_terms = set(_tok(existing_skills_text.lower()))
    goal_terms = set(_tok(goal_text.lower()))
    
    overlap = len(existing_terms & goal_terms)
    is_major_transition = overlap == 0 and len(goal_terms) > 0
    
    print(f"[DEBUG] Career Transition Analysis:")
    print(f"  Existing skills: {list(existing_terms)[:10]}")
    print(f"  Goal terms: {list(goal_terms)}")
    print(f"  Overlap: {overlap}")
    print(f"  Major transition: {is_major_transition}")
    
    # STEP 2: Enhanced query building with AI assistance
    search_strategy = create_enhanced_search_strategy(req)

    if is_major_transition:
        # Use AI to get smart search terms for career transition
        ai_terms = generate_search_terms_with_ai(goal_text, req.resume.Industry)
        terms = ai_terms[:6]  # More terms for better coverage
        print(f"[DEBUG] MAJOR TRANSITION - AI-generated terms: {terms}")
        
        # Add skill gaps if available
        if req.resume.SkillGaps:
            gap_terms = []
            for gap in req.resume.SkillGaps[:2]:
                gap_terms.extend([w for w in _tok(gap) if len(w) > 2])
            terms.extend(gap_terms[:2])
            terms = list(dict.fromkeys(terms))[:4]  # Remove duplicates
    else:
        # For non-major transitions: use existing logic
        terms = _build_enhanced_query_terms(
            req.resume.Skills, 
            req.resume.Goal, 
            req.resume.Experience,
            req.resume.Industry,
            req.resume.SkillGaps,
            req.focus_on_gaps
        )
    
    query = " ".join(terms)
    print(f"[DEBUG] Final query: '{query}'")
    print(f"[DEBUG] Final terms: {terms}")

    # Try multiple search strategies if first fails
    search_strategies = [
        {"query": query, "strategy": "primary_query"},
        {"query": " ".join(terms[:2]), "strategy": "limited_terms"},  # First 2 terms
        {"query": req.resume.Goal or "professional development", "strategy": "goal_only"},
        {"query": "professional development", "strategy": "fallback"}
    ]
    
    raw = None
    used_strategy = None
    
    for strategy in search_strategies:
        try:
            print(f"[DEBUG] Trying strategy '{strategy['strategy']}' with query: '{strategy['query']}'")
            params = {
                "pageSize": req.page_size, 
                "page": 0, 
                "keyword": strategy["query"]
            }
            
            raw = await ssg_get("/courses/directory", params=params)
            data = raw.get("data") or {}
            rows = data.get("courses") or []
            
            if rows:
                print(f"[DEBUG] Strategy '{strategy['strategy']}' succeeded with {len(rows)} courses")
                used_strategy = strategy['strategy']
                break
            else:
                print(f"[DEBUG] Strategy '{strategy['strategy']}' returned 0 courses")
                
        except Exception as e:
            print(f"[DEBUG] Strategy '{strategy['strategy']}' failed with error: {e}")
            continue
    
    if not raw:
        print("[DEBUG] All search strategies failed")
        return RecommendOut(
            query_terms=terms, 
            items=[],
            used_filters={"error": "All search strategies failed"},
            skill_gap_analysis={"error": "No courses found"},
            debug_info={
                "attempted_strategies": [s['strategy'] for s in search_strategies],
                "error": "All search strategies failed"
            }
        )

    data = raw.get("data") or {}
    rows = data.get("courses") or []
    
    print(f"[DEBUG] Processing {len(rows)} courses")
    
    # Show first few course titles to verify we're getting relevant results
    if rows:
        print(f"[DEBUG] Sample of courses found:")
        for i, course in enumerate(rows[:5]):
            title = course.get('title', 'No title')
            provider_name = course.get('trainingProviderAlias', 'No provider')
            price = course.get('totalCostOfTrainingPerTrainee', 'No price')
            print(f"  {i+1}. {title} - {provider_name} - ${price}")
    
    qbow = _bow(query)
    ranked: List[RecItem] = []
    
    used_filters = {
        "budget_max": req.budget_max,
        "duration_max_hours": req.duration_max_hours,
        "area_of_training": req.area_of_training,
        "total_courses_found": len(rows),
        "focus_on_gaps": req.focus_on_gaps,
        "search_strategy_used": used_strategy
    }

    # Skill gap analysis
    skill_gap_analysis = {
        "identified_gaps": req.resume.SkillGaps or [],
        "existing_skills": req.resume.Skills or [],
        "gap_focused_search": req.focus_on_gaps
    }

    courses_processed = 0
    courses_filtered_out = 0

    for r in rows:
        courses_processed += 1
        
        # Apply only essential filters - remove duration filtering to allow ranking instead
        price = r.get("totalCostOfTrainingPerTrainee")
        dur = r.get("totalTrainingDurationHour")
        if dur is None:
            if r.get("lengthOfCourseDuration") is not None:
                dur = float(r["lengthOfCourseDuration"]) * 8.0
            elif r.get("numberOfTrainingDay") is not None:
                dur = float(r["numberOfTrainingDay"]) * 8.0

        # Budget filter (only if specified and course is significantly over budget)
        if req.budget_max is not None and price is not None and price > req.budget_max * 1.5:
            courses_filtered_out += 1
            continue
        
        # Remove duration filter - let scoring handle this instead
        # Duration will be factored into ranking, not elimination
        
        # Area of training filter (only if specifically requested)
        if req.area_of_training:
            area_match = False
            for area in (r.get("areaOfTrainings") or []):
                if req.area_of_training.lower() in area.get("description", "").lower():
                    area_match = True
                    break
            if not area_match:
                courses_filtered_out += 1
                continue

        # Calculate enhanced score with skill gap analysis using enhanced function
        score, score_breakdown, skill_gap_coverage, existing_skill_overlap, recommendation_reason = _calculate_enhanced_score_with_explanation(r, qbow, req)
        
        # Create enhanced course item
        course_item = _extract_course_item(r)
        
        ranked.append(RecItem(
            id=course_item.id,
            title=course_item.title,
            provider=course_item.provider,
            url=course_item.url,
            price=course_item.price,
            duration_hours=course_item.duration_hours,
            tags=course_item.tags,
            skills=course_item.skills,
            unique_skills=course_item.unique_skills,
            bundles=course_item.bundles,
            area_of_training=course_item.area_of_training,
            suitable_job_roles=course_item.suitable_job_roles,
            external_accreditations=course_item.external_accreditations,
            objective=course_item.objective,
            content=course_item.content,
            score=score,
            score_breakdown=score_breakdown,
            skill_gap_coverage=skill_gap_coverage,
            existing_skill_overlap=existing_skill_overlap,
            recommendation_reason=recommendation_reason,
        ))

    print(f"[DEBUG] Processed {courses_processed} courses, filtered out {courses_filtered_out}")
    print(f"[DEBUG] Generated {len(ranked)} recommendations")

    # Sort by score
    ranked.sort(key=lambda x: x.score, reverse=True)
    used_filters["courses_after_filtering"] = len(ranked)
    
    # Update skill gap analysis with results
    if ranked:
        overlap_threshold = getattr(settings, 'EXISTING_SKILL_OVERLAP_THRESHOLD', 0.5)
        skill_gap_analysis.update({
            "avg_gap_coverage": sum(c.skill_gap_coverage for c in ranked) / len(ranked),
            "avg_existing_overlap": sum(c.existing_skill_overlap for c in ranked) / len(ranked),
            "high_gap_coverage_courses": len([c for c in ranked if c.skill_gap_coverage > 0.4]),
            "low_overlap_courses": len([c for c in ranked if c.existing_skill_overlap < overlap_threshold])
        })
    
    debug_info = {
        "search_strategy_used": used_strategy,
        "courses_found": len(rows),
        "courses_processed": courses_processed,
        "courses_filtered_out": courses_filtered_out,
        "final_recommendations": len(ranked),
        "query_used": query,
        "original_terms": terms
    }
    
    return RecommendOut(
        query_terms=terms, 
        items=ranked[:req.top_k],
        used_filters=used_filters,
        skill_gap_analysis=skill_gap_analysis,
        debug_info=debug_info
    )

@app.get("/api/info")
async def api_info():
    return {
        "message": "Enhanced SSG Course Recommendation API", 
        "version": "2.5",
        "status": "running",
        "features": [
            "Course search with advanced filtering",
            "Individual course details",
            "Course tags and categories",
            "Enhanced recommendation scoring with skill gap analysis",
            "Support for bundles and unique skills",
            "Course content and objective analysis",
            "Existing skill overlap detection",
            "Resume scoring and analysis",
            "Resume improvement helper",
            "Debug mode enabled"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading
    import time
    
    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:8000")
    
    # Start browser in background
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run the server
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)

@app.options("/recommend")
async def recommend_options():
    """Handle preflight OPTIONS request for recommend endpoint"""
    return {"message": "OK"}