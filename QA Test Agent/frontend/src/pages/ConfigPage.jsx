import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createRun, startRun } from "../services/api.js";
import ArchitectureDiagram from "../components/ArchitectureDiagram.jsx";
import ParallelExecutionDiagram from "../components/ParallelExecutionDiagram.jsx";
import "../styles/config.css";

const HEALING_OPTIONS = [1, 2, 3, 5, 10];

// Model names per provider, verified against each provider's own docs (see
// backend/services/llm_provider.py for the source and verification notes).
// The Model field stays an editable combo-box (see MODEL_PRESETS usage
// below) so any current/newer model id can still be typed in - providers
// ship new models often, these presets are a helpful starting point, not
// a hard limit.
const MODEL_PRESETS = {
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"],
  openai: ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-5-mini"],
  azure_openai: ["gpt-4.1", "gpt-4o"],
  grok: ["grok-4.6", "grok-4.5", "grok-4.3"],
  groq: ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"],
  sarvam: ["sarvam-105b", "sarvam-105b-conversations"],
};

const PROVIDER_LABELS = {
  gemini: "Gemini (Google)",
  openai: "OpenAI",
  azure_openai: "Azure OpenAI",
  grok: "Grok (xAI)",
  groq: "Groq (fast inference)",
  sarvam: "Sarvam AI",
};

export default function ConfigPage() {
  const navigate = useNavigate();
  const [applicationUrl, setApplicationUrl] = useState("");
  const [authType, setAuthType] = useState("none");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [prdFile, setPrdFile] = useState(null);
  const [maxHealing, setMaxHealing] = useState(3);
  const [parallel, setParallel] = useState(true);
  const [llmProvider, setLlmProvider] = useState("gemini");
  const [llmModel, setLlmModel] = useState(MODEL_PRESETS.gemini[0]);
  const [submitting, setSubmitting] = useState(false);
  const [showArchitecture, setShowArchitecture] = useState(false);
  const [error, setError] = useState("");

  function handleProviderChange(provider) {
    setLlmProvider(provider);
    setLlmModel(MODEL_PRESETS[provider][0]);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("application_url", applicationUrl);
      formData.append("authentication_type", authType);
      if (authType === "username_password") {
        formData.append("username", username);
        formData.append("password", password);
      } else if (authType === "token") {
        formData.append("token", token);
      }
      formData.append("max_healing_attempts", String(maxHealing));
      formData.append("parallel_execution", String(parallel));
      formData.append("llm_provider", llmProvider);
      formData.append("llm_model", llmModel);
      if (prdFile) formData.append("requirements_file", prdFile);

      const created = await createRun(formData);
      await startRun(created.run_id);
      navigate(`/runs/${created.run_id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="config-shell">
      <div className="config-card">
        <h1>Autonomous Test Orchestrator</h1>
        <p className="subtitle">Give it a URL and requirements — it plans, builds, runs, and heals the tests itself.</p>

        <form onSubmit={handleSubmit}>
          <label className="field">
            <span>Application URL</span>
            <input
              type="url"
              required
              placeholder="https://example.com"
              value={applicationUrl}
              onChange={(e) => setApplicationUrl(e.target.value)}
            />
          </label>

          <label className="field">
            <span>Authentication</span>
            <select value={authType} onChange={(e) => setAuthType(e.target.value)}>
              <option value="none">No Authentication</option>
              <option value="username_password">Username / Password</option>
              <option value="token">Token</option>
              <option value="oauth">OAuth</option>
            </select>
          </label>

          {authType === "username_password" && (
            <div className="field-group">
              <label className="field">
                <span>Username</span>
                <input value={username} onChange={(e) => setUsername(e.target.value)} required />
              </label>
              <label className="field">
                <span>Password</span>
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </label>
            </div>
          )}

          {authType === "token" && (
            <label className="field">
              <span>Token</span>
              <input type="password" value={token} onChange={(e) => setToken(e.target.value)} required />
            </label>
          )}

          {authType === "oauth" && (
            <p className="hint">
              OAuth requires a secure app registration configured by an administrator. Contact your admin to set
              this up before starting an OAuth-authenticated run.
            </p>
          )}

          <label className="field">
            <span>PRD / Requirements</span>
            <input
              type="file"
              accept=".pdf,.docx,.txt,.md"
              onChange={(e) => setPrdFile(e.target.files?.[0] ?? null)}
              required
            />
            {prdFile && <span className="uploaded">{prdFile.name} ✓ Uploaded</span>}
          </label>

          <label className="field">
            <span>Maximum Healing Attempts</span>
            <select value={maxHealing} onChange={(e) => setMaxHealing(Number(e.target.value))}>
              {HEALING_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>

          <div className="field-group">
            <label className="field">
              <span>LLM Provider</span>
              <select value={llmProvider} onChange={(e) => handleProviderChange(e.target.value)}>
                {Object.entries(PROVIDER_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Model</span>
              <input
                list="model-presets"
                value={llmModel}
                onChange={(e) => setLlmModel(e.target.value)}
                placeholder="e.g. gemini-2.5-flash"
                required
              />
              <datalist id="model-presets">
                {MODEL_PRESETS[llmProvider].map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </label>
          </div>
          {llmProvider === "azure_openai" && (
            <p className="hint">
              For Azure OpenAI, "Model" must be the deployment name you created in Azure OpenAI Studio, not a
              raw model id.
            </p>
          )}
          {llmProvider === "grok" && (
            <p className="hint">
              Grok is xAI's chatbot (console.x.ai) - not to be confused with "Groq" below, a different company.
            </p>
          )}
          {llmProvider === "groq" && (
            <p className="hint">
              Groq (console.groq.com) is a fast-inference provider - not to be confused with "Grok" (xAI) above.
            </p>
          )}
          {llmProvider === "sarvam" && (
            <p className="hint">
              Sarvam AI needs credits on your account to run - a "402 No credits available" error means the
              integration is working correctly but the account needs billing set up.
            </p>
          )}

          <label className="field toggle-field">
            <span>Parallel Execution</span>
            <button
              type="button"
              className={`toggle ${parallel ? "on" : "off"}`}
              onClick={() => setParallel((p) => !p)}
              aria-pressed={parallel}
            >
              {parallel ? "ON" : "OFF"}
            </button>
          </label>

          {error && <p className="error">{error}</p>}

          <button className="start-btn" type="submit" disabled={submitting}>
            {submitting ? "Starting..." : "Start Autonomous Testing"}
          </button>
        </form>

        <button type="button" className="how-it-works-link" onClick={() => setShowArchitecture((v) => !v)}>
          {showArchitecture ? "Hide" : "See how this works"} {showArchitecture ? "▴" : "▾"}
        </button>
      </div>

      {showArchitecture && (
        <div className="architecture-card">
          <h2>How the agent pipeline works</h2>
          <ArchitectureDiagram />
          <h3 className="architecture-subheading">Parallel Execution</h3>
          <ParallelExecutionDiagram />
        </div>
      )}
    </div>
  );
}
