# SkillsFuture Course Recommender

An AI-powered web application that analyzes resumes and provides personalized SkillsFuture course recommendations for career development in Singapore.

## Features

### Core Functionality
- **Resume Analysis**: Upload PDF resumes for detailed scoring and feedback
- **AI-Powered Scoring**: Comprehensive resume evaluation with grade (A+ to F) and breakdown scores
- **Career-Specific Analysis**: Targeted feedback based on desired roles and industries
- **Course Recommendations**: Personalized SkillsFuture course suggestions using intelligent matching
- **Interactive Web Interface**: Modern, responsive single-page application

### Advanced Features
- **Skill Gap Analysis**: Identifies gaps between current skills and career goals
- **Career Transition Support**: Special handling for major career changes
- **Content-Based Matching**: Analyzes course objectives and content for better recommendations
- **Session Management**: Maintains analysis history and saved courses
- **Real-time API Integration**: Live data from Singapore's SkillsFuture course directory

## Technology Stack

### Backend
- **FastAPI**: Modern Python web framework for the API
- **Provider-agnostic LLM client**: Any OpenAI-compatible API. Defaults to **Groq**
  (free, fast, open-source models). Swap to Ollama / OpenRouter / vLLM by changing env vars.
- **Tool-calling agent**: The recommender is a real agent loop — the LLM searches the
  course catalog, inspects courses, refines its queries, and submits a ranked set.
- **SSG-WSG API**: Official Singapore SkillsFuture course data
- **PyPDF2**: PDF text extraction
- **Pydantic**: Data validation and settings management

### Frontend
- **React**: Component-based UI framework
- **Tailwind CSS**: Utility-first styling
- **Vanilla JavaScript**: No build process required

### Code layout
```
main.py        # thin FastAPI routes
settings.py    # all config (LLM, agent, SSG, scoring weights)
app/
  llm.py       # provider-agnostic OpenAI-compatible client (+ offline mock mode)
  agent.py     # tool-calling recommendation loop (+ deterministic fallback)
  tools.py     # the agent's tools: search_courses, get_course_details, submit_recommendations
  ssg.py       # SSG-WSG course directory client
  scoring.py   # deterministic course scoring (uses settings weights)
  resume.py    # PDF extraction + resume analysis/helper
  prompts.py   # prompt templates
  schemas.py   # pydantic request/response models
```

## Installation

### Prerequisites
- Python 3.9+
- A free **Groq API key** (https://console.groq.com/keys) — or any OpenAI-compatible
  endpoint (Ollama, OpenRouter, etc.). The app also boots in offline **mock mode** with no key.
- SSG-WSG API credentials (for live course data)

### Setup Steps

1. **Download Zip File**
   extract zip file
   cd to zip file directory
   ```bash
   cd skillsfuture-recommender
   ```

2. **Install Python dependencies**
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   Copy `.env.example` to `.env` and fill it in. The key settings:
   ```env
   ENV=dev

   # LLM provider (OpenAI-compatible). Default = Groq.
   LLM_PROVIDER=groq
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_API_KEY=your_groq_api_key        # leave blank for offline mock mode
   LLM_MODEL=llama-3.3-70b-versatile

   # SSG-WSG API Configuration
   SSG_TOKEN_URL=https://public-api.ssg-wsg.sg/dp-oauth/oauth/token
   SSG_CLIENT_ID=your_ssg_client_id
   SSG_CLIENT_SECRET=your_ssg_client_secret
   SSG_API_BASE=https://public-api.ssg-wsg.sg
   SSG_API_VERSION=v2.2

   # Scoring weights (optional — sensible defaults live in settings.py)
   WEIGHT_SIMILARITY=0.6
   WEIGHT_PRICE=0.15
   WEIGHT_DURATION=0.15
   SKILL_GAP_BONUS=0.3
   AREA_MATCH_BONUS=0.2
   EXISTING_SKILL_OVERLAP_THRESHOLD=0.5
   EXISTING_SKILL_PENALTY=0.2
   ```

   **Using a different model provider** — just change three values:

   | Provider   | `LLM_BASE_URL`                   | `LLM_MODEL` example                    |
   |------------|----------------------------------|----------------------------------------|
   | Groq       | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile`              |
   | Ollama     | `http://localhost:11434/v1`      | `qwen2.5:14b` (set `LLM_API_KEY=ollama`)|
   | OpenRouter | `https://openrouter.ai/api/v1`   | `meta-llama/llama-3.3-70b-instruct`    |

4. **Start the application**
   ```bash
   python main.py
   ```

## API Documentation

### Resume Analysis Endpoints

#### POST `/resume/score`
Analyze and score a resume with career-specific feedback.

**Parameters:**
- `file`: PDF resume file
- `target_role` (optional): Desired job role
- `target_industry` (optional): Target industry
- `experience_level` (optional): Experience level

**Response:**
```json
{
  "overall_score": 82.3,
  "grade": "B+",
  "breakdown": {
    "contact_info": 90.0,
    "experience": 85.0,
    "skills": 88.0
  },
  "strengths": ["Strong technical skills", "Clear experience progression"],
  "improvement_areas": ["Add quantifiable achievements", "Strengthen summary"],
  "detailed_feedback": "Comprehensive analysis...",
  "industry_alignment": "Good alignment for technical roles"
}
```

#### POST `/resume/helper`
Get specific suggestions for improving resume sections.

### Course Recommendation Endpoints

#### POST `/recommend`
Get personalized course recommendations based on career goals.

**Request:**
```json
{
  "resume": {
    "Goal": "I want to become a data scientist",
    "Skills": ["Python", "Excel"],
    "Industry": "Technology"
  },
  "page_size": 5,
  "top_k": 15,
  "focus_on_gaps": true
}
```

**Response:**
```json
{
  "query_terms": ["data science", "python", "machine learning"],
  "items": [
    {
      "title": "Data Science Fundamentals",
      "provider": "Provider Name",
      "price": 500.0,
      "duration_hours": 40,
      "score": 0.85,
      "recommendation_reason": "Addresses critical skill gaps"
    }
  ],
  "skill_gap_analysis": {
    "identified_gaps": ["machine learning", "statistics"],
    "avg_gap_coverage": 0.7
  }
}
```

### Course Search Endpoints

#### GET `/courses`
Search SkillsFuture courses with filters.

#### GET `/course/{course_ref}`
Get detailed information about a specific course.

## Architecture

### AI Integration
A single provider-agnostic client (`app/llm.py`, OpenAI-compatible) powers:
- Resume content analysis and scoring (`app/resume.py`)
- Resume improvement suggestions
- The recommendation **agent** (`app/agent.py`), which drives tool calls

If no `LLM_API_KEY` is set, the client runs in **offline mock mode** so the app still boots.

### The recommendation agent
`/recommend` runs a genuine tool-calling loop instead of a single prompt:
1. The LLM is given the user's skills, goal, and skill gaps.
2. It calls `search_courses` with focused keyword queries (often several, from different angles).
3. It inspects promising courses with `get_course_details` and **refines its queries** if results are weak.
4. When it has strong candidates, it calls `submit_recommendations` with ranked course references.
5. The backend scores the chosen courses deterministically (`app/scoring.py`) and returns them.

The loop is bounded by `AGENT_MAX_STEPS` / `AGENT_MAX_TOOL_CALLS`, and falls back to a
deterministic search+score pipeline if the LLM is unavailable or the loop stalls — so the
endpoint never fails.

### Scoring Algorithm
Final ranking is deterministic and reads every weight from `settings.py`:
- **Content similarity** (`WEIGHT_SIMILARITY`): title/objective/content vs. the goal
- **Skill-gap bonus** (`SKILL_GAP_BONUS`): rewards courses that fill stated gaps
- **Price / duration** (`WEIGHT_PRICE`, `WEIGHT_DURATION`): cost and time factors
- **Industry match** (`AREA_MATCH_BONUS`) and an **existing-skill penalty** (`EXISTING_SKILL_PENALTY`)
  to avoid recommending things the user already knows

### Data Flow
1. User uploads resume → PDF text extraction
2. LLM analyzes content → scores and feedback
3. User defines a career goal → the agent searches, refines, and selects courses
4. Backend scores/ranks the selected courses → returns recommendations

## Configuration

### Scoring Weights
Adjust recommendation priorities in `settings.py`:

```python
WEIGHT_SIMILARITY = 0.6          # Content matching importance
SKILL_GAP_BONUS = 0.3           # Bonus for gap-filling courses
CAREER_GOAL_BONUS = 0.5         # Career transition focus
EXISTING_SKILL_PENALTY = 0.2    # Penalty for redundant courses
```

### API Limits
- Resume file size: 10MB maximum
- PDF format only
- Rate limiting: Built-in async retry/backoff for the LLM API

## Deployment

### Production Considerations
1. **Environment Variables**: Secure credential management
2. **HTTPS**: SSL certificates for production
3. **CORS**: Configure allowed origins
4. **Error Handling**: Comprehensive logging and monitoring
5. **Caching**: Consider caching frequent API calls

### Docker Deployment
```dockerfile
FROM python:3.9-slim
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Usage Examples

### Basic Resume Analysis
1. Navigate to Upload page
2. Select PDF resume file
3. Optionally specify target role and industry
4. Click "Analyze Resume"
5. Review detailed scoring and feedback

### Getting Course Recommendations
1. Complete resume analysis or use Search page
2. Enter specific career goals
3. System generates personalized recommendations
4. Browse courses with relevance scores
5. Save interesting courses for later

### Career Transition Support
The system automatically detects major career changes and:
- Uses AI to generate appropriate search terms
- Prioritizes foundational courses
- Provides transition-specific feedback
- Focuses on skill gap identification

## Troubleshooting

### Common Issues

**LLM Connection**
- Verify `LLM_API_KEY` is set (or expect offline mock responses)
- Confirm `LLM_BASE_URL` and `LLM_MODEL` match your provider (see the provider table above)
- For Ollama, make sure the model is pulled (`ollama pull qwen2.5:14b`) and the server is running

**SSG API Authentication**
- Confirm client ID and secret are correct
- Test token endpoint accessibility
- Monitor rate limits and quotas

**PDF Processing Errors**
- Ensure files are valid PDFs
- Check file size limits
- Verify text is extractable (not image-only)

### Debug Mode
Enable detailed logging by setting `ENV=debug` in your environment.

## Contributing

### Development Setup
1. Follow installation steps
2. Install development dependencies
3. Run tests: `python -m pytest`
4. Follow code style guidelines

### Key Areas for Enhancement
- Additional AI models for analysis
- More sophisticated career path detection
- Integration with additional course providers
- Mobile-responsive improvements
- Advanced filtering and search capabilities

---

Built with ❤️ for Singapore's workforce development and lifelong learning initiatives.