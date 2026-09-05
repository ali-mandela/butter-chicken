"""Central environment-based configuration. No secrets hard-coded here."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

# The .env file lives at the project root (one level above backend/), next
# to .env.example - load it explicitly so `os.getenv(...)` below actually
# sees it, regardless of the working directory the server is started from.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class Settings(BaseModel):
    # LLM provider
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini")
    llm_model: str = os.getenv("MODEL", "gemini-2.5-flash")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    azure_openai_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_openai_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    grok_api_key: str = os.getenv("GROK_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    sarvam_api_key: str = os.getenv("SARVAM_API_KEY", "")

    # Storage
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./aivar.db")
    artifacts_root: str = os.getenv("ARTIFACTS_ROOT", "../runs")

    # Security / domain policy
    allowed_domains: str = os.getenv("ALLOWED_DOMAINS", "")  # comma separated, empty = allow-any-public
    blocked_domains: str = os.getenv(
        "BLOCKED_DOMAINS", "localhost,127.0.0.1,0.0.0.0,169.254.169.254,metadata.google.internal"
    )
    secret_encryption_key: str = os.getenv("SECRET_ENCRYPTION_KEY", "")

    # Discovery limits
    max_pages: int = int(os.getenv("MAX_PAGES", "15"))
    max_depth: int = int(os.getenv("MAX_DEPTH", "3"))
    max_actions_per_page: int = int(os.getenv("MAX_ACTIONS_PER_PAGE", "25"))
    max_discovery_time_seconds: int = int(os.getenv("MAX_DISCOVERY_TIME_SECONDS", "180"))

    # Run limits
    max_plan_revisions: int = int(os.getenv("MAX_PLAN_REVISIONS", "2"))
    default_max_healing_attempts: int = int(os.getenv("DEFAULT_MAX_HEALING_ATTEMPTS", "3"))
    agent_timeout_seconds: int = int(os.getenv("AGENT_TIMEOUT_SECONDS", "120"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "2"))

    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")

    # --- Observability: LangSmith (optional) ---
    langsmith_tracing: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    langsmith_api_key: str = os.getenv("LANGCHAIN_API_KEY", "")
    langsmith_project: str = os.getenv("LANGCHAIN_PROJECT", "aivar-autonomous-testing")
    langsmith_endpoint: str = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")


@lru_cache
def get_settings() -> Settings:
    return Settings()
