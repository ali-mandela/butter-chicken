from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as test_runs_router
from config.settings import get_settings
from observability.langsmith_tracing import configure as configure_langsmith

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
configure_langsmith()

app = FastAPI(
    title="Autonomous Test Orchestration Agent",
    description="Backend for the AIVAR autonomous QA testing platform",
    version="0.1.0",
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(test_runs_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "llm_provider": settings.llm_provider}
