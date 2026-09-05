"""LangSmith tracing setup.

When LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY are configured, every
LangGraph node execution is exported to LangSmith automatically (LangGraph's
compiled graph is a langchain-core Runnable, so it participates in the
ambient tracing context with zero extra code), and every LLM call wrapped
with @traceable in services/llm_provider.py is exported as a nested LLM
span (model, prompt, response, latency, token usage where the provider
reports it).

This is a separate, complementary channel from the custom EventBus
(observability/events.py): the EventBus drives the Live Trace tab in the
UI (works with zero external services); LangSmith gives an external,
persistent, queryable trace store for debugging/evaluating agent behavior
across runs. Neither depends on the other.

configure() is called once at process startup (see main.py) and is a no-op
if tracing isn't enabled - nothing about the pipeline changes when
LangSmith isn't configured.
"""
from __future__ import annotations

import logging
import os

from config.settings import get_settings

logger = logging.getLogger("aivar.langsmith")


def configure() -> None:
    settings = get_settings()
    if not settings.langsmith_tracing:
        logger.info("LangSmith tracing disabled (set LANGCHAIN_TRACING_V2=true in .env to enable)")
        return
    if not settings.langsmith_api_key:
        logger.warning("LANGCHAIN_TRACING_V2=true but LANGCHAIN_API_KEY is not set - tracing stays disabled")
        return

    # langchain-core / LangGraph / langsmith's own SDK all read these directly
    # from the environment, so setting them here (sourced from our own
    # centrally-managed Settings/.env) is sufficient - no per-call wiring needed.
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    logger.info("LangSmith tracing enabled for project '%s'", settings.langsmith_project)
