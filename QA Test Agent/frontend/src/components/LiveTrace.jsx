export default function LiveTrace({ events }) {
  return (
    <div className="live-trace">
      {events.length === 0 && <p className="hint">Waiting for the first agent event...</p>}
      {events.map((e, idx) => (
        <div key={idx} className={`trace-line status-${e.status?.toLowerCase() || "info"}`}>
          <span className="trace-time">{new Date(e.timestamp).toLocaleTimeString()}</span>
          <span className="trace-agent">{e.agent}</span>
          <span className={`trace-badge ${badgeClass(e.event)}`}>{e.event.replace(/_/g, " ")}</span>
          {e.test_case_id && <span className="trace-tc">{e.test_case_id}</span>}
          <span className="trace-msg">{e.message}</span>
        </div>
      ))}
    </div>
  );
}

function badgeClass(event) {
  if (event.includes("FAILED")) return "bad";
  if (event.includes("COMPLETED") || event.includes("PASSED")) return "good";
  if (event.includes("NOT_IMPLEMENTED")) return "warn";
  return "";
}
