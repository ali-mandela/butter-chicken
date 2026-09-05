"""Streamlit control panel for Aivar Test Orchestrator.

A web UI for managing autonomous test orchestration runs, viewing results,
and tracking test history. Talks to the same aivar package as the CLI,
so behavior is identical.
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path

import streamlit as st

from aivar.llm import LLMConfig, LLMError
from aivar.orchestrator import run_pipeline, OrchestratorConfig
from aivar.report import render_pipeline_html
from aivar.contracts import PlanMode

logger = logging.getLogger("aivar")


# ============================================================================
# Page Configuration
# ============================================================================

st.set_page_config(
    page_title="Aivar Test Orchestrator",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# Session State Initialization
# ============================================================================

if "current_report" not in st.session_state:
    st.session_state.current_report = None
if "current_state" not in st.session_state:
    st.session_state.current_state = None
if "run_results" not in st.session_state:
    st.session_state.run_results = None


# ============================================================================
# Sidebar: Connection Status
# ============================================================================

st.sidebar.title("Connection Status")

# LLM Status
st.sidebar.subheader("LLM Configuration")
try:
    llm_config = LLMConfig.from_env()
    models_display = ", ".join(llm_config.models) if llm_config.models else "None"
    st.sidebar.success(f"Connected")
    st.sidebar.caption(f"Models: {models_display}")
except LLMError as e:
    st.sidebar.error(f"LLM Error: {str(e)}")
    st.sidebar.warning(
        "Planning will not work without a valid OPENROUTER_API_KEY. "
        "Set it in the environment or in a .env file at the project root."
    )

# Database Status
st.sidebar.subheader("Database Connection")
try:
    from aivar import store

    # store.health() returns a (ok, message) tuple, not a dict.
    connected, detail = store.health()
    if connected:
        st.sidebar.success("Connected")
        st.sidebar.caption(detail)
    else:
        st.sidebar.warning("Not connected")
        st.sidebar.caption(detail)
except ImportError:
    st.sidebar.info("Store not available")
except Exception as e:
    st.sidebar.warning(f"Store error: {str(e)}")


# ============================================================================
# Main Content
# ============================================================================

st.title("Aivar Test Orchestrator")

# Create tabs
tab1, tab2, tab3 = st.tabs(["Run", "Results", "History"])


# ============================================================================
# Tab 1: Run
# ============================================================================

with tab1:
    st.header("Run a Test Pipeline")

    # URL input (required)
    app_url = st.text_input(
        "Application URL",
        placeholder="https://www.saucedemo.com",
        help="The URL of the application to test",
    )

    # Optional credentials
    col1, col2 = st.columns(2)
    with col1:
        username = st.text_input("Username (optional)", help="For authenticated testing")
    with col2:
        password = st.text_input(
            "Password (optional)",
            type="password",
            help="For authenticated testing",
        )

    # Intent
    intent = st.text_area(
        "Intent (optional)",
        height=80,
        placeholder="e.g., 'Test the login flow and product selection'",
        help="Leave blank to sweep the whole app (full coverage). "
        "A specific intent narrows testing to particular features.",
    )

    # PRD file upload
    prd_file = st.file_uploader(
        "Product Requirements Document (optional)",
        type=["md", "txt"],
        help="Upload a .md or .txt file to guide spec-led testing",
    )

    # Advanced options
    with st.expander("Advanced Options"):
        col1, col2 = st.columns(2)
        with col1:
            max_flows = st.slider(
                "Max flows",
                min_value=1,
                max_value=10,
                value=4,
                help="Maximum number of test flows to plan",
            )
            max_pages = st.slider(
                "Max pages",
                min_value=1,
                max_value=15,
                value=5,
                help="Maximum pages to explore during app discovery",
            )
        with col2:
            safe_mode = st.checkbox(
                "Safe mode",
                value=False,
                help="Fill forms but never press submit (use on production sites)",
            )
            headless = st.checkbox(
                "Headless",
                value=True,
                help="Run browser without displaying a window",
            )

        heal = st.checkbox(
            "Heal broken locators",
            value=True,
            help="Automatically repair broken element selectors during execution",
        )

    # Show mode
    mode_description = ""
    if not intent and prd_file is None:
        mode = "Sweep (full coverage)"
        mode_description = "A blank prompt means 'cover everything', not 'do nothing'. Every page, form, and flow will be tested."
    elif intent:
        mode = "Focused"
        mode_description = f"Testing focused on: {intent[:50]}..."
    else:
        mode = "Spec-led"
        mode_description = "Testing driven by the uploaded product requirements document."

    st.info(f"**Mode: {mode}** — {mode_description}")

    # Run button
    if st.button(
        "Run Pipeline",
        type="primary",
        key="run_pipeline_button",
    ):
        # Validate required field
        if not app_url:
            st.error("Application URL is required")
        else:
            # Save PRD file to temp location if provided
            prd_path = None
            if prd_file is not None:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".txt" if prd_file.name.endswith(".txt") else ".md",
                    delete=False,
                ) as tmp:
                    tmp.write(prd_file.read().decode("utf-8"))
                    prd_path = tmp.name

            # Run the pipeline
            with st.spinner("Running pipeline..."):
                try:
                    # Load LLM config
                    try:
                        llm_config = LLMConfig.from_env()
                    except LLMError as e:
                        st.error(f"Failed to load LLM config: {e}")
                        llm_config = None

                    if llm_config is None:
                        st.error("Cannot run pipeline without a valid LLM configuration")
                    else:
                        # Build orchestrator config
                        config = OrchestratorConfig(
                            max_flows=max_flows,
                            max_explore_pages=max_pages,
                            safe_mode=safe_mode,
                            headless=headless,
                            heal=heal,
                        )

                        # Run pipeline
                        report, state = run_pipeline(
                            url=app_url,
                            username=username if username else None,
                            password=password if password else None,
                            intent=intent if intent else None,
                            prd_path=prd_path,
                            config=config,
                            llm_config=llm_config,
                        )

                        # Store results in session state
                        st.session_state.current_report = report
                        st.session_state.current_state = state
                        st.session_state.run_results = {
                            "report": report,
                            "state": state,
                        }

                        st.success("Pipeline completed")

                except Exception as e:
                    st.error(f"Pipeline failed: {str(e)}")
                finally:
                    # Clean up temp file
                    if prd_path and os.path.exists(prd_path):
                        os.unlink(prd_path)

    # Display results if available
    if st.session_state.current_report is not None:
        st.divider()
        st.subheader("Pipeline Results")

        report = st.session_state.current_report
        state = st.session_state.current_state

        # Render decision ledger (replay style)
        st.subheader("Decision Ledger")
        st.caption(
            "This is a replay of the real ledger. The decisions and their order are "
            "exactly what the orchestrator produced."
        )

        # Create placeholder for decisions
        decisions_container = st.container()

        with decisions_container:
            for decision in report.decisions:
                # Color code the verdict
                if decision.verdict == "accept":
                    color = "🟢"
                elif decision.verdict in ("continue", "continue"):
                    color = "🟢"
                elif decision.verdict in ("replan", "regenerate"):
                    color = "🟡"
                elif decision.verdict == "escalate":
                    color = "🔴"
                else:
                    color = "⚪"

                col1, col2, col3 = st.columns([1.5, 1.5, 3])
                with col1:
                    st.caption(f"{decision.stage.value}")
                with col2:
                    st.caption(f"{color} {decision.verdict}")
                with col3:
                    st.caption(decision.reason)

                # Evidence expander
                if decision.evidence:
                    with st.expander("Evidence", expanded=False):
                        st.json(decision.evidence)

                time.sleep(0.15)

        # Metrics
        st.divider()
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Flows Passed", f"{report.flows_passed}/{report.flows_total}")
        with col2:
            st.metric("Gaps", len(report.gaps))
        with col3:
            st.metric("Heals", report.heals_applied)
        with col4:
            st.metric("Defects", report.defects_found)
        with col5:
            st.metric("Cost", f"${report.cost_usd:.4f}")
        with col6:
            st.metric("Duration", f"{report.duration_s:.0f}s")

        # Summary line
        st.info(f"**Summary:** {report.summary_line}")

        # Escalation alert
        if report.escalated:
            st.error(f"**ESCALATED:** {report.escalation_reason}")

        # Try to save to store
        try:
            from aivar import store
            store.save_run_safe(report)
            st.success("Run saved to database")
        except ImportError:
            st.info("Store not available; run not saved")
        except Exception as e:
            st.warning(f"Failed to save run: {str(e)}")


# ============================================================================
# Tab 2: Results
# ============================================================================

with tab2:
    st.header("Test Results")

    if st.session_state.current_report is None:
        st.info("No results yet. Run a pipeline in the 'Run' tab to see results here.")
    else:
        report = st.session_state.current_report

        # Generated pytest files
        st.subheader("Generated Test Files")
        if report.generated_files:
            for file_path in report.generated_files:
                file_path_obj = Path(file_path)
                if file_path_obj.exists():
                    with st.expander(f"{file_path_obj.name}"):
                        code = file_path_obj.read_text(encoding="utf-8")
                        st.code(code, language="python")

                        # Download button
                        st.download_button(
                            label=f"Download {file_path_obj.name}",
                            data=code,
                            file_name=file_path_obj.name,
                            mime="text/plain",
                        )
        else:
            st.info("No test files were generated")

        # Coverage gaps
        st.subheader("Coverage Gaps")
        if report.gaps:
            gaps_data = []
            for gap in report.gaps:
                gaps_data.append({
                    "Severity": gap.severity.value,
                    "Kind": gap.kind,
                    "Description": gap.description,
                    "Evidence": gap.evidence,
                })
            st.dataframe(gaps_data, use_container_width=True)
        else:
            st.success("No coverage gaps detected")

        # Untested flow risk
        st.subheader("Untested Flow Risk")
        if report.untested_risk:
            risk_data = []
            for description, severity in report.untested_risk:
                risk_data.append({
                    "Severity": severity,
                    "Description": description,
                })
            st.dataframe(risk_data, use_container_width=True)
        else:
            st.success("No untested flow risks identified")

        # Full HTML report
        st.subheader("Full Report")
        html_content = render_pipeline_html(report)
        st.components.v1.html(html_content, height=800, scrolling=True)

        # Download report buttons
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="Download HTML Report",
                data=html_content,
                file_name=f"{report.run_id}.html",
                mime="text/html",
            )
        with col2:
            report_json = json.dumps(report.to_dict(), indent=2)
            st.download_button(
                label="Download JSON Report",
                data=report_json,
                file_name=f"{report.run_id}.json",
                mime="application/json",
            )


# ============================================================================
# Tab 3: History
# ============================================================================

with tab3:
    st.header("Run History")

    try:
        from aivar import store

        # Get runs
        runs = store.list_runs(limit=50)

        if not runs:
            st.info("No runs in database yet")
        else:
            # Display as dataframe
            # list_runs() returns RunSummary dataclasses, so read attributes
            # rather than dict keys.
            runs_data = []
            for run in runs:
                url = run.url or ""
                runs_data.append({
                    "Run ID": run.run_id,
                    "URL": (url[:50] + "...") if len(url) > 50 else url,
                    "Mode": run.mode,
                    "Flows Passed": f"{run.flows_passed}/{run.flows_total}",
                    "Gaps": run.gaps_total,
                    "Cost": f"${run.cost_usd:.4f}",
                    "Duration": f"{run.duration_s:.0f}s",
                    "Escalated": "yes" if run.escalated else "",
                    "Created": str(run.created_at),
                })

            st.dataframe(runs_data, use_container_width=True)

            # Allow selection
            selected_run_id = st.selectbox(
                "Select a run to view details",
                options=[r.run_id for r in runs],
            )

            if selected_run_id:
                # Display decisions for selected run
                selected_run = next((r for r in runs if r.run_id == selected_run_id), None)
                if selected_run:
                    st.subheader(f"Run {selected_run_id}")
                    st.caption(f"URL: {selected_run.url}")
                    st.caption(f"Mode: {selected_run.mode}")

                    # RunSummary is only the headline row. The decisions and
                    # gaps live in the detail fetch.
                    detail = store.get_run(selected_run_id) or {}

                    if detail.get("decisions"):
                        st.subheader("Decisions")
                        for decision in detail["decisions"]:
                            col1, col2, col3 = st.columns([1.5, 1.5, 3])
                            with col1:
                                st.caption(decision.get("stage", ""))
                            with col2:
                                st.caption(decision.get("verdict", ""))
                            with col3:
                                st.caption(decision.get("reason", ""))

                    if detail.get("gaps"):
                        st.subheader("Gaps")
                        st.dataframe(
                            [
                                {
                                    "Severity": gap.get("severity", ""),
                                    "Kind": gap.get("kind", ""),
                                    "Description": gap.get("description", ""),
                                    "Evidence": gap.get("evidence", ""),
                                }
                                for gap in detail["gaps"]
                            ],
                            use_container_width=True,
                        )

    except ImportError:
        st.info("Store not available. Run a pipeline to see it in the database.")
    except Exception as e:
        st.error(f"Failed to load run history: {str(e)}")
