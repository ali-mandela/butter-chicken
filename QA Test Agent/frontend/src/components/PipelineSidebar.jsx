const STAGES = [
  { key: "discovery", label: "Discovery", blurb: "Crawling the app in a real browser" },
  { key: "prd_analysis", label: "PRD Analysis", blurb: "Extracting requirements from your document" },
  { key: "planning", label: "Planning", blurb: "Deciding what to test" },
  { key: "plan_validation", label: "Plan Validation", blurb: "Checking the plan for gaps" },
  { key: "test_generation", label: "Test Generation", blurb: "Writing detailed test cases" },
  { key: "script_generation", label: "Script Generation", blurb: "Writing Playwright scripts" },
  { key: "script_validation", label: "Script Validation", blurb: "Checking scripts are safe & valid" },
  { key: "execution", label: "Execution", blurb: "Running tests in a real browser" },
  { key: "healing", label: "Healing", blurb: "Diagnosing & repairing failures" },
  { key: "reporting", label: "Reporting", blurb: "Writing the final report" },
];

function StepIcon({ state }) {
  if (state === "done") {
    return (
      <svg className="step-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="9" fill="var(--step-done)" />
        <path d="M6 10.5l2.5 2.5L14 7.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (state === "failed") {
    return (
      <svg className="step-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="9" fill="var(--step-failed)" />
        <path d="M7 7l6 6M13 7l-6 6" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (state === "active") {
    return (
      <svg className="step-icon spin" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="8" stroke="var(--step-active-track)" strokeWidth="2.5" />
        <path d="M10 2a8 8 0 0 1 8 8" stroke="var(--step-active)" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg className="step-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="10" cy="10" r="8.5" stroke="var(--step-pending)" strokeWidth="1.5" />
    </svg>
  );
}

export default function PipelineSidebar({ currentStage, status }) {
  const currentIndex = STAGES.findIndex((s) => s.key === currentStage);

  return (
    <aside className="pipeline-sidebar">
      <h3 className="sidebar-title">Agent Pipeline</h3>
      <ol className="sidebar-steps">
        {STAGES.map((stage, idx) => {
          let state = "pending";
          if (status === "failed" && idx === currentIndex) {
            state = "failed";
          } else if (idx < currentIndex || (idx === currentIndex && status === "completed")) {
            state = "done";
          } else if (idx === currentIndex && status === "running") {
            state = "active";
          } else if (idx === currentIndex) {
            state = "done";
          }

          return (
            <li key={stage.key} className={`sidebar-step ${state}`}>
              <StepIcon state={state} />
              <div className="sidebar-step-text">
                <span className="sidebar-step-label">{stage.label}</span>
                {state === "active" && <span className="sidebar-step-blurb">{stage.blurb}</span>}
              </div>
            </li>
          );
        })}
      </ol>

      <div className="sidebar-legend">
        <div className="legend-row">
          <StepIcon state="done" />
          <span>Completed</span>
        </div>
        <div className="legend-row">
          <StepIcon state="active" />
          <span>Running now</span>
        </div>
        <div className="legend-row">
          <StepIcon state="pending" />
          <span>Waiting</span>
        </div>
        <div className="legend-row">
          <StepIcon state="failed" />
          <span>Failed</span>
        </div>
      </div>
    </aside>
  );
}
