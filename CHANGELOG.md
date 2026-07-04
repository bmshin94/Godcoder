# Changelog

All notable changes to Godcoder are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Benchmark harness (`tools/benchmark_harness.py`) for headless, reproducible per-task evaluation across models using clean git-worktree sandboxes.
- New manual GitHub Actions workflow (`.github/workflows/benchmark-harness.yml`) to execute benchmark runs and upload artifacts.

### Changed
- Release pipeline (`.github/workflows/release.yml`) now supports `v*` tag pushes by creating/reusing a release and uploading desktop artifacts plus static `bench-runner` binaries.
- Broader provider model discovery support in desktop agent bridge, with compatibility for OpenAI/Anthropic and OpenAI-compatible/Ollama endpoint response shapes.

---

## [0.3.0] - 2026-06-26

### Added
- **Self-Optimizing Harness Mode** — the agent now scaffolds, writes, and optimizes its own harness in real time without any human prompting. Activate by selecting *Harness* in the session composer.
- **ResearchSwarm bridge** — exposes `route`, `log`, `recall`, and `optimize` commands over a persistent memory store so the harness compounds knowledge across iterations.
- **Local Qwen model support** — configure any OpenAI-compatible local endpoint (Ollama, LM Studio, etc.) alongside cloud providers.
- **Voice API integration** — TTS, STT, and Voice-to-Voice settings now configurable from the Settings panel; credentials stored locally only.
- `harness-build/` sandbox isolation — all harness work is confined to a dedicated workspace; the rest of the repo is read-only reference.
- Auto-approval after first confirmation in Harness and Freestyle modes.

### Changed
- Agent core (`crates/agent/`) refactored to support pluggable mode routing (Ask / Plan / Coding / Freestyle / Harness).
- MCP server support extended to streamable HTTP and SSE transports in addition to stdio.

### Fixed
- Context Engine embedding key was leaking into desktop config in some setups.
- Checkpoint restore failed silently when `git-ops` crate encountered detached HEAD state.

---

## [0.2.0] - 2026-05-10

### Added
- **MCP Server support** — extend the agent toolset with external MCP servers over stdio.
- **Graph-Aware Context Engine** (optional) — semantic + structural search powered by tree-sitter, Qdrant, FalkorDB, and BM25. Enable in Settings → Context engine.
- `codebase_search` and `codebase_graph` tools automatically query the Context Engine when enabled.
- Windows quick-launch script (`launch-godcoder.bat`) — sets up Cargo on PATH and starts the app.

### Changed
- Desktop app migrated to Tauri 2.
- Provider abstraction layer redesigned to support arbitrary OpenAI-compatible base URLs.

### Fixed
- Session history was not persisted across restarts on Linux.
- File explorer did not refresh after agent wrote new files.

---

## [0.1.0] - 2026-03-18

### Added
- Initial public release of the rewritten Godcoder (formerly the 2024 autonomous-dev pipeline, now preserved under `v1/`).
- Pure-Rust agent core with Ask, Plan, and Coding modes.
- Tauri desktop app (thin adapter over the Rust core).
- In-place file editing with diff review and checkpoint/rewind via `crates/git-ops/`.
- Interactive terminal and file explorer built into the desktop UI.
- Support for OpenAI and Anthropic providers; configurable via Settings.
- MIT license.

---

## [Legacy] v1 — 2024 Pipeline

The original 2024 autonomous code-generation pipeline is frozen and preserved under `v1/`. It is not maintained but remains available as a historical reference.

[Unreleased]: https://github.com/eli-labz/Godcoder/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/eli-labz/Godcoder/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/eli-labz/Godcoder/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/eli-labz/Godcoder/releases/tag/v0.1.0
