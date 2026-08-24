# Architecture — PROJECT JARVIS

## High-Level Diagram

```text
                    ┌──────────────────────┐
                    │        USER           │
                    │  Voice / Text / UI     │
                    └──────────┬────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   Interaction Layer   │
                    │  STT / Chat / TTS      │
                    └──────────┬────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │      JARVIS CORE      │
                    │                        │
                    │ Orchestrator           │
                    │ Model Router           │
                    │ Context / Working Mem  │
                    │ Permission Layer       │
                    └──────────┬────────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
          ┌──────────┐   ┌──────────┐   ┌──────────┐
          │  TOOLS   │   │ MEMORY   │   │ AGENTS   │
          └──────────┘   └──────────┘   └──────────┘
                │              │              │
                ▼              ▼              ▼
          Web / Files      SQLite         Research
          Shell / Calc     Vector store   Coding
                            (Ph.6+)       Productivity
                                          Monitoring
```

## Guiding Principles

1. **Model-agnostic core.** The orchestrator never calls a provider SDK
   directly — everything goes through `llm.generate(task, complexity,
   privacy)` so the underlying model can change without touching application
   code.
2. **Permission layer sits between the LLM and every tool.** The LLM can
   *request* a tool call; it cannot execute one directly. Risk level per tool
   determines whether confirmation is required (see `SECURITY.md`, once
   written).
3. **Boring storage first.** SQLite for structured/episodic/task memory.
   Vector store only gets introduced when RAG is actually needed (Phase 6).
4. **No framework before it earns its place.** Hand-rolled orchestration
   until the tool/agent count genuinely outgrows it.
5. **Every phase ships a working system.** No half-finished layers merged
   without an end-to-end path exercising them.

## Phase 1 Component Map

```text
jarvis/
├── core/
│   ├── orchestrator.py   # conversation loop: input -> LLM -> response
│   ├── router.py         # model selection (single provider in Phase 1,
│   │                     #   but shaped for multi-provider from day one)
│   └── config.py         # loads .env / settings
│
├── voice/
│   ├── stt.py            # faster-whisper wrapper
│   └── tts.py            # Edge TTS wrapper
│
├── interfaces/
│   └── cli.py            # text + push-to-talk voice entrypoint
│
├── config/
│   └── settings.example.env
│
└── tests/
    └── ...
```

Memory (`memory/`), tools (`tools/`), and agents (`agents/`) directories get
introduced starting Phase 2–3, not before — an empty scaffold with no
behavior behind it just invites bit-rot.

## Data Flow (Phase 1)

```text
Voice (mic) ──▶ faster-whisper (local) ──▶ text
Text (typed) ───────────────────────────────┘
                                              │
                                              ▼
                                   JARVIS Core (orchestrator)
                                              │
                                              ▼
                                   Anthropic Claude API
                                   (Haiku default, Sonnet
                                    for flagged complexity)
                                              │
                                              ▼
                                        response text
                                        ├──▶ printed to console
                                        └──▶ Edge TTS ──▶ speaker
```

## Where This Grows

- **Phase 2** adds `memory/` (SQLite: profile, episodic log, task memory) and
  wires the orchestrator to read/write it around each turn.
- **Phase 3** adds `tools/` with the permission layer and audit log —
  first tools are low-risk (web search, file read).
- **Phase 4–5** add browser/computer control tools, still behind the same
  permission layer, risk-tiered as CRITICAL by default until proven safe.
- **Phase 6** adds a vector store for the personal knowledge base.
- **Phase 7+** adds `agents/` as specialized orchestrator instances with
  scoped tool access, then a scheduler for proactive behavior.
