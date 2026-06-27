"""SkillPilot application package.

Modules:
  schemas  - pydantic request/response models
  llm      - provider-agnostic (OpenAI-compatible) async LLM client
  prompts  - prompt templates
  ssg      - SSG-WSG course directory API client
  scoring  - deterministic course scoring
  resume   - PDF extraction + resume analysis/helper
  tools    - agent tool definitions + dispatch
  agent    - the tool-calling recommendation agent
"""

__version__ = "3.0"
