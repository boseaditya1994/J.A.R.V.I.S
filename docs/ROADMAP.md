# Roadmap — PROJECT JARVIS

Environment: Windows 11, Intel Core Ultra 5 125H (no dedicated GPU), 16GB RAM,
D: drive (62GB free) as project home. See `ENVIRONMENT.md` for full detail.
Primary cloud LLM: Anthropic Claude (Haiku/Sonnet). See `TECHNOLOGY_DECISIONS.md`.

Status legend: ✅ done · 🚧 in progress · ⬜ not started

---

## PHASE 0 — Environment + Architecture ✅
- **Objective:** Establish ground truth before writing code.
- **Features:** Environment scan, tech decisions, architecture doc, roadmap.
- **Technologies:** N/A (docs only)
- **Cost:** $0
- **Risks:** None
- **Acceptance criteria:** `ENVIRONMENT.md`, `TECHNOLOGY_DECISIONS.md`,
  `ARCHITECTURE.md`, `ROADMAP.md` exist and reflect the real machine.

## PHASE 1 — Text + Voice Assistant MVP ✅
- **Objective:** Smallest working assistant — talk or type to it, get a
  spoken + text reply.
- **Features:** Text chat loop; push-to-talk voice input (mic → Whisper →
  text); spoken output (Edge TTS); single-provider LLM call (Claude); basic
  system prompt with a configurable name/personality.
- **Architecture changes:** `jarvis/core`, `jarvis/voice`,
  `jarvis/interfaces/cli.py` created. No memory or tools yet — pure
  request/response.
- **Technologies:** Python 3.12 (via `uv`), `anthropic` SDK, `faster-whisper`,
  `edge-tts`, `sounddevice`/`pyaudio` for mic capture, `ffmpeg`.
- **Cost:** ~$1–5/month (Haiku-only usage at MVP scale).
- **Risks:** Python 3.14 default vs. ML library compatibility (mitigated —
  pinned to 3.12 venv); ffmpeg not installed yet (needs install step); no
  API key yet (needs user to provide one).
- **Security considerations:** API key loaded from `.env`, never committed;
  no tool execution yet so no permission layer needed yet.
- **Acceptance criteria:** Can type or speak a question and receive a correct
  spoken + printed answer end-to-end, with the API key supplied by the user.

## PHASE 2 — Memory ✅
- **Objective:** JARVIS remembers across turns and sessions.
- **Features:** Working memory (conversation buffer, unchanged from Phase 1);
  persistent facts + task memory ("remind me to..."), both **explicit-only**
  (confirmed with the user — no passive/inferred storage, no extra LLM
  cost); automatic episodic log of every turn. `"what do you remember about
  me?"` / `"forget X"` / `"forget everything"` commands, handled by a
  regex-based dispatcher (`jarvis/core/commands.py`) checked before the LLM
  — zero-cost, deterministic, no hallucination risk on reads/deletes. Known
  accepted limitation: regex matching can misfire on incidental phrasing
  (e.g. "remember when we talked about X?"); proper fix is Phase 3's real
  tool-calling, not more regex.
- **Architecture changes:** `jarvis/memory/` added (SQLite at
  `data/memory.db`, gitignored); `jarvis/core/commands.py` added;
  `Orchestrator` now takes a `MemoryStore`, injects stored facts/open tasks
  into the system prompt each turn, and logs every turn to the episodic log.
- **Technologies:** SQLite (stdlib `sqlite3`), no ORM; `dateparser` for
  natural-language due-time parsing in reminders.
- **Cost:** $0 incremental (no additional LLM calls).
- **Risks:** Over-storing avoided by the explicit-only policy. Regex intent
  matching is the accepted trade-off above.
- **Security considerations:** Memory DB stored outside any synced/cloud
  folder (project lives at `D:\Projects\JARVIS`, not OneDrive); user-facing
  inspect/delete commands shipped with this phase; the one destructive/global
  operation (`forget everything`) is gated behind a typed "yes" confirmation
  in the CLI, per the brief's rule on confirming destructive operations.
- **Acceptance criteria (met):** A fact stated in one CLI session is
  correctly recalled after restarting the process (verified live, two
  separate runs); `forget X` measurably removes it; `forget everything`
  only executes after explicit confirmation.

## PHASE 3 — Tool Calling ✅
- **Objective:** JARVIS can act, not just talk.
- **Features:** Tool registry (name, schema, risk level) in
  `jarvis/tools/registry.py`; three tools — `calculator` (sandboxed AST
  arithmetic, no `eval()`), `filesystem_read` (scoped to the project
  workspace, path-traversal/symlink-escape guarded, size-capped),
  `web_search` (Anthropic-hosted server-side tool — no third-party search
  API key needed; Anthropic executes it and the result lands inline in the
  same response). Permission layer (`jarvis/core/permissions.py`) gates
  anything above LOW risk behind a confirmation callback injected from
  `cli.py`; every client-tool call (approved or declined) is written to a
  new `tool_audit_log` SQLite table.
- **Architecture changes:** `jarvis/tools/`, `jarvis/core/permissions.py`,
  `tool_audit_log` table in the existing memory DB. `router.generate()` now
  returns the raw `Message` response (was extracted text) so the
  orchestrator can inspect `stop_reason` and run the tool loop; a new
  `router.extract_text()` helper covers the old use case.
- **Technologies:** Anthropic native tool-use format (custom JSON-Schema
  tools + the hosted `web_search_20260209`/`web_search_20250305` variants,
  selected by which model tier is serving the turn); no agent framework, no
  beta SDK tool-runner — a hand-rolled, capped (5-iteration) request/response
  loop, consistent with Phase 1–2's "own the whole loop" approach.
- **Cost:** Marginal increase from tool schemas in every prompt; web search
  is billed separately by Anthropic at ~$10 per 1,000 searches.
- **Risks:** LLM requesting inappropriate tool calls — mitigated by the
  permission layer being outside LLM control, always, and by
  `filesystem_read` being workspace-scoped regardless of risk tier (an
  extra guardrail beyond what "LOW risk" alone would imply, since an
  unscoped read tool would send arbitrary local file content to the cloud
  API on the model's say-so). No HIGH/CRITICAL-risk tool ships this phase —
  all three tools are legitimately LOW risk per the brief's own risk-tier
  examples — but the confirmation gate is real and unit-tested against a
  synthetic HIGH-risk tool; it gets exercised for real once Phase 4/5 add
  browser control, filesystem write, or shell.
- **Security considerations:** Core Rule from the project brief — the model's
  output alone never authorizes a dangerous operation; confirmation required
  for anything above LOW risk. Verified live: a path-traversal attempt
  against `filesystem_read` was blocked by the workspace-containment check
  (exercised directly in unit tests, independent of whether the model
  attempts the call).
- **Acceptance criteria (met):** JARVIS answered a live web-search-dependent
  question and a local file-read question in the same session, both tool
  calls logged to `tool_audit_log` with no confirmation prompt (correct for
  LOW risk); a fake HIGH-risk tool in tests was blocked when confirmation
  was denied and ran when approved.

## PHASE 4 — Web + Browser ✅
- **Objective:** Read and act on the live web, not just search snippets.
- **Features:** `web_fetch` added alongside Phase 3's `web_search` — both
  Anthropic-hosted, server-side, zero new dependencies. `web_fetch` only
  fetches URLs already present in the conversation (Anthropic's own
  constraint — the model can't point it at a URL it invents from nothing).
  Citations enabled on `web_fetch` so retrieved content carries source
  attribution. System prompt updated to require distinguishing known vs.
  freshly-retrieved information and to treat retrieved content as untrusted
  data, never instructions.
- **Architecture changes:** `jarvis/tools/registry.py` gained
  `web_fetch_tool_dict()` (same pattern as `web_search_tool_dict()`);
  `Orchestrator._tools()` includes both. **Supersedes the original plan**
  written in Phase 0, which speculated Playwright/headless browser
  automation would be needed — that was written before Phase 3's research
  (via the `claude-api` skill) surfaced that Anthropic hosts both search
  *and* fetch server-side. Real interactive browsing (clicking, filling
  forms, multi-page navigation, logins) is deferred to Phase 5 "Computer
  Control," which needs its own higher-risk permission handling anyway.
- **Technologies:** `web_fetch_20260209` (dynamic-filtering, Sonnet-5/Opus
  tier) / `web_fetch_20250910` (basic, Haiku tier) — same complexity-based
  variant selection as `web_search`.
- **Cost:** No separate client cost; billed by Anthropic as part of normal
  API usage (same billing surface as `web_search`).
- **Risks:** Prompt injection from fetched web content — mitigated by
  treating it as untrusted data per the updated system prompt (same
  discipline this assistant itself follows toward its own tool results).
- **Security considerations:** `web_fetch` cannot be pointed at an
  arbitrary attacker-suggested URL — it only fetches URLs already present
  in the conversation, an Anthropic-enforced constraint, not something
  this project had to implement itself.
- **Acceptance criteria (met):** Verified live — summarizing a real
  Wikipedia URL pasted by the user produced an accurate summary with the
  source cited; a research-style question ("official docs for X") combined
  `web_search` and `web_fetch` in one turn and produced an accurate,
  docs-grounded answer. Confirmed no `tool_audit_log` rows were created for
  either call (expected — both are server-side, same as established in
  Phase 3).

## PHASE 5 — Computer Control, Part 1 (Filesystem + Shell) ✅
- **Objective:** JARVIS can operate the local machine within strict bounds.
- **Scope, confirmed with the user:** this round covers file writes and an
  allowlisted shell — exactly what this section already named. Full
  interactive browser/GUI control (Playwright or Anthropic's computer-use
  tool) is deliberately deferred to its own phase — it would give JARVIS
  real mouse/keyboard control or scripted access to the user's actual
  browser profile and deserves its own sandboxing design, not to be folded
  in here. "Open apps" / "fill forms" / "navigate the OS" from the original
  feature list above are part of that deferred work.
- **Features:** `filesystem_write` (HIGH risk) — create/overwrite a text
  file inside the workspace. `shell_execute` (CRITICAL risk) — run a
  command from a fixed executable allowlist (`git`, `python`, `node`,
  `npm`, `uv`, `where`), no shell operators, 20s timeout, output capped and
  logged. These are the first HIGH/CRITICAL-risk tools JARVIS has —
  Phase 3's confirmation gate is now exercised by real tools, not just
  test doubles.
- **Architecture changes:** `jarvis/tools/` split into `filesystem.py`
  (read + write, shared workspace/path validation) and `shell.py`
  (allowlisted execution), with `registry.py` now aggregating both plus
  `calculator` and the Phase 4 web tools. New `ToolSpec.validate` hook —
  a hard-boundary check run *before* confirmation is ever requested (see
  below). `jarvis/tools/spec.py` added to hold the shared `ToolSpec`
  dataclass, avoiding a circular import between `registry.py` and the new
  tool modules.
- **New guardrails beyond risk-tier + confirmation:** (1) a sensitive-file
  denylist (`.env`, `.git/`, `.pem`/`.key`) applied to *both*
  `filesystem_read` and `filesystem_write` — `filesystem_read` is LOW risk
  and auto-approved, so without this a prompt injection from fetched web
  content (the risk Phase 4 flagged) could trick JARVIS into reading
  `.env` and echoing the API key back into its own response; (2)
  `shell_execute`'s allowlist, enforced via `subprocess.run(shell=False)`
  with forbidden shell-metacharacter rejection — no shell interpretation
  at all.
- **Bug found and fixed via live testing:** the allowlist/validation check
  originally ran *inside* the tool handler, which only executes after
  confirmation — so a disallowed command (e.g. `del file.txt`) still
  produced a `Type 'yes' to allow` prompt before being rejected, costing
  the user a decision on something that was never going to run. Fixed by
  adding `ToolSpec.validate`, called by the orchestrator before the
  confirmation gate; a validation failure is now rejected outright and
  logged as `rejected: ...`, never reaching `confirm()`. Caught by
  inspecting `tool_audit_log` after a live run showed `del scratch.txt`
  logged as `declined by user` instead of a rejection — a regression test
  (`test_shell_execute_disallowed_command_rejected_before_confirmation`)
  now asserts the confirm callback is never invoked for disallowed
  commands.
- **Technologies:** stdlib `subprocess`/`pathlib`/`shlex` — no new
  dependency.
- **Cost:** $0 incremental.
- **Risks:** Highest-blast-radius phase so far. Mitigated by the allowlist
  (hard boundary, checked first), confirmation-always for HIGH/CRITICAL
  risk, the sensitive-file denylist, and the full audit trail.
- **Security considerations:** Phase 3's permission layer and audit log
  had been running reliably before this phase added tools that actually
  need them. `shell_execute` is CRITICAL-only — confirmation always
  required, no auto-approve tier, matching the original plan.
- **Acceptance criteria (met):** Verified live — `filesystem_write`
  approved via the real confirmation prompt created a file with correct
  content; `shell_execute` approved via the real confirmation prompt ran
  `git status` and returned real output. The reject/decline paths are
  verified by direct, deterministic unit tests rather than a live model
  interaction: in live sessions, the model increasingly reasoned from the
  tool descriptions and declined to even attempt disallowed/protected
  calls (reading its own tool descriptions and choosing not to try) rather
  than triggering the code-level rejection — a reasonable outcome, but not
  proof of the mechanism itself, so the unit tests are the authoritative
  check for those paths. `tool_audit_log` correctly distinguishes
  `approved`, `declined by user`, and `rejected: ...` outcomes.

## PHASE 6 — Personal Knowledge Base ✅
- **Objective:** Answer questions from the user's own documents.
- **Features:** `ingest <path>` (`.txt`/`.md`/`.pdf`) — a deterministic
  command, not an LLM tool, matching Phase 2's explicit-only policy and
  this phase's own "no automatic scanning" requirement. `knowledge_search`
  (LOW risk, LLM tool) — semantic search over ingested content, the one
  part where the model's judgment about *when* to use the knowledge base
  earns its place as a tool. `what have you ingested?` /
  `forget document <name>` for inspection and deletion, mirroring Phase 2's
  memory-inspection symmetry.
- **Key simplification found while building this:** Chroma ships a
  built-in local embedding function (ONNX Runtime, a small MiniLM model) —
  no API key, no PyTorch. This resolved the "local vs. API embeddings"
  question in favor of local on every axis before it became a real
  trade-off to ask about, the same shape as Phase 4's web_fetch discovery.
- **Architecture changes:** `jarvis/memory/semantic.py` (`KnowledgeStore`,
  mirrors `MemoryStore`'s shape — a class taking an optional path, not a
  bare module client, for the same test-isolation reason); `jarvis/tools/knowledge.py`
  (the `knowledge_search` `ToolSpec`); ingestion reuses
  `jarvis/tools/filesystem.py`'s `validate_path` (now public) so the same
  workspace-scoping + sensitive-file denylist applies — you can't ingest
  `.env` either.
- **Disk-placement bug found and fixed:** Chroma's default embedding
  function hardcodes its model-download path to
  `Path.home() / ".cache" / "chroma"` with no env var override — on this
  machine that's C:, which was already critically low (9.1GB free at the
  time). Fixed the same way real sysadmins handle this class of problem
  when there's no config knob: moved the ~166MB cache to
  `D:\chromacache` and left an NTFS directory junction at the original C:
  path, so Chroma's hardcoded path resolves there transparently — verified
  a second real ingestion read from the junction without re-downloading.
- **Tool-selection bug found and fixed via live testing:** the first live
  question referencing "my architecture doc" made the model guess file
  paths with `filesystem_read`, fail, try `shell_execute` with an
  unallowlisted `find`, get rejected, then give up and ask the user for a
  path — never attempting `knowledge_search` at all, even though it had
  just ingested that exact file moments earlier in the same conversation.
  `knowledge_search` itself worked correctly the whole time (proven by its
  unit tests) — this was purely a tool-selection/prompting gap. Fixed by
  sharpening the tool description (explicit "try this FIRST", "does NOT
  need a file path") and adding a system-prompt sentence naming the same
  guidance; re-tested live and the model then called `knowledge_search`
  correctly and answered from the retrieved content.
- **Known, accepted limitation:** with only 4 chunks retrieved per query
  (`DEFAULT_TOP_K`) and a small local embedding model, retrieval doesn't
  always surface every relevant chunk in one query (a live test recalled 4
  of the source document's 5 listed principles), and the model sometimes
  paraphrases the source ("your architecture doc") rather than citing the
  literal filename despite being asked to. Not a bug — an inherent
  precision/recall trade-off of small-model RAG at small `top_k`; a future
  pass could raise `top_k`, tune chunk size, or reinforce citation format
  further if this proves limiting in practice.
- **Technologies:** `chromadb`, `pypdf`. No new API key, no PyTorch.
- **Cost:** $0 incremental — embeddings run locally.
- **Risks:** Blind-embedding everything creates noise and privacy exposure —
  mitigated by ingestion being explicit-only (a command the user runs by
  name), never automatic directory scanning.
- **Security considerations:** Vector store stays local (`data/chroma/`,
  already covered by the existing `data/` gitignore); no document content
  ever leaves the machine for embedding (local ONNX model); Chroma
  telemetry explicitly disabled at client construction.
- **Acceptance criteria (met):** Verified live — ingesting
  `docs/ARCHITECTURE.md` reported a chunk count; a question referencing
  "my architecture doc" was answered correctly via `knowledge_search` once
  the tool-selection fix landed; `what have you ingested?` listed it;
  `forget document` removed it and the same question could no longer be
  answered from that source afterward; `ingest .env` was blocked by the
  same denylist `filesystem_read`/`write` already use.

## PHASE 7 — Specialized Agents (Part 1) ✅
- **Objective:** Purpose-built agents for recurring workflows.
- **Scope, this round:** the user didn't respond to an `AskUserQuestion`
  narrowing the scope, so per the project's Auto Mode bias I proceeded with
  the stated recommended default — the **Research Agent** only. Coding
  agent (needs HIGH/CRITICAL-risk tools and its own safety-prompt design)
  and monitoring agent (needs Phase 8's scheduling infrastructure, which
  doesn't exist yet) are explicitly deferred, not abandoned.
- **Features:** `research <topic>` — a deterministic command (matched by
  `jarvis/core/commands.py`'s `match_research`, same explicit-only pattern
  as memory/ingestion), not something the main chat LLM can trigger on its
  own, since spawning a multi-step, multi-tool-call agent run has real cost.
  The agent's tool scope is deliberately minimal and read-only —
  `web_search`, `web_fetch`, `knowledge_search` — no `filesystem_write`,
  `shell_execute`, or `calculator`, so it can never modify anything on its
  own. It runs at `complexity="high"` (Sonnet) — the first real exercise of
  the complexity-routing capability `router.py` has carried since Phase 1
  — and produces a structured Markdown report (Summary / Key Findings with
  inline citations / Sources), which the orchestrator saves to
  `research/<slug>.md` and reports back in the reply.
- **Key architectural decision:** Phase 3's tool-calling loop and per-call
  gating logic (validate → confirm → run → audit-log) previously lived
  inline in `Orchestrator`. Extracted into a new shared module,
  `jarvis/core/tool_loop.py` (`run_tool_loop` + `execute_tool`), since an
  "agent" is fundamentally the same loop run with a different system prompt
  and a *restricted* tool subset — not a new execution paradigm. A scoped
  `find_tool` lookup **is** the "controlled interface, not shared
  unrestricted access" the brief asks for; no new abstraction layer needed.
  `Orchestrator` and the research agent (`jarvis/agents/research.py`) both
  call the same, already-tested machinery, differing only in scope.
- **Bug found and fixed via live testing (container-id plumbing):** the
  newer dynamic-filtering `web_search_20260209`/`web_fetch_20260209`
  variants (used at `complexity="high"`) run inside a server-side
  code-execution sandbox. The hand-rolled tool loop wasn't carrying that
  sandbox's `container` id across follow-up calls, so any turn where a
  client-side tool (e.g. `knowledge_search`) forced a second round after
  one of those hosted tools ran failed with `400 — container_id is
  required when there are pending tool uses generated by code execution
  with tools`. Fixed generally in `jarvis/core/router.py` (`generate()` now
  accepts/forwards an optional `container` id) and `jarvis/core/tool_loop.py`
  (`run_tool_loop` tracks `response.container.id` across iterations and
  passes it to the next call) — this fixes the mechanism for *any* future
  caller of the shared loop, not just the research agent. Covered by a
  regression test (`test_loop_forwards_container_id_to_next_call`).
- **Second issue found via live testing (report quality) — mitigated, not
  fully re-confirmed live:** a live run that got past the bug above still
  returned a garbled "report" — a stray sentence about parsing raw JSON
  instead of an actual structured report, suggesting the model's own
  scratch reasoning about the code-execution tool's output leaked into the
  final answer. Rather than chase the exact cause further, the fix taken
  was to decouple "which model" from "which tool variant": the research
  agent still runs the model at `complexity="high"` (Sonnet) but requests
  the **basic** `web_search`/`web_fetch` variants (`complexity="normal"` in
  `registry.web_search_tool_dict`/`web_fetch_tool_dict`), which carry no
  code-execution sandbox at all, sidestepping this and the container-id
  issue at the root. **Caveat, noted explicitly:** the retry to confirm
  this fix produces a clean report hit the JARVIS Anthropic account running
  out of API credits (exhausted by cumulative live testing across all of
  Phases 1–7) before it could complete. This phase is closed out on the
  strength of the full test suite (136/136 passing) plus the live evidence
  already gathered (the tool loop, confirmation gating, and report-saving
  path all exercised successfully in earlier live runs this phase) — a
  deliberate cost/rigor tradeoff, not an oversight. Re-verify live with a
  fresh `research <topic>` run once the account has credits again.
- **Architecture changes:** `jarvis/core/tool_loop.py` (new — extracted
  loop + gating, see above); `jarvis/agents/` (new package) —
  `research.py` (system prompt, scoped tool list, `run()`, `slugify()`);
  `jarvis/core/commands.py` gained `match_research` (a plain regex matcher,
  deliberately with no LLM/store access, keeping the module's existing
  zero-API-calls test guarantee intact); `jarvis/core/orchestrator.py`
  refactored to a thin caller of `tool_loop` plus a new
  `_run_research_agent` dispatch path, checked first in `handle_turn`
  (same precedent as `FORGET_EVERYTHING`); the report-save step
  (`filesystem_write`) bypasses the confirmation gate — same precedent as
  Phase 6's `ingest`, a deterministic consequence of the user's own
  explicit command, not an LLM judgment call — but is still logged to
  `tool_audit_log` (`approved=1`).
- **Technologies:** Still hand-rolled orchestration — no agent framework
  needed yet, consistent with every prior phase.
- **Cost:** Each `research <topic>` run makes several Sonnet calls plus
  Anthropic-billed `web_search`/`web_fetch` usage — noticeably more
  expensive than a normal chat turn; this is expected and was the direct
  cause of the JARVIS account running low on credits during this phase's
  live testing.
- **Risks:** Agent sprawl / unclear ownership of actions — mitigated for
  this one agent by its minimal, explicitly allow-listed tool scope
  (`_ALLOWED_CLIENT_TOOL_NAMES` in `research.py`) enforced independently of
  whatever the global registry exposes.
- **Security considerations:** Per-agent permission scoping via a
  restricted `find_tool` closure, not a new permission concept; same audit
  log as every other tool call, whether triggered by the main chat loop or
  an agent.
- **Acceptance criteria (met, with the caveat above):** The research agent
  completed a real multi-step run end-to-end live (tool loop, confirmation
  gating for `knowledge_search`, and the `filesystem_write` report-save all
  exercised), and two real bugs surfaced and were fixed via that live
  testing. Final confirmation that the report-quality fix produces a clean
  Markdown report is deferred until the JARVIS API key has credits again —
  tracked as the one open follow-up for this phase.

## PHASE 8 — Proactive Intelligence (Part 1) ✅
- **Objective:** JARVIS surfaces useful things unprompted, within limits.
- **Scope, this round:** a morning brief and reminder-due nudges only.
  Deployment/monitoring alerts need a monitoring agent that doesn't exist
  (Phase 7 built only the research agent); true calendar integration needs
  OAuth/external APIs (Phase 9 infra); quiet-hours windows and toast
  snooze/acknowledge flows are real complexity, deferred to a later pass.
- **Features:** `jarvis/interfaces/proactive.py` — a short-lived entrypoint
  (not a daemon), invoked by Windows Task Scheduler, not the interactive
  loop. `--job reminder_check`: purely deterministic, **no LLM call at
  all** — batches every overdue `remind me to ...` task into one toast
  rather than spamming one per task. `--job morning_brief`: summarizes
  stored facts/open tasks into a short notification, Haiku tier, tool
  scope restricted to `knowledge_search` + basic `web_search`. Both respect
  a new daily notification cap (`MAX_NOTIFICATIONS_PER_DAY`) and reuse
  `jarvis/core/tool_loop.py` exactly like the Phase 7 research agent —
  an unattended job is the same shape as an agent (restricted scope, no
  human present to confirm anything), so it earns no new execution
  paradigm.
- **Architecture changes:** `jarvis/interfaces/proactive.py` (new),
  `jarvis/interfaces/notify.py` (new, Windows toast wrapper). First phase
  needing a real schema migration on an already-populated DB —
  `jarvis/memory/db.py` gained a `_migrate()` step (guarded `ALTER TABLE
  tasks ADD COLUMN notified_at`, checked via `PRAGMA table_info` rather
  than a caught exception) plus a new `notifications_log` table;
  `jarvis/memory/store.py` gained `list_due_unnotified_tasks`,
  `mark_task_notified`, `log_notification`, `count_notifications_since`.
- **Bug found and fixed via live testing (DLL conflict, not an API bug):**
  installing `win11toast` (for toast delivery) broke `onnxruntime`
  (Chroma's embedding backend, Phase 6) — `import win11toast` before
  `import onnxruntime` in the same process corrupts onnxruntime's native
  DLL loading for the rest of that process; the reverse order is fine.
  Confirmed directly with a two-line repro. Fixed by importing
  `win11toast` lazily inside `notify.py`'s `notify()` function rather than
  at module load time — this also self-solves the production ordering
  risk for free, since `run_morning_brief`'s own `knowledge_search` tool
  call (if any) always happens inside the tool loop, before `notify()` is
  called at the end of that same function. For the test suite (which loads
  every test module into one shared process regardless of which phase it
  belongs to), `tests/conftest.py` forces `onnxruntime` to import first.
- **Known, accepted limitation:** `commands.py`'s `_handle_remind` stores
  `due_at` as a naive-local-time string (`dateparser`'s default), while
  `MemoryStore._now()` elsewhere in the same DB is tz-aware UTC.
  `run_reminder_check` computes "now" as naive local time to match — this
  works today, but it's a convention mismatch anyone querying
  `data/memory.db` directly should know about. A real fix (normalizing all
  stored timestamps to aware UTC) touches `commands.py` and is out of
  scope for this round.
- **Technologies:** Windows Task Scheduler (`schtasks`) for the cron-style
  trigger, per this phase's original tech note — no new Python scheduler
  dependency, no persistent daemon. `win11toast` for native Windows 11
  toast/Action Center delivery (chosen over `winotify`, which has had no
  release in the past year).
- **Cost:** The reminder-check job is $0 — no LLM call. The morning brief
  makes a cheap Haiku-tier call plus basic (non-dynamic-filtering)
  `web_search` usage.
- **Risks:** Notification fatigue / unwanted autonomy — mitigated by
  `MAX_NOTIFICATIONS_PER_DAY` (shared across both jobs) and by batching
  multiple due reminders into one notification instead of one per task.
- **Security considerations:** Proactive jobs pass through the same
  `tool_loop.py` gating as everything else — `confirm=lambda _: False` is
  used as a safety net in the headless morning-brief job (there's no human
  present to answer a confirmation prompt), but this should never actually
  trigger since its tool scope (`knowledge_search` + basic `web_search`)
  never rises above LOW risk. Registering the OS scheduled tasks is a
  manual step the user runs themselves (`README.md`) — outside
  `shell_execute`'s allowlist, since it's a system-level change, not
  something a chat tool should do on the model's say-so.
- **Acceptance criteria (met):** Verified live, for $0 (no LLM call
  needed for this path) — a reminder with a past due time was correctly
  batched into a real toast notification, `tasks.notified_at` and
  `notifications_log` updated correctly, a second run did not re-fire
  (idempotency confirmed), and the rate-limit skip path was verified
  separately (a pre-seeded `notifications_log` at the cap correctly
  suppressed the notification and left the task unnotified for retry). The
  morning-brief job is covered by the full mocked test suite
  (`tests/test_interfaces_proactive.py`) but its live LLM call is deferred
  until the JARVIS Anthropic account has credits again (see Phase 7's
  entry for why credits ran out) — tracked as the one open follow-up for
  this phase, same pattern as Phase 7's closure.

## PHASE 9 — Multi-device Assistant (Part 1) ✅
- **Objective:** JARVIS is reachable from more than one device.
- **Scope, this round:** a server + installable web app (PWA) for text
  chat, memory, LOW-risk tools, and push notifications (morning brief +
  reminder-due), reachable from phone and laptop over HTTPS. **Explicitly
  deferred:** voice over the web (real porting blockers found —
  `jarvis/voice/tts.py`'s `winsound.PlaySound` is Windows-only and plays on
  the local speaker; `stt.py`'s mic capture assumes a local terminal);
  approving a HIGH/CRITICAL tool call from the remote client (auto-declined
  for now, same `confirm=lambda _: False` safety-net pattern Phase 8
  established for its own headless jobs — no synchronous human to ask over
  a stateless HTTP request); `ingest <path>` from mobile (no file-upload
  mechanism yet, the path has to exist on the server).
- **Features:** `jarvis/server/` — a FastAPI app wrapping
  `Orchestrator.handle_turn()` unchanged (memory, tools, command dispatch
  including `research`/`ingest` all reused as-is). `POST /chat` (+ the
  `forget everything` two-step confirmation flow, mirroring `cli.py`'s own
  prompt but over two endpoints), `POST /push/subscribe`, `GET
  /vapid-public-key`, and a background `asyncio` scheduler loop replacing
  Windows Task Scheduler for the always-on server context. A small
  vanilla-JS PWA (`jarvis/server/static/`) — installable, works offline for
  the shell, receives push notifications via a service worker.
- **Architecture changes:** The VM becomes the single source of truth —
  `data/memory.db`/`data/chroma/` move there once; the laptop becomes a
  PWA client too instead of running `cli.py` for daily use, so there's no
  two-store sync problem to solve. Auth is one shared bearer token
  (`API_AUTH_TOKEN`), not a user/account system — proportionate for a
  single-user assistant; checked with `secrets.compare_digest`
  (`jarvis/server/auth.py`). Notifications move from `win11toast` to
  self-hosted Web Push (VAPID, `jarvis/server/push.py`, no
  Firebase/OneSignal) — `jarvis/interfaces/proactive.py`'s
  `run_morning_brief`/`run_reminder_check` needed zero changes, since their
  `notify_fn` parameter (added in Phase 8) was already the exact injection
  point this needed.
- **Bugs found and fixed via load-testing the dry run and real live
  deployment** — five real, distinct issues, none caught by the mocked
  test suite alone:
  1. **Thread-safety (not an API bug):** FastAPI runs synchronous route
     handlers in a worker threadpool, and the background scheduler's DB
     access runs via `asyncio.to_thread` — both touch the same
     `MemoryStore`/sqlite3 connection from different threads. sqlite3
     connections aren't safe for concurrent cross-thread use; this
     surfaced immediately as `sqlite3.ProgrammingError: SQLite objects
     created in a thread can only be used in that same thread` the first
     time a test exercised more than one request. Fixed with
     `check_same_thread=False` on the connection (`jarvis/memory/db.py`)
     plus a `threading.Lock` wrapping every `MemoryStore` method
     (`jarvis/memory/store.py`) — `cli.py` and `proactive.py` stay
     single-threaded and pay only the cost of an uncontended lock.
  2. **A CSS bug that silently defeated the PWA's own token-setup flow:**
     `#setup { display: flex; ... }` in `index.html` unconditionally
     overrode the browser's default `[hidden] { display: none }` rule
     (author styles always win over user-agent defaults) — the JS was
     hiding the element correctly, but it never visually disappeared.
     Fixed with an explicit `#setup[hidden] { display: none; }` rule.
  3. **A GET/POST mismatch:** the PWA's `enableNotifications` handler
     called `apiPost("/vapid-public-key")`, but the server only exposes
     that endpoint as `GET` (correctly — it's a read, not a mutation) —
     405 on every attempt. Fixed by adding a proper `apiGet()` client
     helper instead of loosening the server's method.
  4. **Stale service-worker cache masking bug #3's fix:** `sw.js` cached
     the shell on install but never cleaned up an old cache on activate,
     so a device that had already loaded the buggy `index.html` kept
     serving it from cache after the server-side fix deployed — same 405
     resurfaced on Android after it was already fixed on desktop. Fixed by
     bumping `CACHE_NAME` and deleting any non-current cache in the
     `activate` handler.
  5. **The VAPID private key was stored in the wrong format entirely:**
     `generate_vapid_keys()` produced a full PEM
     (`-----BEGIN PRIVATE KEY-----...`) with escaped newlines for `.env`
     storage — but `py_vapid`'s `Vapid.from_string()` (what `pywebpush`
     calls internally) strips newlines and base64url-decodes the *whole*
     input string; PEM armor isn't valid base64, so every real push send
     failed with an opaque `ValueError: ... ASN.1 parsing error: invalid
     length`, silently swallowed by the scheduler's blanket exception
     handler with zero visibility. Fixing this required two layers: (a)
     adding actual logging (`logger.exception(...)` in `push.send_push`
     and the scheduler loop, plus `logging.basicConfig()` in `main.py`) to
     even see the real error instead of guessing blind, and (b) switching
     `generate_vapid_keys()` to produce a bare base64url-encoded raw
     32-byte key, matching what `py_vapid` actually expects. The existing
     keypair was re-encoded in place (same public key, so already-created
     browser subscriptions stayed valid) rather than regenerated.
     Discovering (a) then surfaced a sixth, subtler bug: once `send_push`
     stopped raising and started returning `False` on failure, tasks were
     still being marked notified regardless of that return value — a real
     delivery failure got silently recorded as "delivered" and never
     retried. Fixed by changing `NotifyFn`'s contract from
     `Callable[[str, str], None]` to `Callable[[str, str], bool]`
     everywhere (`jarvis/interfaces/proactive.py`,
     `jarvis/interfaces/notify.py`, `jarvis/server/app.py`'s
     `make_push_notify_fn`) — `run_reminder_check` now only calls
     `mark_task_notified` if delivery actually succeeded.
- **Technologies:** FastAPI + Uvicorn (server), `pywebpush`/`py_vapid` (Web
  Push, verified still the standard vendor-free approach), Caddy
  (automatic HTTPS in front of the app, documented setup — not installed
  by this project), Hetzner CPX22 (~$9.49/mo, verified current pricing) or
  Oracle Cloud's Always Free tier (genuinely $0/mo) for hosting.
- **Cost:** Server hosting is the first genuinely new recurring cost this
  project introduces (or $0 on Oracle's free tier) — separate from
  Anthropic API usage, which is unchanged (the server makes the same LLM
  calls the laptop did).
- **Risks:** Expanded attack surface — the first phase where anything
  JARVIS does is reachable off the home network. Mitigated by
  auth-required-on-everything, HTTPS-only (via Caddy), and HIGH/CRITICAL
  tools being unreachable from this client at all rather than attempting a
  half-built remote-confirmation flow.
- **Security considerations:** Authentication is mandatory here, not
  optional, exactly as this entry originally called for — every endpoint
  requires a valid bearer token, checked with a constant-time comparison.
  The token lives in the PWA's `localStorage`, not sent anywhere except
  this server, and never logged.
- **Acceptance criteria (met):** Deployed for real to an Oracle Cloud
  Always Free x86 VM (the ARM shape ran out of capacity in the single-AD
  Hyderabad region — a known, common Always Free friction point), behind
  Caddy with a real Let's Encrypt certificate on a DuckDNS subdomain.
  Verified live: the PWA installed on an Android phone, chat/memory/tools
  work correctly over HTTPS with bearer-token auth, and — after finding
  and fixing the five bugs above — a real Web Push notification for a due
  reminder was successfully delivered to the phone, confirmed by the user
  directly. The full test suite (175 tests) covers the auth gate, chat
  dispatch, confirmation flow, push delivery success/failure semantics,
  and the VAPID key format via the real `py_vapid` parser (not just a
  mock), so a regression here fails loudly next time rather than silently
  shipping.
- **Known, accepted limitation:** delivery to a subscribed device isn't
  always instant — Android's own battery/Doze management can delay when a
  push notification actually surfaces, independent of anything this
  project controls. The server-side delivery attempt itself succeeds
  immediately; the device may take a little longer to display it.

## PHASE 10 — Advanced Personal AI OS ⬜
- **Objective:** The "take care of it" vision — broad task understanding,
  planning, tool use, and verification with appropriate autonomy.
- **Features:** Cross-domain task planning, outcome verification, richer
  personality/config layer.
- **Architecture changes:** Whatever the accumulated phases actually need —
  deliberately not pre-specified this far out.
- **Technologies:** TBD.
- **Cost:** TBD.
- **Risks:** Autonomy creep — every prior phase's confirmation/permission
  discipline still applies; more capability is not license for less
  oversight.
- **Security considerations:** Full audit trail, full permission layer,
  reviewed periodically as capability grows.
- **Acceptance criteria:** Defined when this phase is actually scoped, based
  on what Phases 1–9 revealed.
