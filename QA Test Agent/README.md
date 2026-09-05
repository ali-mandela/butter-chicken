# Autonomous Test Orchestration Agent (AIVAR)

An autonomous, multi-agent QA testing platform: give it an application URL,
an auth method, and a PRD, and it discovers the app, plans a test strategy,
validates the plan, generates test cases and Playwright scripts, validates
the scripts, executes them against a real browser, classifies and heals
failures within a bounded retry budget, and writes a final Markdown report —
while streaming everything it does live to a dashboard.

## Status: full pipeline implemented

```
Discovery -> PRD Analysis -> Planning -> Plan Validation
          -> Test Case Generation -> Script Generation -> Script Validation
          -> Execution
             -> (no failures) ---------------------------> Reporting
             -> (failures) -> Failure Classification -> Healing -> Reporting
```

Every stage does real work, nothing is mocked at the browser or LLM layer:

- **Discovery** launches a real headless Chromium via Playwright, crawls the
  target app within safety bounds, and saves real screenshots + DOM
  snapshots per page.
- **PRD Analysis, Planning, Plan Validation, Test Case Generation, Script
  Generation, Script Validation, Failure Classification, and Healing** all
  call a real LLM (Gemini by default) through a provider-agnostic interface,
  with every output validated against a Pydantic schema.
- **Execution** runs the generated Playwright scripts in real, isolated
  browser contexts — real screenshots on failure, real video recordings,
  real Playwright trace files, real console/network capture. Test cases
  marked `parallel_safe` with no unmet `depends_on` run concurrently when
  Parallel Execution is on; everything else runs in dependency order.
- **Healing** repairs only automation defects (selector drift, timing,
  script-logic bugs) — never application bugs or assertions (Section 19's
  hard rule) — validates every repair independently via the Repair
  Validator before writing it to disk, and **re-executes for real** to
  confirm the fix, bounded by `max_healing_attempts` per test case.
- **Reporting** assembles the final Markdown report entirely from the run's
  real, persisted state (execution records, failures, healing attempts) —
  the only LLM-generated part is the Executive Summary paragraph, with a
  deterministic fallback if that call fails.

This was verified end-to-end with an offline harness (`FakeProvider`
standing in for the LLM, real Playwright underneath): a deliberately broken
selector caused a real execution failure, the Failure Classifier correctly
labeled it `SELECTOR_FAILURE`, the Healer proposed a real fix, the Repair
Validator approved it, the script was rewritten on disk, **re-executed for
real, and passed** — and the resulting report accurately reflected all of
it (`PASS (healed)`, 1 healing attempt, 100% requirement coverage). See
"Verified this session" below for the live (non-harness) run too.

## Why these technical choices

- **LangGraph** (not Google ADK) for orchestration: this problem is a state
  machine with conditional branches and bounded retry loops (plan revision,
  healing), not a conversational agent. LangGraph models that directly with
  explicit nodes/edges over a typed state object, and composes cleanly with
  FastAPI + Playwright. See `backend/orchestration/graph.py`.
- **LangSmith** for LLM/agent observability (see below) — complements, does
  not replace, the custom Live Trace UI.
- **Gemini by default**, but never hard-coded: `backend/services/llm_provider.py`
  defines an abstract `LLMProvider`. Six providers are implemented —
  **Gemini, OpenAI, Azure OpenAI, Grok (xAI), Groq (fast-inference hardware,
  a different company from xAI despite the near-identical name), and
  Sarvam AI** — and the choice is a **per-run UI field**, not just a
  server-wide `.env` default: the Config form's "LLM Provider" dropdown +
  "Model" field (`frontend/src/pages/ConfigPage.jsx`) are stored on
  `RunConfig.llm_provider`/`llm_model` and threaded through every agent
  that calls the LLM. A run with no explicit choice falls back to
  `LLM_PROVIDER`/`MODEL` in `.env`.
  - **Grok and Groq** both use documented OpenAI-compatible APIs (verified
    against docs.x.ai and console.groq.com respectively) — solid
    integrations. **Groq verified live** with a real key: both
    `generate_text` and the `generate_structured` JSON-schema path (what
    every agent actually calls) work, and a real run advanced through
    Discovery → PRD Analysis → Planning → Plan Validation before correctly
    failing at the (bounded, 2-revision) plan-validation loop with
    substantive, specific rejection reasons.
  - **Sarvam AI verified live** too: needs both a standard `Authorization:
    Bearer` header and a separate `api-subscription-key` header (added via
    `default_headers`) — confirmed correct because a live key with no
    account credits got a clean `402 No credits available` from Sarvam's
    own API, not a 401/auth error. So the integration is confirmed
    correct; whether it *works for you* depends on your account having
    credits, which is unrelated to this code.
  - Model presets shown in the UI (`ConfigPage.jsx`'s `MODEL_PRESETS`) were
    checked against each provider's live docs, not recalled from training
    data — providers ship new models often, so treat the dropdown as a
    helpful starting point (it's an editable combo-box, not a hard list).
- **SQLite, no Docker required**: `backend/storage/db.py` uses SQLAlchemy
  against `sqlite:///./aivar.db` by default. Swapping to Postgres later is a
  one-line `DATABASE_URL` change.
- **Credentials never touch the LLM or logs**: `backend/security/secrets.py`
  keeps credentials in an in-memory, Fernet-encrypted store keyed by an opaque
  `credential_ref`; `TestRunState` and all agent prompts only ever see that
  reference, never the raw value. The event bus also redacts any field whose
  key looks secret-like before logging or broadcasting it.

## Observability: two complementary channels

1. **Custom EventBus -> Live Trace UI** (`backend/observability/events.py`) —
   works with zero external services. Every agent emits start/complete/fail
   events; they're logged, kept in per-run history, fanned out over
   WebSocket, and rendered in the frontend's Live Trace tab in real time.
   This is what powers the dashboard you see while a run is in progress.

2. **LangSmith** (`backend/observability/langsmith_tracing.py`) — optional,
   external, persistent trace store for debugging/evaluating agent behavior
   *across* runs (not just the one you're watching live). Set
   `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` in `.env` and:
   - Every LangGraph node execution is traced automatically — the compiled
     graph is a langchain-core `Runnable`, so no extra code was needed for
     graph-level spans.
   - Every LLM call is traced as a nested child span via `@traceable` on
     each provider's `generate_text` (see `services/llm_provider.py`) —
     model name, prompt, response, and latency per call, nested under the
     agent node that made it.
   - When tracing is off (the default), this is fully inert: `configure()`
     logs that it's disabled and returns, nothing else changes.

## Project layout

```
backend/
  agents/<name>/{prompt.py, agent.py}   one folder per agent, own system prompt
  browser/                              Playwright manager, discovery crawler, script executor
  orchestration/graph.py                LangGraph state machine (full pipeline)
  schemas/state.py                      central Pydantic TestRunState
  services/{llm_provider,run_manager}   LLM abstraction + run lifecycle
  security/{secrets,domain_policy}      credential store, URL/domain allowlist
  storage/{db,run_repository}           SQLite persistence + artifact folders
  observability/{events,langsmith_tracing}  live event bus + optional LangSmith tracing
  api/routes.py                         REST + WebSocket endpoints
  main.py                               FastAPI app
frontend/
  src/pages/{ConfigPage,DashboardPage}.jsx
  src/components/{PipelineSteps,LiveTrace,TabBar}.jsx
  src/services/api.js                   fetch + WebSocket client
runs/<RUN-ID>/...                       per-run artifacts (screenshots, DOM, scripts, videos, traces, report, ...)
```

## Running it locally

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium
copy ..\.env.example ..\.env  # then fill in GEMINI_API_KEY (or switch LLM_PROVIDER)
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, fill in an application URL + PRD file, click
**Start Autonomous Testing**, and watch the Live Trace tab.

## What "no fake execution" means here

Without a configured `GEMINI_API_KEY` (or another provider), a run will
complete Discovery for real, then fail cleanly at the PRD Analysis step with
`GEMINI_API_KEY is not configured` — visible in the Live Trace and the run's
`error` field. Every agent raises rather than silently returning placeholder
data. With a real key configured, every remaining stage runs against the
real document, the real discovered application, and a real browser.

## Verified this session

- `backend/main.py` imports cleanly, `/api/health` responds.
- **Live run via the API + a real browser session (no LLM key)**: a run
  against `https://example.com` really launched Chromium, crawled the page,
  and saved a real screenshot + DOM snapshot to `runs/<RUN-ID>/screenshots`
  and `.../dom`, then failed honestly at PRD Analysis — visible via REST,
  WebSocket trace, and in the React dashboard (config form -> run -> live
  pipeline/trace UI, Execution tab) in a real browser session.
- **Offline harness (`FakeProvider` + real Playwright) exercising
  Execution -> Failure Classification -> Healing -> Reporting**: generated a
  deliberately wrong selector, watched it really fail
  (`AssertionError: Locator expected to be visible`), got classified
  `SELECTOR_FAILURE`, got a real repair proposal, had that repair validated
  and written to disk, re-executed it for real, watched it pass, and got a
  final Markdown report whose table correctly showed
  `PASS (healed)` / `Healing: Yes` / `100%` coverage. Real screenshot,
  video, and Playwright trace files were confirmed on disk for both the
  failing and the healed run.
- Fixed a real bug found via that harness run: dynamically importing
  generated scripts wrote `__pycache__/*.pyc` into the scripts artifact
  folder, which would have broken the Artifacts tab's file listing/download
  endpoint. Fixed with `sys.dont_write_bytecode = True` plus a defensive
  is-file filter in `GET /artifacts`.
- Fixed a real bug in `.env` handling: `config/settings.py` only ever read
  `os.environ` directly - nothing loaded a `.env` file, so creating one had
  no effect unless variables were exported into the shell manually. Added
  `load_dotenv()` (pinned `python-dotenv` explicitly instead of relying on
  it being someone else's transitive dependency) and verified it actually
  picks up a value from `.env` before/after the fix.
- **Live run via the API with a real Groq key + real PRD text**: advanced
  through Discovery → PRD Analysis → Planning → Plan Validation for real,
  then correctly stopped after the bounded 2-revision Plan Validator loop
  rejected the plan with specific, substantive reasons (the test PRD
  described login/search features example.com doesn't have) - this is the
  "never trust raw LLM output, discovery before planning" design working
  as intended, not a bug.
- **Live-verified Groq's `generate_structured` path** (the JSON-schema call
  every agent actually makes, not just raw text) with a real key.
- **Live-verified Sarvam's auth scheme** with a real key: got a clean `402
  No credits available` from Sarvam's own API rather than a 401, confirming
  both required headers (`Authorization: Bearer` + `api-subscription-key`)
  are correct - the integration works, independent of any account's
  billing status.

## Security notes

- Credentials: in-memory only, Fernet-encrypted, referenced by opaque id,
  never logged/sent to the LLM (`backend/security/secrets.py`).
- Domain policy: blocks localhost/link-local/metadata endpoints by default;
  set `ALLOWED_DOMAINS` in `.env` to restrict testing to specific hosts
  (`backend/security/domain_policy.py`).
- Destructive-action guard: Discovery skips any element whose text/aria-label
  matches destructive keywords (delete/purge/wipe/close-account) so the
  crawler never triggers irreversible actions.
- Generated scripts are statically checked (`ast.parse`, forbidden-pattern
  regex for `os.system`/`subprocess`/`eval`/`exec`/`time.sleep`) before an
  LLM review pass — a script is only marked valid if both agree.
- **Sandboxing caveat**: generated scripts run in-process (dynamically
  imported, not in a separate OS process/container per script). Static
  checks + the LLM review pass block the obviously dangerous operations,
  but this is a controlled environment, not a full untrusted-code sandbox.
  A hardened deployment should run `execute_script` in a separate,
  resource-limited worker process or container per test case.

## Fixed this session

- **Discovery now logs in before crawling** (`browser/discovery.py`'s
  `attempt_login`, wired into `agents/discovery/agent.py`). Previously
  Discovery only ever saw the login page for any app requiring auth -
  confirmed live against saucedemo.com, which went from discovering 1 page
  (login only) to discovering the authenticated inventory page after this
  fix. Best-effort heuristic (looks for a password field, fills a paired
  username field or token, submits) - not every login form will match.
- **Sticky sidebar was silently clipping content**: `.pipeline-sidebar` had
  `position: sticky` with no height cap, so once its content (10 steps +
  legend) was taller than the visible viewport, the bottom rows (the
  Completed/Running/Waiting/Failed legend) became permanently unreachable
  by scrolling - a stuck/sticky element's own overflow doesn't scroll into
  view by scrolling the page. Fixed with `max-height: calc(100vh - 40px)`
  + `overflow-y: auto` so the sidebar scrolls internally instead.
- **New Architecture view** (`ArchitectureDiagram.jsx` +
  `ParallelExecutionDiagram.jsx`, hand-built SVG, no new dependency): shows
  the actual LangGraph orchestration graph - every agent node, the plan
  revision loop, the healing/re-execution loop - plus a separate diagram
  of how parallel test execution respects `depends_on`. Reachable from a
  "See how this works" toggle on the Config page (pre-run) and an
  "Architecture" tab on the Dashboard (during/after a run).
- General visual pass: Inter font, pill-style tabs, a pulsing dot on the
  "RUNNING" status badge, refined shadows/spacing.

## Known limitation found while fixing the above

**The crawler can't see client-side-routed SPA pages.** Testing against
saucedemo.com after the login fix showed Discovery still only found the
one authenticated page it landed on (inventory), not cart/checkout -
inspecting the saved DOM showed why: this build of saucedemo.com is a
React SPA where navigation links are `href="#"` placeholders with
JS-driven routing, not real hrefs. `browser/discovery.py`'s crawler only
follows real `<a href>` values (Section 8 in the original spec anticipated
this - "modern applications may be SPA... do much more than that"). A
proper fix means Discovery should also click interactive elements
(nav items, the cart icon, buttons) and observe `page.url` changes, not
just parse hrefs - not yet implemented.

## Not yet built

- **Postgres + Docker** — swap `DATABASE_URL`, add `docker-compose.yml`, for
  shared/production deployment.
- **Plan-revision loop UI** — the backend already re-invokes the Planner up
  to `MAX_PLAN_REVISIONS` when the Plan Validator rejects a plan; the
  frontend doesn't yet show individual revision diffs.
- **Firefox/WebKit** — `PlaywrightManager` already accepts an `engine`
  parameter; only Chromium is wired up as the default end-to-end.
- **True per-script sandboxing** — see the caveat above.
- **Click-based SPA discovery** — see "Known limitation" above.
