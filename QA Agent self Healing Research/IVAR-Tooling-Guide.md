# IVAR — Autonomous QA Agent: Complete Tooling Guide

## Architecture Decision: Healenium-Web vs Healenium-Proxy

Healenium offers two approaches, and the choice matters for IVAR's architecture.

**Healenium-Web** integrates directly into your Java test code via the `SelfHealingDriver` wrapper. It is Java-only, runs in-process, and gives you fine-grained control over healing behavior per test. This is the right choice for IVAR because your agent needs to intercept healing events, log confidence scores, and feed them into the IVAR analysis pipeline.

**Healenium-Proxy** is a standalone proxy server that sits between the test runner and Selenium Grid. It is language-agnostic (Java, Python, JS, C#) but operates as a black box — you get healing but less programmatic control over healing decisions. Use this only if your test suite is polyglot.

**Recommendation for IVAR:** Use **Healenium-Web** because IVAR needs to hook into the healing lifecycle (intercept heals, attach confidence scores, route to triage).

---

## Part 1: Healenium-Web Setup (Step-by-Step)

### Prerequisites

- Java 8+ (JDK 17+ recommended)
- Docker Desktop (for backend services)
- Maven or Gradle
- Chrome/Firefox installed

### Step 1 — Start Healenium Backend Services

```bash
# Clone the Healenium infrastructure repo
git clone https://github.com/healenium/healenium.git
cd healenium

# Start backend + PostgreSQL using the Web compose file
docker-compose -f docker-compose-web.yaml up -d
```

This starts:
- `postgres-db` — stores locator fingerprints, healing history, screenshots
- `hlm-backend` — REST API for healing operations (port 7878)
- `selector-imitator` — converts healed locators to readable format (port 8000)

Verify backend is running:
```
http://localhost:7878/healenium/report
```

### Step 2 — Add Maven Dependency

```xml
<dependency>
    <groupId>com.epam.healenium</groupId>
    <artifactId>healenium-web</artifactId>
    <version>3.5.6</version>
</dependency>
```

Or Gradle:
```groovy
implementation 'com.epam.healenium:healenium-web:3.5.6'
```

### Step 3 — Create healenium.properties

Place in `src/test/resources/healenium.properties`:

```properties
recovery-tries = 1
score-cap = .6
heal-enabled = true
hlm.server.url = http://localhost:7878
hlm.imitator.url = http://localhost:8000
```

Key settings:
- `score-cap = .6` — Minimum similarity score (0-1) for a heal to be accepted. Start at 0.6, tune upward for higher precision.
- `recovery-tries = 1` — Number of alternative locators to try. Increase if your UI changes heavily.

### Step 4 — Wrap Your WebDriver

```java
import com.epam.healenium.SelfHealingDriver;

// Create standard driver
WebDriver delegate = new ChromeDriver();

// Wrap with self-healing
SelfHealingDriver driver = SelfHealingDriver.create(delegate);

// Use exactly like a normal WebDriver — no other code changes needed
driver.findElement(By.id("username")).sendKeys("admin");
```

### Step 5 — Use with Explicit Waits (v3.4.4+)

```java
SelfHealingDriver driver = SelfHealingDriver.create(new ChromeDriver());

// Healing triggers AFTER the wait timeout, not immediately
WebElement element = new SelfHealingDriverWait(driver, Duration.ofSeconds(10))
    .until(ExpectedConditions.visibilityOfElementLocated(By.id("dynamic_element")));
```

### Step 6 — Works with PageFactory and @FindBy

```java
public class LoginPage {
    @FindBy(id = "username")
    private WebElement usernameField;

    @FindBy(id = "password")
    private WebElement passwordField;

    @FindBy(css = "button[type='submit']")
    private WebElement loginButton;

    public LoginPage(SelfHealingDriver driver) {
        PageFactory.initElements(driver, this);
    }
}
```

No changes to your POM pattern. Healenium intercepts at the WebDriver level.

### Step 7 — Enable Debug Logging

Create `src/test/resources/simplelogger.properties`:
```properties
org.slf4j.simpleLogger.log.healenium=debug
```

### How Healing Actually Works (Runtime)

1. On every successful `findElement`, Healenium stores the locator + a fingerprint of the matched node and its DOM neighborhood (tag, attributes, ancestors, position) in PostgreSQL.
2. On `NoSuchElementException`, it retrieves the last-known-good fingerprint.
3. Runs a tree-comparing algorithm (LCS-based similarity over the saved subtree vs the current DOM) to score candidate nodes.
4. The best-scoring candidate above `score-cap` threshold becomes the healed locator.
5. The action proceeds, and the healing is recorded with a score and screenshot.
6. View all heals at `http://localhost:7878/healenium/report`.

**Critical limitation:** Healing happens only at runtime. It does NOT modify your test code or POM files. Locators in your source remain unchanged. This is where the IVAR agent layer adds value (see Part 3).

---

## Part 2: Complementary Tools for the IVAR Stack

### Layer 1 — Self-Healing (Locator Repair)

| Tool | Type | What It Does | Why for IVAR |
|------|------|-------------|--------------|
| **Healenium-Web** | OSS, Java | DOM tree-comparison healing with PostgreSQL history | Core healing engine, full API access |
| **Healenium Pro** | Commercial add-on | AI-powered code search + auto-PR creation via GitHub | Closes the loop: healed locator → PR with updated code |
| **CANVAS** | OSS, Python | Semantic intent-based locators using sentence-transformers vectors | Novel layer: survives complete redesigns where DOM healing fails |

**Healenium Pro** deserves special attention for IVAR. It adds AI-based selector detection that searches your GitHub repo for code containing the failed locator, validates matches using an LLM, then creates a branch with a pull request containing the updated locators. You bring your own LLM (OpenAI, Anthropic, etc.) via API key. This maps directly to IVAR's "closed-loop PR workflow" requirement.

### Layer 2 — Visual / Design Drift Detection

| Tool | Type | What It Does | Why for IVAR |
|------|------|-------------|--------------|
| **Applitools Eyes + Figma Plugin** | Commercial | Export Figma frames as visual baselines, compare against live screenshots using Visual AI | The design drift detector: catches spacing, color, font, layout drift that DOM healing never sees |
| **Percy (BrowserStack)** | Commercial | Visual regression testing in CI/CD | Alternative to Applitools, integrates with BrowserStack ecosystem |
| **BackstopJS** | OSS | Headless visual regression with Docker | Budget-friendly pixel-diff option, no AI intelligence |

**Applitools Eyes with the Figma Plugin** is the strongest fit for IVAR. It lets you export Figma frames directly into Eyes to create visual baselines. Developers run their visual tests against these baselines to confirm that what they built matches the approved design. This is how IVAR's "Design Drift Detector" novel layer gets implemented — Figma design becomes the source of truth, not just the DOM.

### Layer 3 — Test Execution Engine

| Tool | Type | What It Does | Why for IVAR |
|------|------|-------------|--------------|
| **Selenium 4 + Healenium** | OSS | Browser automation with self-healing | Your existing stack |
| **Playwright** | OSS | Modern browser automation, built-in accessibility tree | Consider migrating: Playwright's ARIA-first locators are inherently more resilient |
| **BrowserStack Automate** | Commercial | Cloud execution with built-in AI self-heal | One capability flag (`selfHeal: true`) enables healing for Playwright/Selenium |

If your test suite is not yet locked into Selenium, **Playwright** is worth evaluating. Its locator strategy is accessibility-tree-first (`getByRole`, `getByLabel`, `getByText`), which means locators are semantically meaningful out of the box. This aligns with IVAR's semantic intent philosophy and reduces the volume of heals needed in the first place.

### Layer 4 — Figma Integration (Design Intelligence)

| Tool | Type | What It Does | Why for IVAR |
|------|------|-------------|--------------|
| **Figma REST API + Webhooks** | API | Real-time notifications when files change (geometry, styles, components, layers) | IVAR's proactive trigger: detect design changes before tests break |
| **Figma MCP Server** | MCP | LLM-accessible Figma operations via Model Context Protocol | Let the IVAR agent read Figma programmatically in the analysis loop |
| **Storybook + Applitools Addon** | OSS + Commercial | Component-level visual testing where developers build | Catch component drift at the design-system level |

**Figma Webhooks** are essential for the "Figma Change Event Listener" novel layer. Figma supports webhook subscriptions for events including file updates, new comments, and library publications. When a designer publishes a new component version, IVAR can receive a webhook, pull the changed frames via the REST API, and proactively identify which test cases are likely affected — before the next cron run.

### Layer 5 — Reporting, Triage, and CI/CD

| Tool | Type | What It Does | Why for IVAR |
|------|------|-------------|--------------|
| **Healenium Report Dashboard** | Built-in | Visual report of all heals with screenshots and scores | Base-level observability |
| **Allure Report** | OSS | Rich test reporting with history, categories, environment | Attach IVAR metadata (confidence scores, heal source, Figma drift) to test results |
| **GitHub Actions / Jenkins** | CI/CD | Cron-triggered test execution | IVAR's cron job runner |
| **Jira / Linear API** | API | Ticket creation for flagged issues | Auto-create tickets when IVAR detects code-vs-Figma divergence |

---

## Part 3: How IVAR Orchestrates These Tools

### The Agent Loop (per cron run)

```
1. CRON triggers test suite execution
       ↓
2. Selenium + Healenium-Web runs tests
       ↓
3. Healenium self-heals broken locators at runtime
       ↓
4. Test report generated (pass/fail + heal log)
       ↓
5. IVAR Agent receives notification
       ↓
6. Agent classifies each failure/heal:
   ├─ Category A: Selector drift (healed by Healenium)
   │   → Log it, check confidence score
   │   → Score ≥ 0.9: auto-approve, update code via PR
   │   → Score 0.6-0.9: flag for human review
   │   → Score < 0.6: mark as unresolved
   │
   ├─ Category B: Visual drift (Figma ≠ live UI)
   │   → Applitools compares Figma baseline vs screenshot
   │   → If drift detected: is it intentional (code matches new Figma)?
   │   → If unintentional: flag code as divergent, create ticket
   │
   └─ Category C: Feature gap (new AC exists, no test covers it)
       → Agent reads AC from Jira/Confluence
       → Cross-references Figma for UI structure
       → Generates draft Gherkin scenarios
       → Opens PR with new test cases for review
```

### The Proactive Loop (Figma webhook-driven)

```
1. Designer publishes new Figma version
       ↓
2. Figma webhook fires to IVAR endpoint
       ↓
3. Agent pulls changed frames via Figma REST API
       ↓
4. Agent compares changed components against test suite:
   ├─ Which tests reference elements in changed frames?
   ├─ Which locators are likely to break?
   └─ Which AC are affected?
       ↓
5. Agent pre-flags at-risk tests in dashboard
       ↓
6. Next cron run validates predictions
```

---

## Part 4: Recommended Implementation Order

**Phase 1 — Foundation (Weeks 1-3)**
- Set up Healenium-Web with Docker backend
- Wrap existing WebDriver with SelfHealingDriver
- Integrate Healenium report dashboard
- Set up cron job for test execution + notification

**Phase 2 — Design Intelligence (Weeks 4-6)**
- Set up Applitools Eyes + Figma Plugin for visual baselines
- Implement Figma webhook listener for design change events
- Build the diff analyzer that cross-references Figma changes with test locators

**Phase 3 — Agent Intelligence (Weeks 7-10)**
- Build confidence scoring on top of Healenium's score-cap
- Implement triage routing (auto-approve / human review / reject)
- Integrate Healenium Pro for automated GitHub PR creation
- Connect to Jira API for automated ticket creation

**Phase 4 — Novel Layers (Weeks 11-14)**
- Add semantic intent locators (CANVAS or custom sentence-transformer approach)
- Build AC-to-Gherkin test synthesis pipeline
- Implement coverage delta tracker
- Add Figma-aware proactive risk flagging

---

## Key Configuration Reference

### Healenium Backend Docker Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| SPRING_POSTGRES_DB | Database name | healenium |
| SPRING_POSTGRES_SCHEMA | Schema name | healenium |
| SPRING_POSTGRES_USER | DB username | healenium_user |
| SPRING_POSTGRES_PASSWORD | DB password | YDk2nmNs4s9aCP6K |
| KEY_SELECTOR_URL | Tie selector to specific page | false |
| COLLECT_METRICS | Collect healing metrics | true |
| HLM_LOG_LEVEL | Logging level | info |

### Healenium Pro (AI + GitHub)

| Setting | Value |
|---------|-------|
| Repository | owner/repo format |
| Branch | main or master |
| GitHub PAT | Classic PAT with `repo` scope |
| LLM Provider | OpenAI / Anthropic (bring your own key) |

The AI service never receives your GitHub token. LLM calls are isolated from repository credentials.

---

## Critical Warnings

1. **Self-healing can mask real bugs.** A button that silently moved from the checkout flow is a UX regression, not a selector to heal. Always triage heals; treat a high heal rate as a code smell, not a success metric.

2. **Healenium requires a warm-up run.** Healing works only after at least one successful run has stored the locator fingerprint. Brand new locators cannot be healed on their first failure.

3. **Healenium-Web is Java-only.** If your test suite uses Python, JS, or C#, you must use Healenium-Proxy instead (language-agnostic but less programmatic control).

4. **Change default DB credentials in production.** The default `YDk2nmNs4s9aCP6K` password is documented publicly. Replace it in your docker-compose and properties files.

5. **Applitools is commercial.** No permanent free tier for production use. Evaluate during trial, then budget accordingly. BackstopJS is the open-source fallback but lacks Visual AI.
