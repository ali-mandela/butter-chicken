import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getRun,
  getTests,
  getExecution,
  getHealing,
  getArtifacts,
  connectEvents,
  artifactUrl,
  reportUrl,
  resumeRun,
} from "../services/api.js";
import PipelineSidebar from "../components/PipelineSidebar.jsx";
import LiveTrace from "../components/LiveTrace.jsx";
import TabBar from "../components/TabBar.jsx";
import ArchitectureDiagram from "../components/ArchitectureDiagram.jsx";
import ParallelExecutionDiagram from "../components/ParallelExecutionDiagram.jsx";
import "../styles/dashboard.css";

export default function DashboardPage() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [tests, setTests] = useState(null);
  const [execution, setExecution] = useState(null);
  const [healing, setHealing] = useState(null);
  const [artifacts, setArtifacts] = useState(null);
  const [tab, setTab] = useState("Overview");
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState("");
  const wsRef = useRef(null);

  async function handleResume() {
    setResuming(true);
    setResumeError("");
    try {
      await resumeRun(runId);
    } catch (err) {
      setResumeError(err.message);
    } finally {
      setResuming(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const [runData, testsData, executionData, healingData, artifactsData] = await Promise.all([
          getRun(runId),
          getTests(runId),
          getExecution(runId),
          getHealing(runId),
          getArtifacts(runId),
        ]);
        if (!cancelled) {
          setRun(runData);
          setTests(testsData);
          setExecution(executionData);
          setHealing(healingData);
          setArtifacts(artifactsData);
        }
      } catch {
        // run may not exist yet on first mount tick
      }
    }
    refresh();
    const poll = setInterval(refresh, 4000);

    wsRef.current = connectEvents(runId, (event) => {
      setEvents((prev) => [...prev, event]);
    });

    return () => {
      cancelled = true;
      clearInterval(poll);
      wsRef.current?.close();
    };
  }, [runId]);

  if (!run) {
    return (
      <div className="dashboard-shell">
        <p>Loading run {runId}...</p>
      </div>
    );
  }

  const currentActivity = events.length ? events[events.length - 1].message : "Initializing...";

  return (
    <div className="dashboard-shell">
      <header className="dashboard-header">
        <div>
          <Link to="/" className="back-link">
            ← New Run
          </Link>
          <h1>{run.run_id}</h1>
          <p className="app-url">{run.application_url}</p>
          <p className="app-url">
            LLM: {run.llm_provider} / {run.llm_model}
          </p>
        </div>
        <span className={`status-pill ${run.status}`}>{run.status.toUpperCase()}</span>
      </header>

      <div className="dashboard-body">
        <PipelineSidebar currentStage={run.current_stage} status={run.status} />

        <div className="dashboard-main">
          <div className="summary-row">
            <SummaryStat label="Test Cases" value={run.total_test_cases} />
            <SummaryStat label="Scripts Generated" value={run.total_scripts} />
            <SummaryStat label="Plan Revisions" value={run.plan_revision_count} />
            <SummaryStat label="Valid Scripts" value={tests?.script_validation?.valid ?? "-"} />
          </div>

          <div className="current-activity">
            <strong>Current Activity:</strong> {currentActivity}
          </div>

          {run.error && (
            <div className="run-error">
              <div>Run error: {run.error}</div>
              {run.status === "failed" && (
                <div className="resume-row">
                  <button className="resume-btn" onClick={handleResume} disabled={resuming}>
                    {resuming ? "Resuming..." : `↻ Resume from "${run.current_node ?? "the start"}"`}
                  </button>
                  <span className="resume-hint">
                    Picks up right here - everything completed before this step is kept, not redone.
                  </span>
                </div>
              )}
              {resumeError && <div className="resume-error">{resumeError}</div>}
            </div>
          )}

          <TabBar active={tab} onChange={setTab} />

          <div className="tab-content">
            {tab === "Overview" && <LiveTrace events={events.slice(-15)} />}

            {tab === "Test Cases" && (
              <TestCasesTab testCases={tests?.test_cases ?? []} scripts={tests?.generated_scripts ?? []} />
            )}

            {tab === "Execution" && <ExecutionTab results={execution?.execution_results ?? []} />}

            {tab === "Live Trace" && <LiveTrace events={events} />}

            {tab === "Healing" && <HealingTab healing={healing} />}

            {tab === "Artifacts" && <ArtifactsTab runId={runId} artifacts={artifacts?.artifacts ?? {}} />}

            {tab === "Report" && (
              <p className="hint">
                {run.status === "completed" ? (
                  <a href={reportUrl(runId)} target="_blank" rel="noreferrer">
                    Open final report
                  </a>
                ) : (
                  "The report is generated once the run finishes."
                )}
              </p>
            )}

            {tab === "Architecture" && (
              <div className="architecture-tab">
                <ArchitectureDiagram />
                <h4 className="architecture-subheading">Parallel Execution</h4>
                <ParallelExecutionDiagram />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function SummaryStat({ label, value }) {
  return (
    <div className="summary-stat">
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

function TestCasesTab({ testCases, scripts }) {
  if (!testCases.length) return <p className="hint">No test cases generated yet.</p>;
  const scriptByTc = Object.fromEntries(scripts.map((s) => [s.test_case_id, s]));
  return (
    <div className="test-case-list">
      {testCases.map((tc) => (
        <div key={tc.test_case_id} className="test-case-card">
          <div className="tc-header">
            <strong>{tc.test_case_id}</strong> {tc.title}
            {scriptByTc[tc.test_case_id] && (
              <span className={`script-badge ${scriptByTc[tc.test_case_id].valid ? "valid" : "invalid"}`}>
                script {scriptByTc[tc.test_case_id].valid ? "valid" : "invalid"}
              </span>
            )}
          </div>
          <div className="tc-meta">
            Requirement: {tc.requirement_id || "-"} | Priority: {tc.priority}
          </div>
          <ol>
            {tc.steps.map((s) => (
              <li key={s.step_number}>{s.action}</li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

function ExecutionTab({ results }) {
  if (!results.length) {
    return (
      <p className="hint">
        No execution results yet - real Playwright execution runs after Script Validation. No fabricated
        pass/fail results are ever shown here.
      </p>
    );
  }
  return (
    <div className="test-case-list">
      {results.map((r) => (
        <div key={r.test_case_id} className="test-case-card">
          <div className="tc-header">
            <strong>{r.test_case_id}</strong>
            <span className={`script-badge ${r.status.includes("pass") ? "valid" : "invalid"}`}>
              {r.status.replace(/_/g, " ")}
            </span>
          </div>
          <div className="tc-meta">
            Duration: {r.duration_seconds != null ? `${r.duration_seconds}s` : "-"}
          </div>
          {r.errors.length > 0 && (
            <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
              {r.errors[0]}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

function HealingTab({ healing }) {
  if (!healing || (!healing.failures.length && !healing.healing_attempts.length)) {
    return <p className="hint">No failures or healing attempts recorded for this run.</p>;
  }
  return (
    <div>
      {healing.healing_attempts.map((h, i) => (
        <div key={i} className="healing-card">
          <strong>{h.test_case_id}</strong> attempt #{h.attempt_number} - {h.failure_category}
          <p>{h.diagnosis}</p>
          <p>Repair: {h.proposed_change_summary}</p>
          <p>Validated: {h.repair_validated ? "yes" : `no (${h.repair_rejected_reason})`}</p>
        </div>
      ))}
    </div>
  );
}

function ArtifactsTab({ runId, artifacts }) {
  const categories = Object.keys(artifacts);
  if (!categories.length) return <p className="hint">No artifacts yet.</p>;
  return (
    <div className="artifact-tree">
      {categories.map((cat) => (
        <div key={cat} className="artifact-category">
          <h4>{cat}</h4>
          <ul>
            {artifacts[cat].map((file) => (
              <li key={file}>
                <a href={artifactUrl(runId, cat, file)} target="_blank" rel="noreferrer">
                  {file}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
