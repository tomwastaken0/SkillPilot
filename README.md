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
- **AWS Bedrock**: Claude AI integration for resume analysis and course matching
- **SSG-WSG API**: Official Singapore SkillsFuture course data
- **PyPDF2**: PDF text extraction
- **Pydantic**: Data validation and settings management

### Frontend
- **React**: Component-based UI framework
- **Tailwind CSS**: Utility-first styling
- **Vanilla JavaScript**: No build process required

### Infrastructure
- **AWS Services**: Bedrock for AI capabilities
- **OAuth2**: Secure API authentication
- **Environment-based Configuration**: Flexible deployment settings

## Installation

### Prerequisites
- Python 3.8+
- AWS Account with Bedrock access
- SSG-WSG API credentials

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
   Create a `.env` file with the following:
   ```env
   # Environment
   ENV=dev

   # AWS Credentials (for Claude AI)
   AWS_ACCESS_KEY_ID=your_aws_access_key
   AWS_SECRET_ACCESS_KEY=your_aws_secret_key
   AWS_SESSION_TOKEN=your_session_token

   # SSG-WSG API Configuration
   SSG_TOKEN_URL=https://public-api.ssg-wsg.sg/dp-oauth/oauth/token
   SSG_CLIENT_ID=your_ssg_client_id
   SSG_CLIENT_SECRET=your_ssg_client_secret
   SSG_API_BASE=https://public-api.ssg-wsg.sg
   SSG_API_VERSION=v2.2

   # Scoring Configuration
   WEIGHT_SIMILARITY=0.6
   WEIGHT_PRICE=0.15
   WEIGHT_DURATION=0.15
   WEIGHT_RATING=0.10

  # New skill gap analysis weights and thresholds
  SKILL_GAP_BONUS=0.3
  AREA_MATCH_BONUS=0.2
  EXISTING_SKILL_OVERLAP_THRESHOLD=0.5
  EXISTING_SKILL_PENALTY=0.2

  # Career transition focus - heavily prioritize target career goals
  CAREER_GOAL_BONUS=0.5

  # Content analysis weights (for better course content matching)
  OBJECTIVE_WEIGHT=1.2
  CONTENT_WEIGHT=1.0
  TAG_WEIGHT=0.8
   ```

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
The application uses AWS Bedrock with Claude for:
- Resume content analysis and scoring
- Career transition detection
- Intelligent search term generation
- Course relevance assessment
- Personalized recommendation explanations

### Scoring Algorithm
The recommendation system uses a multi-factor scoring approach:

1. **Content Similarity** (40%): Matches course content with career goals
2. **Skill Gap Coverage** (20%): Prioritizes courses filling identified gaps
3. **Price Factor** (10%): Considers course cost
4. **Duration Factor** (10%): Balances time investment
5. **Relevance Bonus** (10%): AI-assessed career alignment
6. **Career Transition Bonus** (10%): Extra weight for career changers

### Data Flow
1. User uploads resume → PDF text extraction
2. AI analyzes content → Generates scores and feedback
3. User defines career goals → AI generates search terms
4. System queries SSG API → Retrieves course data
5. AI scores and ranks courses → Returns recommendations

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
- Rate limiting: Built-in retry logic for AWS Bedrock

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

**AWS Bedrock Connection**
- Verify AWS credentials are valid
- Ensure region is set to `us-east-1`
- Check Bedrock service access permissions

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