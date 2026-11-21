# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] - 2026-11-21

### Added
- **Model-Agnostic BYOK Engine (15+ Providers):** Native Anthropic Messages API (extended thinking + prompt caching), Google Gemini & Vertex AI (ADC auto-refresh), OpenAI, NVIDIA NIM, DeepSeek, Qwen, Zhipu GLM, Groq, Mistral, OpenRouter, Together AI, plus zero-key local Ollama, vLLM, LM Studio, and `llama.cpp`.
- **Native Tauri v2 + React 18 Desktop Workspace:** Warm editorial light/dark palette with SIL OFL `Newsreader` + `Noto Naskh Arabic` typography, multilingual RTL/BiDi support, global summon shortcut, system tray, conversation branching, and OS keychain secret storage.
- **Agentic Coding Harness:** Symlink-safe workspace file jail (`read_file`, `edit_file`, `write_file`, `glob`, `grep`), workspace-cwd `bash` test/build runner, per-turn file checkpoints with one-click Rewind, `.claude/settings.json` rule compatibility, and 5-event programmable lifecycle hooks (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`).
- **Interactive Gen-2 Artifacts & Office Exports:** Live streaming HTML, React/JSX, SVG, Mermaid, Markdown, and code previews inside isolated `sandbox="allow-scripts"` iframes, plus downloadable `.xlsx`, `.docx`, `.pptx`, and `.pdf` generation.
- **MCP, One-Click `.mcpb` Bundles, `/skill-builder`, Cowork & Terminal CLI (`ocd`):** Stdio + Streamable HTTP + OAuth PKCE MCP connectors, bundled plugin marketplace, conversational `/skill-builder`, background Cowork tasks, and shared `ocd` terminal REPL.
