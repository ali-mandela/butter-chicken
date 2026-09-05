# Autonomous QA Agent with Design Intelligence & Self-Healing Test Automation
## Landscape research: how this is actually being built, and how practitioners actually react

**Date:** 2026-09-03
**Status:** Research only. No implementation decisions made. Greenfield assumption — nothing built yet.
**Method:** Primary-source web research (official docs, source code, arXiv papers, vendor engineering blogs, practitioner forums). Vendor marketing claims are labelled as such. Unverifiable figures are listed in the final section rather than used as fact.

---

## 0. The six findings that should drive every design decision

1. **The whole industry has converged on one architecture: compile the agent run down to a deterministic artifact, and keep the LLM out of the runtime hot path.** This appears independently in commercial products, open-source frameworks, and peer-reviewed work. It is the single strongest signal in the landscape.
2. **Determinism comes from caching, not from better prompting.** Momentic reports cached steps run **52ms slower** than raw Playwright and **>99% of steps execute under 500ms once cached**. The LLM becomes a cache-miss exception handler.
3. **The dominant criticism of self-healing is that it masks real regressions** — and there is a clean, known answer: **heal locator drift, never heal a failing assertion.** A behavioural change is a candidate bug, not a candidate heal.
4. **"Design intelligence" is reliable in exact proportion to how much external specification it checks against.** Anchored to WCAG, design tokens, or a Figma file → deterministic and trustworthy. Asked to originate an aesthetic judgment → collapses (13% valid, see §3.6).
5. **The best-evidenced success mode for AI in QA is triage, not execution.** Elastic's triage agent agrees with human engineers **85%** of the time and *cannot take external action directly*.
6. **The genuinely unbuilt thing is the bridge between the two halves.** Nobody automatically checks a running implementation against its design source as a CI gate. Figma's own AI Design QA agent audits design files, not implementations.

---

## 1. Scope note: what the brief's three phrases actually mean

The problem statement has no canonical published origin — searching the exact phrasing returns only 2026 category marketing. That means the terms are ours to define. Working definitions, derived from what the field actually builds:

| Phrase | What it means in practice |
|---|---|
| **Autonomous QA Agent** | Tests are specified as *intent* (natural language or a recorded journey), not as hand-written selectors. The system plans, executes, and reports without a human authoring each step. |
| **Self-Healing Test Automation** | When the UI changes, the test's element references are repaired automatically rather than breaking the build. |
| **Design Intelligence** | Verifying that a UI is *correct as designed* — visual, layout, design-system, and accessibility correctness — as opposed to merely functional. |

---

## 2. Part One — Self-healing and agentic execution

### 2.1 The seven recurring architectural patterns

**Pattern 1 — Multi-attribute weighted similarity scoring (no LLM).**
The oldest and most widely deployed mechanism. On locator failure, compare the live DOM against a stored fingerprint (text, position, class, tag, role, structural path), score candidates, take the best above a threshold.
Used by: Healenium, Applitools Execution Cloud, Testim, mabl. Formalized academically as Similo/VON Similo and COLOR.
This is the **only category with a fully public, reproducible algorithm.** Healenium uses a modified **Longest Common Subsequence** with per-attribute weighting plus a "heuristic node distance" pass, stores every successfully-resolved element's DOM subtree in PostgreSQL, and gates heals behind a configurable `score-cap` (default 0.5).

**Pattern 2 — LLM as re-ranker over a heuristic shortlist, not as the search itself.**
A cheap deterministic heuristic narrows to a handful of candidates; the LLM only judges among finalists. **This consistently beats both pure-heuristic and pure-LLM in every study that measured it:**
- VON Similo LLM: GPT-4 re-ranking cut failed localizations from **70 → 39 of 804** test cases (44% reduction).
- Explanation-consistency repair (arXiv 2312.05778): Edit-Distance alone scored **30.9%** (43/139); Edit-Distance + ChatGPT re-ranking scored **87.8%** (122/139). The *weakest* standalone heuristic became the strongest once paired with LLM judgment.
- Katalon Studio 11 ships exactly this: a classic fallback chain first, LLM only if that also fails.

**Pattern 3 — Set-of-Marks / bounding-box vision grounding.**
Label interactable elements with IDs, draw them onto a screenshot, let a vision model reference elements by label rather than coordinates. Rooted in Microsoft's Set-of-Mark paper (arXiv 2310.11441). Used by Skyvern; DOM-side analogues are Playwright MCP's accessibility-tree `ref` IDs and Agent-E's `mmid` identifiers.

**Pattern 4 — Pure vision, no DOM.**
A minority position: ignore the DOM entirely, localize from pixels. Midscene.js by explicit design choice; Tricentis Tosca Vision AI because it targets Citrix/VMware/legacy apps that expose no object model at all.

**Pattern 5 — Compile to a deterministic script; keep the LLM out of the hot path. ⭐**
The most important pattern in the landscape. An LLM runs *once* to produce a plan/selector/script; that artifact is cached or committed; subsequent runs replay it with zero inference; the LLM is re-invoked only as an exception handler on failure.

| Implementation | How it expresses the pattern |
|---|---|
| **Octomind** | Tagline is literally *"AI doesn't belong in test runtime."* Healed selectors are committed to the repo ("Source-Level Healing", "Zero Silent Commits" — nothing lands until a human runs `octomind pull`). Execution is plain Playwright. |
| **Playwright Agents** (Planner/Generator/Healer, v1.56, Oct 2025) | Healer patches the checked-in `.spec.ts`. CI runs are pure Playwright. The LLM's product *is* the human-readable test file. |
| **Momentic V3** | Planner drafts the flow once; resolved steps are cached; self-heals only when a cached step misses. The vendor calls this *"the technically honest version of self-healing — a cache-and-revalidate loop."* |
| **Stagehand** | `observe()` once → persist an `Action` object → `act(actionObject)` replays with **zero inference**. Cache key deliberately excludes model config so it survives model swaps. |
| **Midscene.js** | Two-tier YAML cache (plan cache + XPath cache) with explicit priority: explicit selector > cache > AI. |
| **Meticulous.ai** | The most radical version: **no LLM anywhere.** A recorded real session (DOM events + 100% of network responses) *is* the deterministic artifact, replayed on a deterministic-scheduling Chromium fork. |
| **QA Wolf / Checkly** | LLM is diagnostic-only. Runtime is always plain generated code. |
| **Agentic Compilation** (arXiv 2604.09718) | The rigorous academic statement. Formalizes the "Rerun Crisis" as O(M×N) cost scaling for loop agents; one-shot compilation to a JSON blueprint run by a model-free runtime. **80–94% zero-shot blueprint success; $0.002–$0.092 per compilation vs ~$15–150 for continuous-loop agents** — up to ~1500× cheaper. |

**The architectural fork.** Skyvern and Browser Use deliberately *do not* follow this pattern — they stay live per-step agentic loops. That is correct for their goal: unfamiliar sites where no prior successful run exists to compile from. The split is clean:
> **Known app, want cheap/fast/stable → compile to script. Unknown app, want maximum generality → stay agentic every step.**
> QA regression testing is squarely the first case.

**Pattern 6 — Human-approval gate before a heal becomes permanent.**
Katalon requires clicking "Approve" in Self-Healing Insights; Octomind enforces Zero Silent Commits; QA Wolf routes fixes through human review; Autify makes ML model promotion manual *specifically* so tests behave identically across runs. Presented consistently as the antidote to silent test-intent drift.

**Pattern 7 — Natural language as the locator ("intent over implementation").**
testRigor and Virtuoso argue that phrasing tests as intent makes them structurally heal-tolerant, since no implementation detail was ever encoded. This is a design philosophy, not an algorithm, and it's the **weakest-verified** claim category.

### 2.2 Element resolution — the three grounding families

| Family | Mechanism | Trade-off |
|---|---|---|
| **Accessibility tree** | Semantic tree screen readers use; stable across CSS/DOM refactors | The convergent default. Fails on custom components with poor a11y implementation |
| **Set-of-Marks overlay** | Numeric IDs + boxes drawn on a screenshot | Bridges pixels to discrete actions; still depends on DOM/AXTree quality |
| **Pure pixel coordinates** | Vision model emits coordinates directly | Works where no object model exists; weakest precision |

The convergent production answer is **accessibility-tree-first with vision fallback** (Momentic states this explicitly; the agent literature independently confirms the taxonomy).

### 2.3 Benchmark reality

| Benchmark | Result |
|---|---|
| WebArena (812 tasks) | Original GPT-4 baseline **14.41%** vs **78.24% human**. Top leaderboard entry Feb 2026: **74.3%** (WebTactix/DeepSeek v3.2) |
| WebVoyager (643 tasks, 15 real sites) | Original multimodal **59.1%**; Agent-E **73.2%**; Browser Use self-reports **89.1%** on a modified 586-task harness (methodology change acknowledged by its own authors) |
| Mind2Web | Best cross-task **55.1%** element accuracy / 52.0% step success; GPT-4 cross-website **35.8%** |
| RAG-grounded Selenium generation (arXiv 2601.06034) | **90%** execution success (18/20) with retrieval grounding vs **30%** without |

**The honest caveat.** Benchmarks grade happy paths in frozen environments. The six production failure modes nobody benchmarks: **selector drift, screenshot ambiguity, login-state loss, modal interruptions, rate-limit cliffs, and irreversibility.** WebArena's shop never ships a new CSS class; Mind2Web never fires a cookie banner mid-flow.

> ⚠️ The widely-circulated claim *"a browser agent scores 78% on WebArena but books 22% of carts in production"* is an **unsourced rhetorical framing device** with no methodology or citation, and it appears to misread WebArena's *human* baseline as an agent score. Do not cite it.

---

## 3. Part Two — Design intelligence, decomposed

The term is vague and partly marketing. It decomposes into six distinct capabilities with radically different maturity and reliability.

### 3.1 Visual regression / perceptual diffing — **mature**
Two families. **Naive pixel diff**: per-pixel colour distance in YIQ space (approximates human luminance perception better than RGB) — `pixelmatch` (used by Playwright), `resemble.js` (BackstopJS), `odiff` (Argos). Anti-aliasing is handled by a dedicated edge-adjacency detector; this is the price of admission for any pixel differ to be usable at all.

**ML-assisted diff**: Applitools segments the image into UI elements and compares structurally, which is what enables tunable **match levels** — Exact / Strict / Content / Layout / Ignore Colors / Dynamic / None. Applitools' *Root Cause Analysis* additionally surfaces the DOM/CSS delta behind a visual diff, turning "here's a red box" into "here's the CSS rule that changed" (it works by snapshotting DOM/CSS alongside the image — it is DOM diffing, not image understanding).

Percy takes a different architecture: capture a **DOM snapshot** client-side, ship it to the server, re-render at each breakpoint there — which is why it can test arbitrary responsive widths cheaply and freeze animations server-side. Chromatic's TurboSnap maps changed files to affected stories via a build dependency graph and skips the rest.

Notably, **Argos deliberately does not use ML to adjudicate diffs** — a direct architectural counterpoint to Applitools.

**Failure modes:** cannot detect a bug that doesn't move a pixel; cross-browser/OS/GPU font-hinting noise; **baseline rot** — a baseline asserts *sameness*, never *correctness*.

**The real bottleneck is approval fatigue.** Every tool needs a human to approve a new baseline when a change is intentional. High diff volume → rubber-stamping → the safety net silently dies. Percy's own blog documents this as a first-class problem. This, not diff accuracy, is why teams turn visual testing off.

### 3.2 Design-spec conformance (Figma vs production) — **emerging, and the biggest real gap**
- **Figma Code Connect** maps Figma components to real source components — infrastructure for fidelity, not a verifier.
- **Figma MCP server** feeds design context to coding agents at *generation* time — not post-hoc verification.
- **Figma's own AI Design QA Agent** (open beta) reviews **design files against the design library, tokens and variables**. It audits Figma artifacts. It does **not** compare implementation to design.
- **Visual Copilot / Anima / Locofy** are generators, not verifiers. Independent comparisons converge on: output quality is gated by how disciplined the source Figma file is, and all still need senior-dev cleanup.

**No mature product does automated Figma-vs-live-production conformance as a CI gate.** Once a human or agent edits generated code, design drift begins immediately and nothing re-checks it. Continuous visual diffing doesn't cover this — it diffs code against *itself over time*, not against the design source.

### 3.3 Design-token conformance — **mature and fully deterministic**
The W3C **Design Tokens Community Group format reached first stable version 2025.10**, backed by Figma, Adobe, Google, Microsoft, Shopify, Salesforce. Tokens require `$value` with `$type` (color, dimension, fontFamily, duration, cubicBezier, plus composites: border, shadow, typography, gradient); aliases use `{group.token}` syntax; `$type` inherits down groups. Style Dictionary compiles tokens to platform artifacts. Stylelint/ESLint rules (e.g. Kong's `use-proper-token`, `ds-lint`) flag hardcoded hex/spacing/typography where a token reference is expected.

**Limit:** this is *source-level* static analysis. A component that internally uses tokens correctly but is composed wrongly at the call site passes. And **no tool detects "off-catalog components" in a rendered production page** — only import-level linting. That gap appears genuinely unfilled.

### 3.4 Baseline-free heuristic visual QA — **geometry mature, ML research-only**
**Geometric:** compute bounding boxes from the render tree, apply IoU and containment logic to detect overlap and text truncation. Deterministic and baseline-free by construction.

**Learned models — the real academic line:**
| Work | Method | Reported |
|---|---|---|
| **OwlEyes** (arXiv 2009.01417) | CNN classifier + Grad-CAM localization; 4,470 labelled GUI screenshots | **85% precision, 84% recall**; 90% localization accuracy. Found **57 unknown real bugs, 26 confirmed/fixed** |
| **Nighthawk** (arXiv 2205.13945) | Reframed as object detection with true bounding boxes | **0.84 AP / 0.84 AR detection**, but only **0.59 AP / 0.60 AR localization**. Found **151 unknown issues, 75 confirmed/fixed** |

**Detection is systematically easier than localization, which is easier than root-cause explanation** — a pattern that recurs across the entire landscape (it's also why Applitools needs a *separate* DOM-diff step to explain *why*).

Both trained on Android screenshots; generalization to responsive web/dark mode is not established. Neither shipped commercially.

### 3.5 Accessibility — **the most operationally solid capability in the entire brief**
The only place where "design correctness" is grounded in an actual W3C specification rather than a baseline or a vibe.

Deque's own figures, and the two numbers are **not contradictory** — they measure different things:
- **By criterion count:** axe-core fully automates **29.5% of WCAG 2.2 success criteria**, partly automates 10.3%, leaves **60.2% manual**.
- **By real issue volume** (13,000+ pages, ~300,000 issues): **57.38% of accessibility issues encountered in the wild are automatable** — higher, because a few automatable criteria (contrast, focus order, parsing) account for a disproportionate share of real defects.

~100% automatable: 2.4.3 Focus Order, 2.4.7 Focus Visible, 1.4.11 Non-text Contrast, 1.3.2 Meaningful Sequence. 83–92%: 4.1.1 Parsing, 3.1.1 Language of Page, 1.4.3 Contrast (Minimum).
Structurally **not** automatable: 2.4.4 Link Purpose, 2.4.6 Headings and Labels, most of 3.x — these require judging whether text is *meaningful*, which is a human call.

WCAG 2.2's new **2.5.8 Target Size (24×24px)** is geometry-computable in principle, but no mainstream tool ships a rule because the exception logic ("equivalent control", "essential presentation") produces too many false positives.

### 3.6 VLM design critique — **research-only; naive use is mostly noise**
The most sobering evidence in the research, and it is primary-sourced.

**UICrit** (arXiv 2407.08850) — 983 mobile UIs, 3,059 critiques from 7 professional designers:
- **Zero-shot VLM critique produced 5,927 comments, of which only 776 — 13.1% — were validated as accurate.** Naive "ask a vision model if this UI looks good" is ~87% noise.
- **Few-shot prompting improved quality 55% relative** (0.48 vs 0.31, p=5e-4).
- Human-written critiques still scored **0.75** — the best LLM condition remained far below.
- Inter-rater agreement among human experts was only *fair* (Fleiss' κ 0.29–0.31), setting a real subjectivity ceiling for any judge.

Corroborating, independently:
- **UIClip** (arXiv 2404.12500, UIST 2024) — a purpose-trained CLIP-style UI-quality scorer achieved the highest agreement with 12 designers' rankings among tested baselines. Purpose-built beats general VLM, at the cost of a training pipeline.
- *"VLM Judges Can Rank but Cannot Score"* — VLM judges handle **relative ranking** but not **absolute scoring**; uncertainty intervals cover ~40% of the score range.
- Design-evaluation prompts show unusually high prompt sensitivity; same-verdict consistency falls from >95% at temperature 0 to ~70% at temperature 1.

**Practical implication: never ask "score this UI 1–10". Ask "which of these two is better", or don't ask at all.**

### 3.7 Capability summary

| Capability | Needs a baseline? | Deterministic? | Catches what a functional test cannot |
|---|---|---|---|
| Visual regression | **Yes** | Mostly (ML diff adds non-determinism) | Unintended CSS/layout regressions with no functional signal |
| Figma-vs-code conformance | Yes (the design file) | No | Divergence from *design intent*, not just from a prior build |
| Design-token linting | **No** | **Yes** | Off-system styling that renders fine but violates the system |
| Heuristic layout QA | **No** | Geometry yes; CNN no | Layout bugs on first-ever render, no baseline needed |
| Accessibility (WCAG subset) | **No** | **Yes** | Spec-grounded failures that look fine and pass every functional test |
| VLM design critique | No | **No** | Aesthetic judgment — but currently unreliable |

---

## 4. Part Three — How practitioners actually react

### 4.1 The criticisms, ranked by how often they appear

**1. Self-healing silently masks real regressions.** The dominant theme across every source type. From Ministry of Testing practitioners:
> *"if a test is 'healed' how do i know this hasn't changed the intent of my test… if i have to go and check then i might as well have fixed the test myself"* — Bill Matthews

> *"snake oil that may result in false positives — but even worse — false negatives without any transparency to see what is truly going on"* — Mark Cole

> *"high risk that the self-healing tool fixes something that is not broken (for example in a negative test), leading to invalid tests"* — Claudia Mueller

The canonical cautionary tale, recurring near-verbatim across independent write-ups: a "Pay now" button disappears from a real regression; healing latches onto a visually similar wrong button; the test passes; the bug ships.

**2. Maintenance burden doesn't vanish — it shifts to debugging the AI's decisions.** A consultant reporting across ~10 client engagements: *"Some of the Agentic testing providers claim to develop around 1000 test cases monthly, but after a few months, they deliver around 500 largely flaky tests."*

**3. The AI layer introduces its own non-determinism.** Small prompt or page changes cause disproportionate result swings. And on AI writing both code and its tests: *"You ask the agent to write code, then ask it to write tests for that code, and surprise, they all pass because the tests are literally just 'does the code do what the code does.'"*

**4. Cost doesn't hold at scale.** Real spread: **~$10 per 100 agent tasks** on a cheap model vs **~$100 per run** for the same workload on a frontier model.

**5. Visual regression false positives → approval fatigue** (see §3.1).

### 4.2 The defenses — and the one concrete design that answers criticism #1

- **Heal selector drift; refuse to heal failing assertions.** The single concretely-praised design found in the entire practitioner research. A behavioural change indicates a potential bug, so only locator drift is heal-eligible. This directly dissolves the masking critique.
- **Cap and log every heal.** *"Pair self-healing with behavior and content assertions, so a passing test still means the feature actually works"*; require every heal to be logged, reviewed, and capped per run.
- **A vendor in this exact market concedes the core critique.** Octomind — who sell AI test generation — publicly argue **"AI doesn't belong in test runtime."** They also candidly state their own team *"cannot honestly say these tools have boosted their productivity in a meaningful way (say, 20% or more)."*
- **The root cause may be upstream.** Lisa Crispin: *"the most common cause of flakiness is poor design of the test code. Not enough abstraction, too declarative, not using good design patterns."* Self-healing may be compensating for architectural debt rather than adding a capability.

### 4.3 Where AI in QA demonstrably works

- **Triage — the best-quantified success story found.** Elastic Security Labs' bug-bounty triage agent agrees with human security engineers **85% of the time**, validated against **764 known-outcome reports**, at **$0.50–$1.15 per report** for analysis and **$0.80–$4.90** for the ~30% needing reproduction. ~70% are rejected during cheap analysis. Critically: *"the agent cannot take any external action directly."* **AI narrows the search space; a human makes the call.**
- **Test-idea generation, properly steered:** *"it'll spontaneously come up with test paths that I'd normally only get to after a month."*
- **Investigating flaky CI:** documented cases of an agent bisecting to find a race condition, and of taking a 40%-pass-rate pipeline to a 35-point improvement overnight — as an *investigator*, never as the thing deciding pass/fail.
- **Selector-level healing specifically**, when logged and bounded.

### 4.4 The structural critique (testing vs checking)

Bach and Bolton draw a hard line: **checking** is mechanical pass/fail evaluation a machine can do; **testing** is a sapient process of exploration, questioning and modelling. On their account "test automation" is a misnomer — what is automated is always checking.

Applied to AI agents: *"AI is not testing. AI can not do professional testing. AI can do exploratory analysis."* The reasoning is that LLMs cannot explain the reasoning behind a judgment the way a tester must when asked "why do you believe this is a bug?" Bach adds a distinct **accountability** argument that isn't a capability claim: *"the operator of an AI agent always bears responsibility for the behavior of that agent"* — even a perfect AI tester wouldn't resolve the organizational problem that someone must own the judgment.

This is a minority-but-credentialed position (context-driven testing school), not mainstream industry consensus. Represented fairly: a small influential faction argues the category is *named wrong* and no capability improvement fixes that; a much larger mainstream argues about *degree*.

---

## 5. Part Four — What the evidence implies for a system built now

Each item traces to a finding above.

**Architecture**
1. **Compile, don't loop.** Plan once with the LLM, persist a deterministic artifact, replay with zero inference, re-invoke the LLM only on cache miss. (Pattern 5; ~1500× cost delta; 52ms cached overhead.)
2. **Accessibility-tree-first, vision fallback.** (§2.2 — the convergent answer.)
3. **LLM as re-ranker over a heuristic shortlist**, never as the primary search. (Pattern 2 — 30.9% → 87.8%.)
4. **Version and persist heals as reviewable artifacts**, ideally as committed code. (Pattern 6.)

**Safety — the part that differentiates a serious system**
5. **Never heal a failing assertion.** Separate locator resolution from behavioural validation; make assertions structurally un-healable. (§4.2 — answers the #1 criticism.)
6. **Cap heals per run and log every one** with old attempt, new selector, confidence, and reasoning.
7. **Require a healed selector to match on stable semantic attributes** (role, test-id, accessible name) — not visual similarity alone. This is specifically the "Pay now button" failure mode.
8. **Distinguish "the app broke" from "I broke"** — treat AI-layer instability as a first-class, separately-reported failure category.
9. **Build an explicit human-accountability seam**, not just a dashboard someone *could* look at. (Bach's argument.)
10. **Report cost per run transparently.**

**Design intelligence — sequence by reliability, not by impressiveness**
11. **Start with the spec-anchored, deterministic layers:** accessibility (axe-core), design-token conformance, and geometric layout heuristics (overlap, truncation, off-grid). These need no baseline, are deterministic, and catch real bugs that pass every functional test.
12. **Add visual regression second, and invest disproportionately in noise suppression** — ignore regions, animation freezing, layout-level match modes. Approval fatigue, not diff accuracy, is what kills adoption.
13. **Use VLMs for ranking and for explaining a diff a deterministic checker already flagged — never as the detector, and never for absolute scores.** (13% validity zero-shot.)
14. **Don't let AI grade its own generated tests.** Prefer an independent source of truth.

**The open opportunity**
15. The unfilled gaps are (a) **implementation-vs-design conformance as a CI gate**, and (b) **off-catalog component detection in a rendered page**. Both are spec-anchored — which §3 predicts is exactly where automation is reliable — and neither exists as a mature product.

---

## 6. Primary sources

**Self-healing / agentic execution**
- Applitools Execution Cloud self-healing docs — attribute matching, bidirectional selector persistence
- Healenium (`github.com/healenium/healenium-web`) — heal config surface, score-cap
- Stagehand docs (`docs.stagehand.dev/v4/basics/act`) — a11y/DOM/set-of-marks hybrid, cache-and-replay, selfHeal
- Playwright `test-agents` docs — Planner/Generator/Healer; Healer patches source files
- Playwright `test-snapshots` docs — threshold/maxDiffPixels semantics, OS/GPU rendering variance warning
- Momentic docs + `momentic.ai/blog/how-agentic-testing-works` — a11y-first + vision fallback, 52ms/500ms/10–15min figures
- Meticulous `how-it-works` — deterministic Chromium replay, full network mocking
- Katalon self-healing docs — ordered fallback chain, approval gate
- Autify engineering blog — MLUI model, manual production promotion for determinism
- Skyvern blog — screenshot/vision-LLM approach
- arXiv 2310.02046 (VON Similo LLM) — 70→39 of 804
- arXiv 2301.03863 (VON Similo) — 94.7% vs 83.8%, 1,163 pairs
- arXiv 2312.05778 — 87.8% vs 30.9% on 139 broken statements
- arXiv 2604.09718 (Agentic Compilation) — compile-once pattern, cost tables
- arXiv 2601.06034 — 90% vs 30% with RAG grounding
- arXiv 2307.13854 (WebArena) — 14.41% vs 78.24%
- arXiv 2310.11441 (Set-of-Mark) — the grounding technique
- `leaderboard.steel.dev/leaderboards/webarena` — 74.3% top entry, Feb 2026
- `browser-use.com/posts/sota-technical-report` — 89.1%, modified harness
- ROBULA+ (Leotta et al., JSEP 2016) — ~90% fragility reduction vs absolute XPath

**Design intelligence**
- Applitools match-levels docs + Root Cause Analysis
- Argos `docs/diff-algorithm` — odiff multi-pass, explicit non-use of ML
- Chromatic TurboSnap docs
- `designtokens.org/tr/drafts/format/` + W3C stable-version announcement (2025.10)
- Kong design-tokens Stylelint plugin
- arXiv 2009.01417 (OwlEyes) — 85%/84%, 57/26
- arXiv 2205.13945 (Nighthawk) — 0.84/0.84, 0.59 AP, 151/75
- Deque Automated Accessibility Coverage Report — 57.38% issue-based
- Deque "What to Expect from WCAG 2.2" — 29.5%/10.3%/60.2%
- arXiv 2407.08850 (UICrit) — 13.1% zero-shot validity, 0.48 vs 0.31 vs 0.75, κ 0.29–0.31
- arXiv 2404.12500 (UIClip)
- `figma.com/solutions/ai-design-qa-agent/` — open beta; design-file scope confirmed

**Practitioner reception**
- `club.ministryoftesting.com` day-20 self-healing thread — Matthews, Cole, Mueller, Crispin quotes
- `tjmaher.com` 2026 James Bach workshop notes — testing vs checking, accountability
- HN Algolia comment searches: self-healing tests / flaky tests AI / visual regression / AI test generation
- `dev.to/rmarinsky` — multi-client consultant experience
- `elastic.co/security-labs/blog/ai-vulnerability-triage-bug-bounty-hackerone` — 85%, 764 reports, $0.50–$4.90
- Octomind — "AI doesn't belong in test runtime"; productivity candour
- `browserstack.com/guide/how-to-reduce-false-positives-in-visual-testing`
- `browser-use.com/posts/ai-browser-agent-benchmark` — $10 vs ~$100 per 100 tasks

---

## 7. Explicitly NOT verified — do not cite as fact

- **"78% on WebArena → 22% in production"** — unsourced framing device, no methodology; likely misreads the human baseline. **Discard.**
- **"68% of self-healing setups fail"** — the author self-discloses it is not peer-reviewed; it is one person's informal audit of 34 client setups.
- **"57% of testers abandoned self-healing within 6 months" (TestGuild poll) and "61% reported unexpected test behavior" (Applitools 2024)** — cited only secondhand; neither could be located.
- **"31% more time debugging AI decisions" across "437 enterprise implementations"** — unsourced vendor SEO content with invented-sounding precision.
- **"$900K–$1M annual all-in cost for a 10-engineer team"** — single-origin vendor advocacy number.
- Vendor accuracy claims with no methodology: Functionize **99.9% self-healing accuracy**; Virtuoso **95% first-attempt success**; Octomind **83% maintenance reduction**; Applitools **99% false-positive reduction**; Builder.io **"pixel-perfect"** and **50–80% time savings**.
- **TestQuality's "agentic QA architecture"** piece names Plan-Act-Verify and semantic healing but supplies **no mechanism** for either; its 94% compilation / 68% activation figures are unattributed.
- **Virtuoso QA overall** — every reachable source was marketing; no technical documentation found. Treat as substantially less reliable than the rest.
- mabl's own auto-heal help page returned 403; Healenium's `how-it-works.md` 404'd (algorithm corroborated across three secondary sources); octomind.dev failed DNS on direct fetch (quotes reconstructed from consistent search snippets).
- Nighthawk's Faster-RCNN architecture — consistent across secondary sources, not stated in the arXiv abstract.
- No evidence OwlEyes or Nighthawk ever graduated from research prototype to maintained product.
- No general-purpose tool found that detects off-catalog components in a rendered production UI — may genuinely not exist rather than having been missed.
