# aivar v2 — self-healing QA agent

## Core Principle

The model runs once to author a test, then gets out of the way. Every CI run is deterministic. Healing applies to locator drift only, never to assertions.

## Build Steps

- [x] Step 0: Scaffold + type contracts
- [x] Step 1: Deterministic executor
- [x] Step 2: Resolution cascade tiers 0+1 + configurable target + secrets
- [x] Step 3: Planner + compiler (first LLM call)
- [ ] Step 4: Failure classification
- [ ] Step 5: Tier 2 + heal loop
- [ ] Step 6: Spec-anchored probes
- [ ] Step 7: Visual regression
- [ ] Step 8: Report + approval CLI

## Run the tests

```bash
uv sync
uv run pytest
```

## Quick Start

### Compile a test

The `compile` command takes a plain-English intent and generates a test by running the LLM planner and a dry-run on the live app:

```bash
uv run python -m aivar.cli compile "Log in and verify the products page loads" --url https://www.saucedemo.com --out examples/generated.json
```

### Run a compiled test

```bash
uv run python -m aivar.cli run examples/generated.json
```

## Run a test (programmatic)

Use `load_test` to read a compiled test and `run_test` to execute it:

```python
from aivar.testfile import load_test
from aivar.executor import run_test

test = load_test("examples/login.json")
result = run_test(test)
print(f"Status: {result.status}")
print(f"Failed steps: {[r.step_id for r in result.results if r.status == 'failed']}")
```

## Configuration

### Target

Use the `Target` class to configure the browser and target URL:

```python
from aivar.target import Target
from aivar.executor import run_test

target = Target(
    url="https://example.com",
    name="staging",
    viewport_width=1920,
    viewport_height=1080,
    headless=False,
)
result = run_test(test, target=target)
```

Or create a Target from environment variables:

```python
target = Target.from_env(url="https://example.com")
```

### Environment Variables

#### LLM Configuration

- `OPENROUTER_API_KEY`: API key for OpenRouter (required for compilation)
- `AIVAR_LLM_MODELS`: Comma-separated list of model IDs to try in order (default: `minimax/minimax-m3:free,nvidia/nemotron-3-super-120b-a12b:free`)
  - **Important**: Only free-tier models (ending in `:free`) work with the free account. Paid models return 403.

#### Test Credentials

- `AIVAR_USERNAME`: Username for test login steps (replaces `${AIVAR_USERNAME}` in test files)
- `AIVAR_PASSWORD`: Password for test login steps (replaces `${AIVAR_PASSWORD}` in test files)

#### Target Configuration

- `AIVAR_TARGET_URL`: The URL to test (required if not passed to `Target.from_env()`)
- `AIVAR_TARGET_NAME`: Name of the target (default: "default")
- `AIVAR_VIEWPORT_WIDTH`: Viewport width in pixels (default: 1280)
- `AIVAR_VIEWPORT_HEIGHT`: Viewport height in pixels (default: 720)
- `AIVAR_HEADLESS`: "0", "false", "no" (case-insensitive) for non-headless; otherwise true (default: true)

### Secret Substitution

Test files support `${NAME}` and `${NAME:-default}` syntax for secrets:

- `${NAME}` — resolves from the `NAME` environment variable; raises an error if not set
- `${NAME:-default}` — resolves from the `NAME` environment variable if set, else uses `default`

Example in a test file:

```json
{
  "value": "${DATABASE_PASSWORD}"
}
```

**IMPORTANT:** Real applications must use `${NAME}` with NO default so no secret is ever committed to version control. Only use defaults for public demo values or test data.

When logging, secrets are redacted as `***` so resolved values never appear in logs.

### Resolution Cascade

- **Tier 0**: Use the compiled selector if present
- **Tier 1** (ACTION steps only): If Tier 0 misses or selector is None, attempt heuristic resolution using element snapshot and target text matching
- **Tier 0 only** (ASSERTION steps): Assertions never use Tier 1; a missing element is a candidate bug, not a lookup problem
