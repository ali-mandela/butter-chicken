const TABS = [
  "Overview",
  "Test Cases",
  "Execution",
  "Live Trace",
  "Healing",
  "Artifacts",
  "Report",
  "Architecture",
];

export default function TabBar({ active, onChange }) {
  return (
    <div className="tab-bar">
      {TABS.map((tab) => (
        <button key={tab} className={`tab ${active === tab ? "active" : ""}`} onClick={() => onChange(tab)}>
          {tab}
        </button>
      ))}
    </div>
  );
}
