# Technology Decisions — PROJECT JARVIS

Decisions are scoped to what Phase 1–3 actually need. Later phases will add
their own rows here rather than pre-selecting everything now (Rule: don't
introduce a framework before it's needed).

## LLM

| Option | Cost | Pros | Cons | Recommendation |
|---|---:|---|---|---|
| Anthropic Claude (Haiku/Sonnet API) | ~$0.25–3 / M tokens in, varies by model | Strong reasoning, cheap Haiku tier for routine turns, easy to route by complexity, good tool-use support | Requires internet + API key + billing | **Primary cloud model** |
| OpenAI (GPT-4o-mini / GPT-4o) | Similar range | Also strong, mature ecosystem | Same requirements as above; no reason to run two cloud providers at once | Backup option if preferred over Anthropic |
| Google Gemini (Flash) | Free tier available, then cheap | Generous free tier | Slightly less consistent tool-calling in practice | Viable cheap alternative |
| Local via Ollama (Llama 3.1 8B / Qwen 2.5 7B, Q4) | $0 | Free, private, offline | Slow on this CPU-only machine (no GPU), noticeably lower reasoning quality than cloud | **Optional fallback** for offline/private/simple tasks, not primary |

**Decision:** Route by task complexity/privacy through a thin abstraction
(`llm.generate(task, complexity, privacy)`), starting with a single cloud
provider (Anthropic, pending your key) for everything in Phase 1. Local model
via Ollama can be added later as the "privacy" / "offline" branch without
touching the app code, since it sits behind the same interface.

## Speech-to-Text

| Option | Cost | Pros | Cons | Recommendation |
|---|---:|---|---|---|
| `faster-whisper` (local, CPU int8) | $0 | Free, private, no network dependency, good accuracy at `small`/`base` | A few seconds latency per utterance on CPU; needs ffmpeg | **Recommended for Phase 1** |
| OpenAI Whisper API | $0.006/min | Very accurate, fast, zero local compute | Costs money, needs internet, sends audio to a third party | Fallback if local latency is too high |
| Cloud STT (Azure/Google) | Similar | Real-time streaming support | More setup, another vendor/key | Not needed yet |

**Decision:** `faster-whisper` running locally (`base` or `small` model,
int8). No cost, keeps voice data on-device, and this CPU can handle
short-utterance transcription within a few seconds.

## Text-to-Speech

| Option | Cost | Pros | Cons | Recommendation |
|---|---:|---|---|---|
| Piper (local) | $0 | Fully offline, fast, small models, decent quality | Voices are noticeably synthetic vs. cloud options | Good default, zero cost |
| Edge TTS (free, cloud) | $0 | Very natural voices, free, no API key needed | Needs internet, unofficial API (Microsoft could change it) | **Recommended for Phase 1** — best quality-to-cost ratio |
| OpenAI TTS | ~$15/M chars | Natural, reliable, official API | Costs money for a chatty assistant | Use only if Edge TTS proves unreliable |
| ElevenLabs | Higher, has free tier | Best-in-class voice quality/cloning | Free tier is limited; paid tiers add up fast for a "personal assistant" that talks a lot | Not justified for MVP |

**Decision:** Edge TTS as the default (free, good quality, no key setup
friction) with Piper as an offline fallback if network TTS isn't desired for
a given deployment.

## Memory / Storage

| Option | Cost | Pros | Cons | Recommendation |
|---|---:|---|---|---|
| SQLite | $0 | Zero setup, file-based, perfect for structured memory (profile, tasks, episodic log) | Not a vector store | **Structured memory (Phase 2)** |
| Chroma (embedded) | $0 | Simple embedded vector store, no server needed, pairs naturally with SQLite-based metadata | Less mature at scale than Qdrant | **Semantic memory, when RAG is actually needed** |
| Qdrant / pgvector | $0 self-hosted | Production-grade, scalable | Needs Docker/Postgres running — unnecessary weight for a single-user assistant on a disk-constrained laptop | Overkill for now; revisit only if the KB grows large |
| FAISS | $0 | Fast, lightweight | Lower-level, more code to manage persistence/metadata than Chroma | Not needed while Chroma covers it |

**Decision:** SQLite for everything structured (profile, task memory,
episodic log, audit log) starting Phase 2. Chroma only gets introduced in
Phase 6 (Personal Knowledge Base) when RAG is actually needed — not before.

## Agent Framework

| Option | Cost | Pros | Cons | Recommendation |
|---|---:|---|---|---|
| Custom tool-calling loop (Python, using the provider's native tool-use) | $0 | Full control, minimal dependencies, easy to reason about and secure (permission layer sits directly in our code) | We write more glue code ourselves | **Recommended through Phase 3–5** |
| LangGraph | $0 (OSS) | Good for complex multi-step agent graphs | Adds a real learning curve and abstraction layer before we need one | Reconsider only in Phase 7 if orchestration logic outgrows a hand-rolled router |
| CrewAI | $0 (OSS) | Nice multi-agent role abstractions | Opinionated, heavier than needed for a single orchestrator + tools | Not needed |
| MCP (Model Context Protocol) | $0 | Good standard for exposing tools, plays well with Claude, future-proofs tool integrations | Adds a server/client layer before Phase 1 needs it | Adopt in Phase 3+ once we have more than a couple of tools worth standardizing |

**Decision:** Hand-rolled orchestrator + native tool-calling (Anthropic's
tool-use format) for now. No agent framework in Phase 1–2. Revisit MCP once
the tool count grows enough that a standard interface pays for itself.

## Wake Word (Phase 1 note — not blocking)

| Option | Cost | Pros | Cons |
|---|---:|---|---|
| Push-to-talk (keypress) | $0 | Zero complexity, works immediately | Not hands-free |
| OpenWakeWord | $0, local | Open source, offline | Extra setup, another local model |
| Porcupine | Free tier (personal use) | Very accurate, low CPU | Requires an access key + account |

**Decision:** Push-to-talk for Phase 1 MVP (per the brief — don't let wake
word block the MVP). Revisit OpenWakeWord once the core loop works.
