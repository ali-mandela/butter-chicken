const BASE = "/api/test-runs";

export async function createRun(formData) {
  const res = await fetch(BASE, { method: "POST", body: formData });
  if (!res.ok) throw new Error((await res.json()).detail || "Failed to create run");
  return res.json();
}

export async function startRun(runId) {
  const res = await fetch(`${BASE}/${runId}/start`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json()).detail || "Failed to start run");
  return res.json();
}

export async function resumeRun(runId) {
  const res = await fetch(`${BASE}/${runId}/resume`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json()).detail || "Failed to resume run");
  return res.json();
}

export async function getRun(runId) {
  const res = await fetch(`${BASE}/${runId}`);
  if (!res.ok) throw new Error("Failed to fetch run");
  return res.json();
}

export async function getTests(runId) {
  const res = await fetch(`${BASE}/${runId}/tests`);
  if (!res.ok) throw new Error("Failed to fetch tests");
  return res.json();
}

export async function getExecution(runId) {
  const res = await fetch(`${BASE}/${runId}/execution`);
  if (!res.ok) throw new Error("Failed to fetch execution results");
  return res.json();
}

export async function getHealing(runId) {
  const res = await fetch(`${BASE}/${runId}/healing`);
  if (!res.ok) throw new Error("Failed to fetch healing info");
  return res.json();
}

export async function getArtifacts(runId) {
  const res = await fetch(`${BASE}/${runId}/artifacts`);
  if (!res.ok) throw new Error("Failed to fetch artifacts");
  return res.json();
}

export function artifactUrl(runId, category, filename) {
  return `${BASE}/${runId}/artifacts/${category}/${encodeURIComponent(filename)}`;
}

export function reportUrl(runId) {
  return `${BASE}/${runId}/report`;
}

export function connectEvents(runId, onEvent) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${window.location.host}${BASE}/${runId}/events`);
  ws.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data));
    } catch {
      // ignore malformed frames
    }
  };
  return ws;
}
