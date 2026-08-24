# Environment Assessment — PROJECT JARVIS

_Generated 2026-08-19 by initial environment scan._

## Hardware

| Component | Detail |
|---|---|
| CPU | Intel Core Ultra 5 125H — 14 cores / 18 threads, includes an NPU (~11 TOPS via OpenVINO) |
| GPU | Intel Arc (integrated) — no dedicated VRAM, shared system memory |
| RAM | 15.68 GB usable (~16 GB) |
| Disk | **C: 7.3 GB free / 230.6 GB total** ⚠️, D: 62.2 GB free / 244.1 GB total, G: 6.9 GB free / 230.6 GB total |
| Microphone | Present and enabled ("Senary Audio") |

**Critical constraint: C: is almost full.** The project currently lives at
`C:\Users\ADITYA\OneDrive\Documents\J.A.R.V.I.S`, which is both (a) on the
nearly-full C: drive and (b) inside OneDrive's sync scope. Two compounding risks:
- Python/Node tooling, pip/uv caches, Docker images, and model weights (Whisper,
  local LLMs, embeddings) default-install to C: and can easily add 5–20+ GB —
  there isn't room.
- OneDrive syncing `node_modules`, `.venv`, model checkpoints, and SQLite/vector
  DB files causes file-lock errors, sync churn, and can silently corrupt a DB
  that's being written while syncing.

**No dedicated GPU.** Local LLM inference is CPU-bound (or Vulkan-via-Arc-iGPU
at best). Realistic local ceiling: ~7–8B parameter models at Q4 quantization,
usable but not fast (a few tokens/sec). The NPU can accelerate Whisper STT via
OpenVINO but that's an optimization for later, not day one.

## Software

| Tool | Version | Notes |
|---|---|---|
| OS | Windows 11 Home 24H2, Build 26200 | |
| Python (default) | 3.14.3 | **Too new** — many ML wheels (torch, faster-whisper, etc.) lag behind the latest CPython. Do not build the AI venv on this. |
| Python (available via `uv`) | 3.12.13, already installed locally | **Recommended interpreter for this project.** |
| Node.js | v24.13.0 | Fine, modern |
| npm | 11.6.2 | |
| Git | 2.55.0 | |
| Docker | 29.7.2 (Desktop) | Installed but daemon not currently running |
| Package managers | `winget`, `uv` (no choco/scoop, no system `pip`/`conda`) | Use `uv` for Python deps |
| ffmpeg | **Not installed** | Required for audio I/O (Whisper, TTS playback) |
| Ollama | **Not installed** | Needed only if/when we add local LLM fallback |
| WSL2 | Present (docker-desktop distro) | Backs Docker Desktop |

## API Keys / Secrets

Checked for presence only (no values read):

| Variable | Status |
|---|---|
| `ANTHROPIC_API_KEY` | not set |
| `OPENAI_API_KEY` | not set |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | not set |
| `AZURE_OPENAI_API_KEY` | not set |
| `ELEVENLABS_API_KEY` | not set |
| `PORCUPINE_ACCESS_KEY` | not set |
| `HUGGINGFACE_TOKEN` / `HF_TOKEN` | not set |
| `GROQ_API_KEY` | not set |
| `OPENWEATHER_API_KEY` | not set |

No cloud provider is currently configured. A provider decision + API key is
needed before Phase 1 can call a cloud LLM.

## Capabilities Summary

- ✅ Can run a modern Python (3.12) and Node (24) stack via `uv`/`npm`
- ✅ Docker available (daemon needs to be started when used)
- ✅ Microphone present for voice input
- ⚠️ No GPU — local LLM/STT/TTS must stay small or lean on cloud APIs
- ⚠️ C: drive nearly full — installs, caches, and model weights must be
  redirected to D: (or the project relocated there)
- ⚠️ OneDrive-synced project folder — recommend excluding heavy/volatile
  subfolders (`.venv`, `node_modules`, `data/`, model caches) from sync, or
  moving the whole project to a non-synced path
- ❌ No LLM/STT/TTS API keys configured yet — needed for any cloud-based
  component

## Recommended Immediate Fixes (before Phase 1 code)

1. Decide project location: keep at current OneDrive path (with sync
   exclusions for volatile folders) or move to `D:\Projects\JARVIS`.
2. Point Python/uv/pip/Docker caches at D: via env vars
   (`UV_CACHE_DIR`, `PIP_CACHE_DIR`, `HF_HOME`) to avoid filling C:.
3. Install `ffmpeg` (`winget install ffmpeg` — few hundred MB, put on D: if
   possible).
4. Create the project's Python virtualenv against `cpython-3.12`, not the
   default 3.14.
5. Choose and obtain one cloud LLM API key (recommendation: Anthropic Claude,
   see `TECHNOLOGY_DECISIONS.md`).

## Recommended AI Models Given This Hardware

- **Cloud reasoning (primary):** Claude Haiku for routine turns, Claude Sonnet
  for anything requiring real reasoning — cheap and requires no local
  compute.
- **Local STT:** `faster-whisper` `small` or `base` model, CPU (int8) — a few
  seconds of latency per utterance, no cost, no GPU required.
- **Local TTS:** Piper (tiny, fast, fully offline, natural-enough voices) or
  Edge TTS (free, cloud, better quality, needs internet).
- **Local LLM (optional, later):** if Ollama is added, an 8B-class quantized
  model (e.g. Llama 3.1 8B Q4) is the realistic ceiling on this CPU — usable
  for simple/offline/private tasks, not for complex reasoning.

## Estimated Running Cost

Assuming light personal use (a few dozen assistant turns/day):
- Claude API (Haiku-heavy, occasional Sonnet): **~$3–10/month**
- STT/TTS: **$0/month** if using local Whisper + Piper/Edge TTS
- Everything else (SQLite, local vector store, Docker): **$0** (self-hosted)

**Estimated total: $3–10/month** for Phase 1–3, scaling with usage and how
often premium/cloud models are invoked.
