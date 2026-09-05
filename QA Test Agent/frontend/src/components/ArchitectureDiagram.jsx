import "../styles/architecture.css";

const NODE_W = 158;
const NODE_H = 52;

const NODES = [
  { id: "discovery", label: "Discovery Agent", sub: "real browser crawl", x: 20, y: 30, kind: "browser" },
  { id: "prd", label: "PRD Analyzer", sub: "reads your document", x: 214, y: 30, kind: "llm" },
  { id: "planner", label: "Planner", sub: "decides what to test", x: 408, y: 30, kind: "llm" },
  { id: "validator", label: "Plan Validator", sub: "checks for gaps", x: 602, y: 30, kind: "llm" },

  { id: "testgen", label: "Test Generator", sub: "writes test cases", x: 20, y: 172, kind: "llm" },
  { id: "scriptgen", label: "Script Generator", sub: "writes Playwright code", x: 214, y: 172, kind: "llm" },
  { id: "scriptval", label: "Script Validator", sub: "checks scripts are safe", x: 408, y: 172, kind: "llm" },
  { id: "executor", label: "Executor", sub: "runs tests for real", x: 602, y: 172, kind: "browser" },

  { id: "classifier", label: "Failure Classifier", sub: "why did it fail?", x: 796, y: 172, kind: "llm" },
  { id: "healer", label: "Healing Agent", sub: "proposes a fix", x: 796, y: 288, kind: "llm" },
  { id: "repair", label: "Repair Validator", sub: "checks the fix is safe", x: 602, y: 288, kind: "gate" },

  { id: "reporter", label: "Reporter", sub: "writes final report", x: 408, y: 404, kind: "output" },
];

const KIND_COLORS = {
  browser: { fill: "#e0f2fe", stroke: "#0284c7", text: "#075985" },
  llm: { fill: "#f3e8ff", stroke: "#9333ea", text: "#6b21a8" },
  gate: { fill: "#fef3c7", stroke: "#d97706", text: "#92400e" },
  output: { fill: "#dcfce7", stroke: "#16a34a", text: "#166534" },
};

function nodeById(id) {
  return NODES.find((n) => n.id === id);
}

function center(id) {
  const n = nodeById(id);
  return { x: n.x + NODE_W / 2, y: n.y + NODE_H / 2 };
}

function edgePoint(id, side) {
  const n = nodeById(id);
  switch (side) {
    case "top":
      return { x: n.x + NODE_W / 2, y: n.y };
    case "bottom":
      return { x: n.x + NODE_W / 2, y: n.y + NODE_H };
    case "left":
      return { x: n.x, y: n.y + NODE_H / 2 };
    case "right":
      return { x: n.x + NODE_W, y: n.y + NODE_H / 2 };
    default:
      return center(id);
  }
}

function Arrow({ d, dashed, color = "#94a0c2" }) {
  return (
    <path
      d={d}
      fill="none"
      stroke={color}
      strokeWidth="2"
      strokeDasharray={dashed ? "5 4" : undefined}
      markerEnd="url(#arrowhead)"
    />
  );
}

function EdgeLabel({ x, y, children, color = "#6b7086" }) {
  return (
    <text x={x} y={y} textAnchor="middle" className="edge-label" fill={color}>
      {children}
    </text>
  );
}

export default function ArchitectureDiagram() {
  return (
    <div className="architecture-wrap">
      <p className="architecture-intro">
        This is the actual orchestration graph (built with LangGraph) that runs behind every test run. Blue
        boxes do real browser work. Purple boxes call the LLM. Each box only does one job - the LLM
        reasons, the tools act.
      </p>

      <div className="architecture-scroll">
        <svg viewBox="0 0 985 480" className="architecture-svg" role="img" aria-label="Agent orchestration graph">
          <defs>
            <marker id="arrowhead" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 Z" fill="#94a0c2" />
            </marker>
          </defs>

          {/* main chain row 1 */}
          <Arrow d={`M${edgePoint("discovery", "right").x},${edgePoint("discovery", "right").y} L${edgePoint("prd", "left").x},${edgePoint("prd", "left").y}`} />
          <Arrow d={`M${edgePoint("prd", "right").x},${edgePoint("prd", "right").y} L${edgePoint("planner", "left").x},${edgePoint("planner", "left").y}`} />
          <Arrow d={`M${edgePoint("planner", "right").x},${edgePoint("planner", "right").y} L${edgePoint("validator", "left").x},${edgePoint("validator", "left").y}`} />

          {/* plan revision loop */}
          <Arrow
            dashed
            color="#d97706"
            d={`M${edgePoint("validator", "top").x},${edgePoint("validator", "top").y} C ${edgePoint("validator", "top").x},-18 ${edgePoint("planner", "top").x},-18 ${edgePoint("planner", "top").x},${edgePoint("planner", "top").y}`}
          />
          <EdgeLabel x={(edgePoint("validator", "top").x + edgePoint("planner", "top").x) / 2} y={-6} color="#92400e">
            invalid → revise (max 2 times)
          </EdgeLabel>

          {/* down to row 2 */}
          <Arrow
            d={`M${edgePoint("validator", "bottom").x},${edgePoint("validator", "bottom").y} C ${edgePoint("validator", "bottom").x},130 ${edgePoint("testgen", "top").x},130 ${edgePoint("testgen", "top").x},${edgePoint("testgen", "top").y}`}
          />
          <EdgeLabel x={(edgePoint("validator", "bottom").x + edgePoint("testgen", "top").x) / 2} y={128} color="#166534">
            plan approved
          </EdgeLabel>

          {/* row 2 chain */}
          <Arrow d={`M${edgePoint("testgen", "right").x},${edgePoint("testgen", "right").y} L${edgePoint("scriptgen", "left").x},${edgePoint("scriptgen", "left").y}`} />
          <Arrow d={`M${edgePoint("scriptgen", "right").x},${edgePoint("scriptgen", "right").y} L${edgePoint("scriptval", "left").x},${edgePoint("scriptval", "left").y}`} />
          <Arrow d={`M${edgePoint("scriptval", "right").x},${edgePoint("scriptval", "right").y} L${edgePoint("executor", "left").x},${edgePoint("executor", "left").y}`} />

          {/* executor -> classifier (failures found) */}
          <Arrow d={`M${edgePoint("executor", "right").x},${edgePoint("executor", "right").y} L${edgePoint("classifier", "left").x},${edgePoint("classifier", "left").y}`} />
          <EdgeLabel x={(edgePoint("executor", "right").x + edgePoint("classifier", "left").x) / 2} y={edgePoint("executor", "right").y - 8} color="#991b1b">
            failures found
          </EdgeLabel>

          {/* classifier -> healer */}
          <Arrow d={`M${edgePoint("classifier", "bottom").x},${edgePoint("classifier", "bottom").y} L${edgePoint("healer", "top").x},${edgePoint("healer", "top").y}`} />

          {/* healer -> repair validator */}
          <Arrow d={`M${edgePoint("healer", "left").x},${edgePoint("healer", "left").y} L${edgePoint("repair", "right").x},${edgePoint("repair", "right").y}`} />

          {/* repair validator -> executor (re-execute loop) */}
          <Arrow
            dashed
            color="#d97706"
            d={`M${edgePoint("repair", "top").x},${edgePoint("repair", "top").y} C ${edgePoint("repair", "top").x},240 ${edgePoint("executor", "bottom").x},240 ${edgePoint("executor", "bottom").x},${edgePoint("executor", "bottom").y}`}
          />
          <EdgeLabel x={(edgePoint("repair", "top").x + edgePoint("executor", "bottom").x) / 2} y={238} color="#92400e">
            repair validated → re-execute (max N attempts)
          </EdgeLabel>

          {/* executor -> reporter (no failures) */}
          <Arrow
            d={`M${edgePoint("executor", "bottom").x - 40},${edgePoint("executor", "bottom").y} C ${edgePoint("executor", "bottom").x - 40},350 ${edgePoint("reporter", "right").x + 40},350 ${edgePoint("reporter", "right").x + 40},${edgePoint("reporter", "top").y}`}
          />
          <EdgeLabel x={edgePoint("executor", "bottom").x - 40} y={346} color="#166534">
            no failures
          </EdgeLabel>

          {/* repair validator -> reporter (healing loop ends) */}
          <Arrow d={`M${edgePoint("repair", "bottom").x},${edgePoint("repair", "bottom").y} L${edgePoint("reporter", "top").x},${edgePoint("reporter", "top").y}`} />
          <EdgeLabel x={(edgePoint("repair", "bottom").x + edgePoint("reporter", "top").x) / 2 + 40} y={(edgePoint("repair", "bottom").y + edgePoint("reporter", "top").y) / 2} color="#6b7086">
            healing done
          </EdgeLabel>

          {NODES.map((n) => {
            const c = KIND_COLORS[n.kind];
            return (
              <g key={n.id}>
                <rect
                  x={n.x}
                  y={n.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx="10"
                  fill={c.fill}
                  stroke={c.stroke}
                  strokeWidth="1.5"
                />
                <text x={n.x + NODE_W / 2} y={n.y + 21} textAnchor="middle" className="node-label" fill={c.text}>
                  {n.label}
                </text>
                <text x={n.x + NODE_W / 2} y={n.y + 38} textAnchor="middle" className="node-sub" fill={c.text}>
                  {n.sub}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="architecture-legend">
        <span className="legend-chip" style={{ background: KIND_COLORS.browser.fill, color: KIND_COLORS.browser.text }}>
          Real browser action
        </span>
        <span className="legend-chip" style={{ background: KIND_COLORS.llm.fill, color: KIND_COLORS.llm.text }}>
          LLM reasoning
        </span>
        <span className="legend-chip" style={{ background: KIND_COLORS.gate.fill, color: KIND_COLORS.gate.text }}>
          Safety check / gate
        </span>
        <span className="legend-chip" style={{ background: KIND_COLORS.output.fill, color: KIND_COLORS.output.text }}>
          Final output
        </span>
      </div>
    </div>
  );
}
