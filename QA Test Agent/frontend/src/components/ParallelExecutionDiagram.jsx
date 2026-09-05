export default function ParallelExecutionDiagram() {
  return (
    <div className="parallel-diagram">
      <p className="architecture-intro">
        When Parallel Execution is ON, the Executor Agent runs independent test cases at the same time, each
        in its own isolated browser context. A test case that depends on another (shares state, like "view
        the item added in a previous test") always waits its turn - dependencies are never run out of order.
      </p>

      <div className="parallel-lanes">
        <div className="parallel-lane">
          <div className="lane-badge running">⚡ running</div>
          <div className="lane-box">TC-001 · Login</div>
        </div>
        <div className="parallel-lane">
          <div className="lane-badge running">⚡ running</div>
          <div className="lane-box">TC-003 · View Product</div>
        </div>
        <div className="parallel-lane">
          <div className="lane-badge running">⚡ running</div>
          <div className="lane-box">TC-005 · Sort Products</div>
        </div>
      </div>

      <div className="parallel-arrow-down">↓ finishes, then</div>

      <div className="parallel-lanes">
        <div className="parallel-lane wide">
          <div className="lane-badge waiting">⏳ waits for TC-001</div>
          <div className="lane-box dependent">TC-002 · Add to Cart (depends_on: TC-001)</div>
        </div>
      </div>
    </div>
  );
}
