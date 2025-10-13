# settings.py
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl

class Settings(BaseSettings):
    # Use v2 model_config (env file, case-insensitive keys, ignore extras)
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",   # prevents "Extra inputs are not permitted" crashes
    )

    # Environment
    ENV: str = "dev"

    # ---- SSG-WSG (keep these EXACTLY aligned with your .env) ----
    # Your .env has these:
    # SSG_TOKEN_URL=https://public-api.ssg-wsg.sg/dp-oauth/oauth/token
    # SSG_API_BASE=https://public-api.ssg-wsg.sg
    # SSG_API_VERSION=v2.2
    SSG_TOKEN_URL: AnyHttpUrl = "https://public-api.ssg-wsg.sg/dp-oauth/oauth/token"
    SSG_API_BASE: AnyHttpUrl = "https://public-api.ssg-wsg.sg"
    SSG_API_VERSION: str = "v2.2"

    SSG_CLIENT_ID: str
    SSG_CLIENT_SECRET: str

    # Original weights (match your .env names)
    WEIGHT_SIMILARITY: float = 0.6
    WEIGHT_PRICE: float = 0.15
    WEIGHT_DURATION: float = 0.15
    WEIGHT_RATING: float = 0.10

    # New skill gap analysis weights and thresholds
    SKILL_GAP_BONUS: float = 0.3  # Bonus for courses that address skill gaps
    AREA_MATCH_BONUS: float = 0.2  # Bonus for industry/area matches
    EXISTING_SKILL_OVERLAP_THRESHOLD: float = 0.5  # Threshold above which existing skill overlap is penalized
    EXISTING_SKILL_PENALTY: float = 0.2  # Penalty for courses with too much overlap with existing skills
    
    # Career transition focus (NEW)
    CAREER_GOAL_BONUS: float = 0.5  # Major bonus for courses aligned with career goals - prioritizes aspirations over background
    
    # Content analysis weights
    OBJECTIVE_WEIGHT: float = 1.2  # How much to weight course objective in similarity
    CONTENT_WEIGHT: float = 1.0   # How much to weight course content in similarity
    TAG_WEIGHT: float = 0.8       # How much to weight course tags in similarity

settings = Settings()