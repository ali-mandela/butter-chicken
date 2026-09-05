# Aivar Test Orchestrator — Web UI

A Streamlit control panel for managing autonomous test orchestration runs. This is the same Aivar engine as the CLI, just with a web interface for easier access and monitoring.

## Running the App

```bash
uv run streamlit run frontend/app.py
```

The app will be available at `http://localhost:8501` by default.

## Tabs

### Run

Input form to start a new test pipeline run:

- **Application URL** (required): The URL of the app to test.
- **Username** (optional): For authenticated testing.
- **Password** (optional): For authenticated testing (never shown).
- **Intent** (optional): A natural-language description of what to test. Leave blank to sweep the entire app.
- **PRD Upload** (optional): Upload a `.md` or `.txt` file to guide spec-led testing.
- **Advanced Options**:
  - Max flows: How many test flows to plan (1-10, default 4).
  - Max pages: How many pages to explore (1-15, default 5).
  - Safe mode: Fill forms but never submit (use on production sites).
  - Headless: Run the browser without a visible window (default enabled).
  - Heal: Automatically repair broken element selectors during execution.

#### Input Modes

The app infers the **mode** from your inputs:

- **Sweep (full coverage)**: No intent, no PRD. Tests every page, form, and flow.
- **Focused**: An intent is provided. Testing is narrowed to particular features or flows.
- **Spec-led**: A PRD is uploaded. Testing is driven by the product requirements.

**Important:** A blank intent does not mean "do nothing". It means "cover everything". Sweep mode is the strictest mode, not the laziest.

After clicking **Run Pipeline**, the app displays:

- A **Decision Ledger** showing every choice the orchestrator made (explore → plan → critique → generate → validate → execute → triage → report).
- **Metrics**: flows passed/total, gaps remaining, heals applied, defects found, cost, and duration.
- **Summary line**: One-liner recap of results.
- **Escalation alert** (if applicable): Reason the pipeline was escalated and did not complete normally.

### Results

After a run completes:

- **Generated Test Files**: Each pytest file is shown with syntax highlighting and a download button.
- **Coverage Gaps**: A table of untested features or flows, with severity and evidence.
- **Untested Flow Risk**: Features that should have been tested but were not.
- **Full Report**: An embedded interactive HTML report with all details (flows, failures, heals, gaps, decisions).
- **Download Buttons**: Export the HTML or JSON report to your local machine.

### History

Browse all previous runs in the database:

- **Run list**: Newest first, showing URL, mode, flows passed/total, gaps, cost, and duration.
- **Run details**: Click a run ID to see its decisions and gaps.

## Sidebar: Connection Status

Always visible on the left:

- **LLM Configuration**: Shows which models are available. If the `OPENROUTER_API_KEY` is not set, you'll see a warning; planning will not work.
- **Database Connection**: Shows whether the store is connected and ready.

## API Keys and Secrets

The app **never displays or logs** the password or the API key, even in logs or error messages. All secrets are resolved from environment variables or .env files at startup.

## Behavior Identical to CLI

This control panel calls the exact same `aivar.orchestrator.run_pipeline()` function as the CLI. The only difference is the UI layer; test planning, execution, healing, and reporting are identical.

## Troubleshooting

- **Pipeline fails with "Failed to load LLM config"**: Set `OPENROUTER_API_KEY` in your environment or in a `.env` file at the project root.
- **Store shows "not available"**: The database module is still being initialized; run the pipeline anyway, and it will still work (but results won't be saved to the database).
- **Pipeline times out**: Increase `max_flows` and `max_pages` limits, or use a smaller intent to narrow the scope.
