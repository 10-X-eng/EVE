# STEVE 0.3.0 — Grok / X and local Ollama

Choose ChatGPT, Grok / X, or local Ollama to work with STEVE inside Autodesk Fusion. This release adds provider selection while preserving existing ChatGPT conversations and settings.

## What changed

- **Meet STEVE.** Updated name, S logo, toolbar, installers, and release packages. Existing managed installations and saved data transfer to the new folders with backups.

- **Manage long-running goals.** `/goal <objective>`, `/goal`, `/goal edit`, `/goal pause`, `/goal resume`, and `/goal clear` use Codex's native goal lifecycle. The ◎ control shows status, token usage, optional budgets, and editing controls. Stop pauses the goal, automatic turns retain the Fusion target, and saved goals stay paused until explicitly resumed.
- **See STEVE's Python.** Compact, expandable cards show submitted Fusion scripts and their running, waiting, or completion state without replacing the code pane as replies stream. Scripts appear when submitted, rather than token by token.
- **Sign in with X / Grok.** Select Grok / X on the sign-in card or in the account menu and approve access in your browser. STEVE completes sign-in automatically; there is no need to copy the code the browser may show for Grok Build. A separate device-code flow is also available.
- **Choose Grok models and effort.** Available models, supported reasoning levels, and defaults come from xAI's live catalog. STEVE remembers your selected model and effort per model.
- **Use STEVE's Fusion tools with Grok.** The integration supports Python operations, design queries, image inputs, streaming, steering, and saved chat image lookup through the bundled runtime.
- **Keep provider settings separate.** Each provider has its own sign-in, conversation history, and preferences. Switching is disabled during a task or sign-in.
- **Run a local model with Ollama.** No sign-in is required. STEVE discovers downloaded models with tool support, checks their actual context allocation, and supports images when the model has vision. Local setup guidance includes a small Gemma configuration for modest GPUs. Web search is unavailable with this provider.

xAI determines account eligibility and access. No API key or separate STEVE account is required. Browser sign-in is user-confirmed on Windows, and automated checks cover the runtime/tool loop, resumed conversations, and effort forwarding. Live Grok modeling and macOS sign-in still need verification; see [verification status](https://github.com/10-X-eng/STEVE/blob/main/docs/VERIFICATION.md).

## Update or install

- **Windows x64:** download **STEVE-0.3.0-windows-x64.zip**, extract the whole ZIP, close Fusion, then run **Install STEVE.exe**.
- **macOS (Apple silicon):** download **STEVE-0.3.0-macos-arm64.zip**, extract it, quit Fusion, then run **Install STEVE.command** through Terminal (type `bash `, drag the file in, press Return) or allow it under System Settings > Privacy & Security.

Download this transition release manually: older installations cannot discover it after the repository rename. The installer replaces the previous managed add-in folder with STEVE. On first run, STEVE transfers sign-ins, chat history, goals, preferences, and cached images into its new data folder, retaining a backup. Future updates appear in STEVE's account menu.

Each ZIP includes the Codex runtime, installer, and installation guide. GitHub's **Source code** downloads do not include the runtime or installer. STEVE downloads updates on request and does not replace files while Fusion is running.

These are unsigned previews. Both platform packages must pass automated build and installation verification before publication. Each package's SHA-256 checksum is included as a separate release asset.
