# PROJECT JARVIS

A personal AI assistant, built incrementally. Through **Phase 9**: a text +
voice MVP (Phase 1) with persistent memory (Phase 2), real tool calling
(Phase 3), live web search + page fetch with citations (Phase 4), local
file writes + an allowlisted shell (Phase 5), a personal knowledge base
over your own documents (Phase 6), a scoped-tool-access research agent
(Phase 7), unprompted morning-brief/reminder-due notifications (Phase 8),
and a multi-device server + installable web app (Phase 9) — JARVIS can do
arithmetic, read/write files in its own workspace, search and fetch the
web, run a small set of dev-tool commands, answer questions from
PDFs/notes/docs you explicitly ingest, produce a structured research
report on a topic you name, surface a daily brief or a due reminder
without being asked, and now be reached (by voice or text) from your
phone or any browser over HTTPS, all permission-gated, rate-limited, and
audit-logged where it matters. No interactive browser/GUI control yet,
and only one specialized agent so far (coding/monitoring agents are
deferred — see `docs/ROADMAP.md` Phase 5 and Phase 7 for why). See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for what comes next and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how it fits together.

## Prerequisites

Already verified on this machine (see `docs/ENVIRONMENT.md`):
- Python 3.12 (via `uv` — do **not** use the system default 3.14, ML wheels
  lag behind it)
- `uv` (package/venv manager)
- `ffmpeg` (installed via `winget install ffmpeg`)
- A microphone, if you want to use voice input

Two cache locations are redirected off the nearly-full C: drive —
`UV_CACHE_DIR` and `HF_HOME` are already set as persistent User environment
variables (pointing at `D:\uvcache` and `D:\hfcache`). If you ever set this
up on a different machine, do the same there first:

```powershell
setx UV_CACHE_DIR D:\uvcache
setx HF_HOME D:\hfcache
```

(Restart your terminal after `setx` so new values take effect.)

## Setup

```powershell
cd D:\Projects\JARVIS
uv venv --python 3.12 .venv
uv sync
copy config\settings.example.env .env
```

Then open `.env` and fill in `ANTHROPIC_API_KEY` (get one at
https://console.anthropic.com/). Everything else has a working default.

## Run

```powershell
uv run python -m jarvis.interfaces.cli
```

- Type a message and press Enter to chat by text.
- Press Enter with nothing typed to start voice recording; press Enter
  again to stop and have it transcribed.
- Type `exit` or `quit` to stop.

Every reply is both printed and spoken aloud (via Edge TTS + ffmpeg).

### Memory commands

JARVIS only remembers something when you explicitly say so — no passive
inference from normal conversation (see `docs/ROADMAP.md` Phase 2 for why).

- `remember that <fact>` — stores a fact, recalled in future sessions too.
- `remind me to <task> [at/on <time>]` — stores a reminder; if a time is
  recognized it's parsed and stored. Phase 8's reminder-check job (see
  below) is what actually notifies you once it's due.
- `what do you remember about me?` — lists everything currently stored.
- `forget <substring>` — deletes any stored fact containing that text.
- `forget everything` / `clear my memory` — wipes all facts, tasks, and
  history. Requires typing `yes` to confirm — this is the one destructive,
  irreversible command in this phase.

Memory lives in `data/memory.db` (SQLite, gitignored — never committed).

### Tools

JARVIS can call seven tools during a normal conversation — no special
syntax needed, just ask. Two require typed confirmation before they run:

- **calculator** (LOW risk) — arithmetic, evaluated by a restricted parser
  (no `eval()`, no code execution — just `+ - * / **` and parentheses).
- **filesystem_read** (LOW risk) — reads text files, but only inside the
  project workspace (`TOOLS_WORKSPACE_DIR` in `.env`, defaults to the
  project root) and never `.env`, anything under `.git/`, or `.pem`/`.key`
  files, regardless of location.
- **filesystem_write** (**HIGH risk — asks first**) — creates or overwrites
  a text file, same workspace scoping and protected-file rules as
  `filesystem_read`.
- **shell_execute** (**CRITICAL risk — always asks**) — runs a command,
  but only if its executable is one of `git`, `python`, `node`, `npm`,
  `uv`, `where`. No pipes, redirects, or chaining — that allowlist check
  happens *before* you're ever asked to confirm, so a disallowed command
  is rejected outright rather than costing you a decision.
- **web_search** (LOW risk) — Anthropic-hosted; no separate API key
  needed. Billed by Anthropic as part of normal API usage.
- **web_fetch** (LOW risk) — Anthropic-hosted page fetch + summarize, with
  citations. Only fetches URLs already present in the conversation (paste
  one, or let `web_search` surface one first) — it can't be pointed at an
  arbitrary URL the model invents.

- **knowledge_search** (LOW risk) — semantic search over documents you've
  explicitly ingested (see below). Takes a query, not a file path.

The permission layer (`jarvis/core/permissions.py`) requires typed
confirmation (`Type 'yes' to allow`) for anything above LOW risk.
`web_search`/`web_fetch` are server-side (Anthropic executes them — no
audit-log entry). Every client-side tool call — approved, declined, *or
rejected outright by a hard boundary like the shell allowlist* — is logged
to `tool_audit_log` in `data/memory.db`.

### Personal knowledge base

Nothing gets indexed automatically — you add documents explicitly, the
same explicit-only policy as memory (Phase 2):

- `ingest <path>` — adds a `.txt`, `.md`, or `.pdf` file (path relative to
  the workspace, same scoping/denylist as `filesystem_read`) to the
  knowledge base. Re-ingesting the same path updates it rather than
  duplicating. Reports the number of chunks added.
- Just ask a question naturally (e.g. "what does my resume say about
  X?") — JARVIS decides when to use `knowledge_search` and cites the
  source filename (and page, for PDFs).
- `what have you ingested?` / `what documents do you know about?` — lists
  ingested sources and chunk counts.
- `forget document <name>` — removes a document and all its chunks.

Embeddings run locally via Chroma's built-in ONNX model (~80MB, downloaded
once) — no API key, no document content ever leaves the machine. Storage
lives in `data/chroma/` (gitignored). If you set this up on a fresh
machine, be aware Chroma's model cache hardcodes to
`%USERPROFILE%\.cache\chroma` with no config override — redirect it the
same way this project redirected `HF_HOME`/`UV_CACHE_DIR` if that lands
somewhere space-constrained (this machine uses a directory junction, since
there's no env var for it).

### Research agent

`research <topic>` runs a scoped, read-only agent (Phase 7) instead of a
normal chat turn — it can't be triggered by the main LLM on its own, only
by typing this exact command:

- Tool access is deliberately minimal: `web_search`, `web_fetch`, and
  `knowledge_search` only — no `filesystem_write`, `shell_execute`, or
  `calculator`, so the agent itself can never modify anything.
- Runs at Sonnet tier (`complexity="high"`) for better multi-source
  synthesis than a normal chat turn.
- Produces a structured Markdown report (Summary / Key Findings with
  citations / Sources), prints it, and saves it to
  `research/<slugified-topic>.md` in the workspace — the save itself
  doesn't need confirmation (same precedent as `ingest`), but is still
  logged to `tool_audit_log`.
- Costs noticeably more than a normal chat turn (several Sonnet calls plus
  billed web search/fetch usage) — expect it to use meaningfully more of
  your Anthropic API credit than everyday chatting.

### Shopping-compare agent

`find <item>` (`jarvis/agents/shopping.py`) is the same shape as the
research agent — a scoped agent dispatched only by exact command text, not
something the main chat LLM can trigger on its own — but purpose-built for
comparison shopping instead of open research:

- Searches specifically across a fixed shortlist: Amazon, Flipkart, Zepto,
  Blinkit, Swiggy Instamart, Zomato, BigBasket, Meesho, Nykaa, Myntra, and
  Toing.
- Tool access is `web_search` + `web_fetch` only — no `knowledge_search`
  (this isn't about your own documents) and nothing that writes anything.
- Produces a short ranked comparison (site, price, pack size/delivery
  estimate, link) with a reminder that prices/stock on these apps change
  fast — nothing gets saved to disk, unlike `research`, since a price
  quote is stale within hours.
- **Never places an order.** No platform in that shortlist exposes a
  public order-placement API to third parties — ONDC is the one open
  protocol built for this, but it gates access behind registering as an
  approved Network Participant, not something an individual project can
  do. Even if that gate didn't exist, a purchase is a financial
  transaction and always needs your own explicit, per-instance
  confirmation — this agent's job stops at finding and reporting; you buy
  it yourself, in the app.

### Proactive notifications (Phase 8)

JARVIS can surface a morning brief and due-reminder nudges without being
asked, via two Windows Task Scheduler tasks that each run
`jarvis/interfaces/proactive.py` — a short-lived process, not a background
service. Both respect `MAX_NOTIFICATIONS_PER_DAY` (`.env`, default 10,
shared across both jobs) and pass through the same permission layer as
everything else (`jarvis/core/tool_loop.py`) — no separate, looser path.

- **Morning brief** (`--job morning_brief`) — calls the LLM (Haiku tier,
  minimal tool scope: `knowledge_search` + basic `web_search`, never the
  dynamic-filtering variant — see `docs/ROADMAP.md` Phase 7's container-id
  bug) to summarize your open tasks/facts into a short notification. Uses
  your Anthropic API credits.
- **Reminder check** (`--job reminder_check`) — purely deterministic, no
  LLM call, **$0**: notifies once a `remind me to ...` task's due time has
  passed, batching every overdue reminder into a single toast rather than
  spamming one per task.

**Registering the scheduled tasks is a manual, one-time step you run
yourself** (same precedent as installing `ffmpeg` via `winget` above) —
JARVIS's own `shell_execute` tool deliberately excludes `schtasks` from its
allowlist, since registering scheduled tasks is a system-level change
outside a chat tool's remit.

First, find your `uv` install path (Task Scheduler's PATH may differ from
your interactive shell's):

```powershell
where uv
```

Then, from PowerShell (adjust the `uv` path and project path if yours
differ — **leave `/ru` and `/rl` unset** so the task runs interactively as
you, not as SYSTEM; toast notifications never reach the desktop from a
non-interactive session, even if the toast call itself succeeds):

```powershell
schtasks /create /tn "JARVIS Morning Brief" /tr "\"C:\Users\<you>\.local\bin\uv.exe\" --directory D:\Projects\JARVIS run python -m jarvis.interfaces.proactive --job morning_brief" /sc daily /st 07:30 /f

schtasks /create /tn "JARVIS Reminder Check" /tr "\"C:\Users\<you>\.local\bin\uv.exe\" --directory D:\Projects\JARVIS run python -m jarvis.interfaces.proactive --job reminder_check" /sc minute /mo 15 /f
```

- **07:30 daily** for the morning brief and **every 15 minutes** for the
  reminder check are reasonable defaults — adjust `/st` (start time) or
  `/mo` (interval in minutes) to taste. A `/mo 15` reminder check means a
  reminder can fire up to ~15 minutes after its actual due time.
- Verify registration: `schtasks /query /tn "JARVIS Morning Brief" /v /fo list`
- Run one immediately to test: `schtasks /run /tn "JARVIS Reminder Check"`
- Remove either: `schtasks /delete /tn "JARVIS Morning Brief" /f`

**Known limitation:** `remind me to ...`'s due time is parsed and stored as
naive local time (`dateparser`), while the rest of the memory DB uses
tz-aware UTC timestamps. The reminder-check job accounts for this today,
but it's a convention mismatch worth knowing about if you query
`data/memory.db` directly.

### Multi-device server (Phase 9)

A FastAPI server (`jarvis/server/`) wraps the same `Orchestrator` `cli.py`
uses, reachable from your phone or any browser over HTTPS via a small
installable web app (PWA) — chat, memory, voice, and push notifications
all work from anywhere (see "Voice on the web client" below);
**HIGH/CRITICAL-risk tools (`filesystem_write`, `shell_execute`) are
auto-declined from this client** (no synchronous human to confirm them
over HTTP yet — a real approve-from-your-phone flow is deferred).

**Local dry run first, $0, no real infrastructure needed:**

```powershell
uv run uvicorn jarvis.server.main:app --reload
```

Open `http://localhost:8000`, paste your `API_AUTH_TOKEN` (see below) when
prompted, and chat. This is enough to confirm everything works before
deploying anywhere.

**One-time setup, in `.env`:**

```powershell
# a long random secret the PWA sends on every request
python -c "import secrets; print(secrets.token_urlsafe(32))"

# a VAPID keypair for self-hosted Web Push (no Firebase/OneSignal) —
# prints two bare base64url strings, no PEM armor (pywebpush's key parser
# only accepts the raw key — see jarvis/server/push.py's docstring for the
# real bug this fixed)
uv run python -m jarvis.server.push
```

Paste the results into `API_AUTH_TOKEN`, `VAPID_PRIVATE_KEY`, and
`VAPID_PUBLIC_KEY` exactly as printed. **Never regenerate the VAPID
keypair once a device has subscribed to push** — it invalidates every
existing subscription.

**Deploying for real** (only do this once you're ready to pay for/manage
real infrastructure — this isn't run automatically). This has actually
been done once, on Oracle Cloud's Always Free tier — the steps below
reflect what that real deployment needed, including the friction points
hit along the way.

1. **Provision a VM.** [Hetzner](https://www.hetzner.com/cloud/) CPX22
   (~$9.49/mo) is the simplest, most reliable option. Oracle Cloud's
   [Always Free tier](https://www.oracle.com/cloud/free/) is genuinely
   $0/mo but has real friction: the popular Ampere (ARM, A1.Flex) shape
   frequently has **no capacity** in single-availability-domain regions
   (e.g. India South/Hyderabad has only one AD, so there's no fallback AD
   to retry within the region) — if this happens repeatedly, fall back to
   the x86 **VM.Standard.E2.1.Micro** shape instead (always has capacity,
   tighter on RAM at 1GB, but sufficient for a single-user server). Use
   Ubuntu as the image either way. When creating the instance, if
   Networking shows "Automatically assign public IPv4 address" as
   disabled with a warning about needing a public subnet, the inline
   VCN-creation wizard is buggy — cancel, create the VCN separately via
   **Networking → Virtual Cloud Networks → Start VCN Wizard → "Create VCN
   with Internet Connectivity"** (this correctly wires up a public subnet
   + internet gateway), then redo instance creation selecting that VCN's
   public subnet. **Set the VM's timezone to your own**
   (`sudo timedatectl set-timezone <Region/City>`) — the morning brief's
   trigger hour (`MORNING_BRIEF_HOUR` in `.env`, default 7) is read
   against the server's local clock, not UTC-adjusted, so the timezone
   has to be right first.
2. **Open ports 80/443 at *two* separate layers** — both are needed,
   neither implies the other:
   - The cloud firewall: **Networking → Virtual Cloud Networks → your VCN
     → Security Lists → Default Security List → Add Ingress Rules** — TCP,
     source `0.0.0.0/0`, destination ports 80 and 443.
   - The OS-level firewall (Oracle's Ubuntu images block everything but
     SSH by default via `iptables`, independent of the cloud firewall
     above):
     ```bash
     sudo iptables -L INPUT -n --line-numbers   # find the line number of the REJECT rule first
     sudo iptables -I INPUT <line-before-REJECT> -p tcp -m state --state NEW --dport 80 -j ACCEPT
     sudo iptables -I INPUT <line-before-REJECT> -p tcp -m state --state NEW --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```
     **The rules must land before the REJECT rule, not after** — inserting
     at a hardcoded position without checking can land them after it,
     where they're silently never reached (found live: this produced
     `ERR_CONNECTION_TIMED_OUT` even with the cloud firewall correctly
     configured). Re-run `iptables -L INPUT -n --line-numbers` after to
     confirm the ACCEPT rules for 80/443 appear above REJECT.
3. **Get a domain pointed at the VM.** Let's Encrypt (which Caddy uses)
   can't issue a certificate for a bare IP address. If you don't own a
   domain, [DuckDNS](https://www.duckdns.org) gives a free subdomain
   (`yourname.duckdns.org`) — sign in, add a subdomain, and manually set
   its IP to the VM's public IP (DuckDNS defaults to auto-filling *your
   current browser's* IP, which is wrong here).
4. Copy the project to the VM (no git remote needed — a zip/scp works
   fine for a single deploy):
   ```powershell
   Compress-Archive -Path jarvis, tests, config, pyproject.toml, uv.lock, README.md, docs, .gitignore -DestinationPath jarvis-deploy.zip -Force
   scp -i your_key.pem jarvis-deploy.zip ubuntu@<VM_IP>:~/
   ```
   Then on the VM: `unzip jarvis-deploy.zip -d ~/jarvis && cd ~/jarvis && uv sync`.
5. Copy `.env` over too (**the whole file, including `ANTHROPIC_API_KEY`**
   — this VM now needs it) and migrate your existing data once: `scp` both
   `.env` and `data/` from this laptop to the VM. The VM becomes the
   single source of truth from here on; day-to-day use moves to the web
   client on both your phone and this laptop instead of running `cli.py`
   locally, so there's only one memory store to keep in sync (i.e., none).
6. Install [Caddy](https://caddyserver.com/) and put it in front of the
   app for automatic HTTPS — a Caddyfile this simple is enough:
   ```
   your-subdomain.duckdns.org {
       reverse_proxy localhost:8000
   }
   ```
7. Run the app as a systemd service:
   ```bash
   sudo tee /etc/systemd/system/jarvis.service <<'EOF'
   [Unit]
   Description=JARVIS multi-device server
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/jarvis
   Environment=PATH=/home/ubuntu/.local/bin:/usr/bin:/bin
   ExecStart=/home/ubuntu/.local/bin/uv run uvicorn jarvis.server.main:app --host 127.0.0.1 --port 8000
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   EOF
   sudo systemctl daemon-reload && sudo systemctl enable --now jarvis
   ```
8. On your phone, open the site in Chrome and paste the token — saving it
   automatically triggers the browser's notification-permission prompt too
   (there's no separate button; browsers don't allow a site to silently
   grant itself that permission, so this rides along on that first genuine
   tap instead). On Android, also double-check Chrome's *system-level*
   notification permission (Settings → Apps → Chrome → Notifications) —
   some OEM battery-management skins silently disable it even after the
   in-page permission prompt is granted. Delivery isn't always instant;
   Android's own Doze/battery optimization can delay when a push actually
   surfaces, independent of anything this server controls.
9. Once a real push notification is confirmed arriving on your phone,
   disable Phase 8's Windows Task Scheduler jobs (`schtasks /change /tn
   "JARVIS Morning Brief" /disable`, same for "JARVIS Reminder Check") —
   the server-side scheduler in `jarvis/server/app.py` replaces them, and
   running both would double-notify you.

**Debugging a stuck deployment:** `sudo journalctl -u jarvis -n 50
--no-pager` and `sudo journalctl -u caddy -n 50 --no-pager` (add
`--no-pager` always — the default pager needs `q` to exit and otherwise
looks like the command hung). `sudo ss -tlnp | grep -E ':80|:443'` confirms
Caddy is actually listening. A stuck Let's Encrypt request usually means
one of the two firewall layers in step 2 above isn't actually open yet.

**"Clear & reset" (used above to fix a stale service-worker cache) wipes
*everything*** — cookies, cache, service worker registration, and
`localStorage`, where your bearer token lives. If you keep having to
re-paste the token, you're probably reaching for that instead of a normal
refresh. A plain reload (pull-to-refresh, the reload icon, or closing and
reopening the tab) does **not** touch `localStorage` — save "Clear &
reset" for an actual stuck-cache problem, not routine refreshing.

### Voice on the web client

The mic button (🎤) and "Speak replies" toggle in the web client use the
browser's built-in **Web Speech API** — not `jarvis/voice/stt.py`/`tts.py`,
which stay local-only for `cli.py`. This was a deliberate choice over
porting Whisper to the server: `faster-whisper`'s smallest model alone
needs more RAM than the whole 1GB VM has to spare. The trade-off: Chrome's
speech recognition sends audio to Google's servers to transcribe it — not
self-hosted, unlike this project's usual bias — while speech *synthesis*
(reading replies aloud) runs fully on-device with no such trade-off.

- Tap 🎤, speak, and it transcribes + sends automatically when you stop
  talking (same as typing and hitting Send).
- "Speak replies" (default **on**) reads every new reply aloud; tap the
  toggle to turn it off. The little "🔊 replay" under any message replays
  that one on demand regardless of the toggle's state.
- **Not possible via a web app:** true wake-word activation ("say JARVIS
  and it opens/listens, like Alexa/Siri") — browsers don't allow a page to
  keep listening once the tab isn't open in the foreground, and there's no
  way for a website to register as an OS-level voice service the way real
  assistants do. That would need a native mobile app, a different project
  from this one.
- Only tested on Chromium browsers (Android Chrome, Windows Chrome/Edge).
  Firefox/Safari have weak or no `SpeechRecognition` support — the mic
  button and toggle just don't appear there instead of erroring.
- No server changes, no redeploy beyond copying the updated
  `index.html` — this feature is 100% client-side.

## Test

```powershell
uv run pytest
```

Tests are fully mocked/offline — no API key or network calls required
(the one exception, `tests/test_stt.py`, uses a pre-generated sample WAV
checked into `tests/fixtures/`).

## Project Layout

```text
jarvis/
├── core/
│   ├── config.py         # .env loading + validation
│   ├── router.py         # model selection (Haiku/Sonnet); returns raw Message
│   ├── permissions.py    # tool risk tiers + confirmation gate (Phase 3)
│   ├── commands.py       # regex-based memory/research command detection (Phase 2, 7)
│   ├── tool_loop.py      # shared tool-calling loop + gating, reused by agents (Phase 7)
│   └── orchestrator.py   # conversation loop, system prompt, memory + tool-call wiring
├── agents/
│   └── research.py       # scoped research agent: web/knowledge tools only (Phase 7)
├── tools/
│   ├── spec.py            # shared ToolSpec dataclass (incl. optional pre-confirm validate hook)
│   ├── registry.py        # calculator + aggregates every tool into client_tools()
│   ├── filesystem.py      # filesystem_read/write, workspace scoping, protected-file denylist
│   ├── shell.py           # shell_execute: allowlisted, non-shell subprocess runner
│   └── knowledge.py       # knowledge_search tool wrapper over KnowledgeStore
├── memory/
│   ├── db.py              # SQLite connection + schema (facts/tasks/episodic/audit)
│   ├── store.py            # MemoryStore: CRUD + tool_audit_log
│   └── semantic.py         # KnowledgeStore: Chroma-backed RAG (ingest/search/list/forget)
├── voice/
│   ├── stt.py             # mic capture + faster-whisper transcription
│   └── tts.py             # edge-tts synthesis + playback
├── interfaces/
│   ├── cli.py             # text/voice entrypoint
│   ├── notify.py          # Windows toast delivery (Phase 8, lazy win11toast import)
│   └── proactive.py       # morning-brief + reminder-check jobs, run by Task Scheduler (Phase 8)
└── server/
    ├── app.py             # create_app() FastAPI factory: /chat, push, background scheduler (Phase 9)
    ├── main.py            # production wiring (real settings/store/client) for `uvicorn ...:app`
    ├── auth.py            # bearer-token dependency
    ├── push.py             # self-hosted Web Push (VAPID) via pywebpush
    └── static/            # the installable PWA (index.html, manifest.json, sw.js)
```
