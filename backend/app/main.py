import logging
import time

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.executor import run_test
from app.llm import plan_test
from app.memory import save_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("aivar")

app = FastAPI(title="AIVAR QA Agent")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.0f}ms)")
    return response

DEFAULT_URL = "https://www.saucedemo.com"
DEFAULT_USER = "standard_user"
DEFAULT_PASS = "secret_sauce"


class IntentRequest(BaseModel):
    intent: str


class ExecuteRequest(BaseModel):
    intent: str
    custom_target: bool = False
    url: str | None = None
    username: str | None = None
    password: str | None = None


def resolve_target(req: ExecuteRequest):
    if req.custom_target:
        if not req.url or not req.username or not req.password:
            raise HTTPException(400, "custom_target=True requires url, username, password")
        return req.url, req.username, req.password
    return DEFAULT_URL, DEFAULT_USER, DEFAULT_PASS


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/plan")
def plan(req: IntentRequest):
    return plan_test(req.intent)


@app.post("/execute")
def execute(req: ExecuteRequest):
    plan_result = plan_test(req.intent)
    url, username, password = resolve_target(req)
    result = run_test(plan_result["steps"], url, username, password)
    save_run(req.intent, url, result)
    return result
