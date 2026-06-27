# SkillPilot 🧭

An AI agent that reads your resume and recommends relevant **Singapore SkillsFuture**
courses for your career goal. It scores your resume, finds courses that close your skill
gaps, and explains *why* each one is recommended.

- **Backend:** FastAPI (Python)
- **AI:** any OpenAI-compatible LLM — defaults to **Groq** (free). Swap to Ollama / OpenRouter by changing env vars.
- **Recommender:** a real tool-calling **agent** that searches the course catalog, inspects courses, refines its queries, and returns a ranked set.
- **Frontend:** React + Tailwind in a single `index.html` (no build step).

---

## Quick start

### 1. Prerequisites
- **Python 3.9+**
- A free **Groq API key** — for the AI (resume analysis + the recommendation agent)
- **SSG-WSG API credentials** — for live SkillsFuture course data

> You can run it **without** keys to try the UI — it boots in offline "mock mode" with
> canned responses. For real results you'll want at least a Groq key.

### 2. Get the project
```bash
git clone https://github.com/tomwastaken0/SkillPilot.git
cd SkillPilot
```

### 3. Install dependencies
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Add your keys
Copy the example env file and fill in your own keys:
```bash
# Windows:
copy .env.example .env
# macOS/Linux:
cp .env.example .env
```
Then open `.env` and set:
```env
LLM_API_KEY=gsk_your_groq_key_here
SSG_CLIENT_ID=your_ssg_client_id
SSG_CLIENT_SECRET=your_ssg_client_secret
```
`.env` is git-ignored, so your keys stay on your machine and never get committed.

### 5. Run it
```bash
python main.py
```
It starts at **http://localhost:8000** and opens your browser. Upload a resume (PDF),
set a career goal, and get recommendations.

---

## Getting the keys

### Groq (free, no credit card)
1. Sign up at **https://console.groq.com**
2. Go to **API Keys** → https://console.groq.com/keys
3. **Create API Key**, copy it (shown once), and paste it into `.env` as `LLM_API_KEY`.

The default model is `llama-3.3-70b-versatile`, which supports the tool-calling the agent needs.

### SSG-WSG (Singapore SkillsFuture course data)
The course catalog comes from Singapore's official SSG-WSG API, which uses OAuth2
client credentials.
1. Register at the **SSG-WSG Developer Portal**: https://developer.ssg-wsg.gov.sg
2. Create an application to get a **Client ID** and **Client Secret**.
3. Put them in `.env` as `SSG_CLIENT_ID` / `SSG_CLIENT_SECRET`.

> Without valid SSG credentials, resume scoring still works, but course
> search/recommendations will return no courses.

---

## Use a different AI model (optional)

The LLM client is provider-agnostic — change three values in `.env`:

| Provider   | `LLM_BASE_URL`                   | `LLM_MODEL` example                    | Notes |
|------------|----------------------------------|----------------------------------------|-------|
| **Groq**   | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile`              | default, free |
| **Ollama** | `http://localhost:11434/v1`      | `qwen2.5:14b`                          | fully local; set `LLM_API_KEY=ollama` and `ollama pull` the model first |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.3-70b-instruct` | many models, one key |

---

## Project structure
```
main.py        # thin FastAPI routes
settings.py    # all config (LLM, agent, SSG, scoring weights)
index.html     # React + Tailwind frontend (served by the backend)
app/
  llm.py       # provider-agnostic OpenAI-compatible client (+ offline mock mode)
  agent.py     # tool-calling recommendation loop (+ deterministic fallback)
  tools.py     # agent tools: search_courses, get_course_details, submit_recommendations
  ssg.py       # SSG-WSG course directory client
  scoring.py   # deterministic course scoring (uses settings.py weights)
  resume.py    # PDF extraction + resume analysis/helper
  prompts.py   # prompt templates
  schemas.py   # pydantic request/response models
tests/         # pytest suite
```

Run the tests with:
```bash
python -m pytest
```

More detail (API endpoints, scoring, architecture) is in [`docs/README.md`](docs/README.md).

---

## Troubleshooting
- **AI responses look generic / canned** → no `LLM_API_KEY` set (you're in mock mode). Add a Groq key.
- **No courses come back** → check `SSG_CLIENT_ID` / `SSG_CLIENT_SECRET` are valid.
- **Port 8000 in use** → edit the port at the bottom of `main.py`.
