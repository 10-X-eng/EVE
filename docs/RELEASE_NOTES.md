# STEVE 0.8.0 — Shared image gallery and clearer updates

- **What’s new:** a small notice after updating opens these version highlights inside STEVE. Dismiss it once; reopen them anytime from Settings → Updates. Notes work offline.
- Close-up captures of small parts keep the camera outside the assembly instead of placing it inside surrounding geometry. In Design, STEVE can request `isolate: true` to hide other bodies/components for the screenshot and restore visibility afterward. Faces and edges isolate their owning body; occurrence targets retain their subtree's existing visibility. Isolated views do not verify assembly fit.
- **Image gallery:** open the image icon in the top bar to import, search, rename, attach and manage shared references. Existing cached images appear with access off; turn on **Available to STEVE** for cross-conversation lookup. Migration preserves chat history, deduplicates images and never enables them automatically. Removing a gallery entry preserves cached pixels used by chats. Start a new chat after updating to give STEVE the gallery lookup tools; manual Attach works in older chats.
- Update controls explain when a task, job, sign-in or Codex download blocks installation. Confirmation and progress explicitly announce the STEVE restart while Fusion stays open.
- Design guidance defaults to functional parts: establish interfaces, build and measure each part, visually inspect and correct it, then verify the assembly. Basic checks apply with DFM off. This guides model behavior; live design verification remains necessary.
- The maintainer confirmed the Windows 0.7.0 → 0.7.1 in-Fusion update works.

# STEVE 0.7.1 — Cleaner top bar

- Removed the Early Access badge from the top bar.
- Published a patch release for live verification of the in-Fusion updater introduced in 0.7.0.

## Update from 0.7.0 without closing Fusion

In an installed, managed copy of STEVE 0.7.0, open **Settings → Updates → Check for updates**. Wait for 0.7.1 to download, then choose **Update & restart STEVE** and confirm when idle. Fusion should stay open while STEVE restarts. Verify that Settings shows **0.7.1**, the top-bar badge is gone, and your document and conversation remain available.

This release provides the package for that live test; it does not claim the test has already passed. Source checkouts must be updated manually. Versions through 0.6.2 require the packaged installer once before in-Fusion updates are available.

# STEVE 0.7.0 — Redesigned panel, Dream, providers and in-Fusion updates

- **Readable replies:** replies now render tables, links, nested and task lists, and fenced code with syntax highlighting, a language label and **Copy**. Links open in your browser.
- **Fusion steps fold away:** each run of Python steps is one activity block ("Ran 4 steps in Fusion · 1 failed") that stays open while STEVE works and collapses when the reply arrives. Expand a step to read its script or the exception it raised. The transcript no longer fills with code.
- **One status line:** the footer names what STEVE is doing and which tool it is using. The pinned document, the current job and DFM show as chips above the message box instead of separate banners.
- **Simpler navigation:** the gear opens a short Settings list — AI provider, Manufacturing (DFM and RMFG), Updates, Diagnostics — where each row shows its current state and opens its own page. The **+** button beside the message box holds Attach images, Dream and jobs. The header is shorter and the welcome screen fits the docked panel.
- **STEVE Dream (experimental):** generate concept images through ChatGPT's Codex connection, refine them in chat, reuse them as visual references, and save originals to Downloads. Concepts persist in chat history and are available to image lookup tools. Image generation consumes Codex limits and is currently enabled only for ChatGPT.
- **In-Fusion updates:** managed installations download updates automatically. Choose **Update & restart STEVE** to apply when idle, with rollback if startup fails. Users upgrading from 0.6.2 must use the old installer once to receive this updater.
- **Ollama servers:** configure a host, port, URL path/query and optional API key for a shared or private Ollama server.

- **OpenRouter:** choose **OpenRouter (experimental)** and **Sign in with OpenRouter**. OpenRouter creates a key labeled STEVE in your account; STEVE stores it in the macOS Keychain or Windows' per-user encryption. Usage is paid from your OpenRouter credits.
- **Model choice:** models with tool calling and at least 64K context appear grouped by company, with each model's effort levels. **Most popular** is the default.
- **Limits:** web search is unavailable for OpenRouter, and text-only models cannot receive images. Tool-calling quality varies by model. Live OpenRouter sign-in and inference still need verification; see [verification status](VERIFICATION.md).

## Install or upgrade to 0.7.0

Download the complete platform ZIP from [STEVE Releases](https://github.com/10-X-eng/STEVE/releases/tag/v0.7.0): **STEVE-0.7.0-windows-x64.zip** or **STEVE-0.7.0-macos-arm64.zip**. Extract it, close Fusion, and run the included installer. This one-time manual installation gives 0.6.2 users the new in-Fusion updater. Chats and preferences are retained.

Dream and the redesigned panel passed automated browser checks. Live image generation and refinement succeeded with Codex; native Fusion appearance and live macOS verification remain user checks. See [verification status](VERIFICATION.md) for provider and updater limits.

# STEVE 0.6.2 — RMFG checkout and simpler settings

This update brings sheet-metal checks, quotes and cart preparation into the conversation, and makes STEVE's settings easier to find.

## Changes

- **Simpler menus:** click the STEVE logo for Design for manufacturing, Updates, Diagnostics and Restart STEVE. The person icon holds AI provider and RMFG connections.
- **Automatic RMFG checks:** with DFM enabled and RMFG connected, STEVE uploads the scoped part snapshot without a separate upload button. It reuses established material and thickness requirements, checks supplier findings, and rechecks changed geometry.
- **Quotes and checkout:** ask STEVE to quote quantities of one or more checked parts and prepare a cart. The new `rmfg_checkout` tool validates snapshots, materials and quantities, then shows **Open checkout**. Review delivery and final pricing and pay on RMFG; STEVE does not submit payments.
- **Remembered RMFG connection:** startup restores the saved connection and refreshes expired access tokens. Connect reuses an existing login. Older DFM-only connections have a separate **Enable quotes & checkout** action for the additional permissions.
- **Additional DFM evidence:** live Fusion fixtures cover multiple cavities and independent openings, with no changes to inspected bodies.

**Start a new chat with + after updating to use the new cart tool.** Existing chats retain their original tool definitions and remain available in history.

## Validation and scope

Connection persistence, token refresh, automatic upload, quote/cart validation, retry handling, stale snapshots and menu interactions have automated coverage. Windows and macOS CI build, install and verify complete packages before publication. New-chat cart-tool availability has been confirmed in local Windows Fusion.

Quote/cart behavior is tested against controlled responses and RMFG's current API contract; a live supplier checkout has not been completed. **DFM remains experimental.** RMFG export supports one solid body per leaf component; multiple separately checked parts can share a cart. Material/process qualification, slicer validation and live macOS DFM remain open.

See [machine definitions](https://github.com/10-X-eng/STEVE/blob/main/docs/MACHINES.md), [evaluation evidence](https://github.com/10-X-eng/STEVE/blob/main/docs/DFM_EVALUATION.md), and [remaining qualification](https://github.com/10-X-eng/STEVE/blob/main/docs/DFM_READINESS.md).

## Update or install

Open **Settings (⚙) → Updates → Check for updates**, then choose **Update STEVE**. Save your work and quit Fusion when prompted. Chats and preferences are retained.

- **Windows x64:** extract **STEVE-0.6.2-windows-x64.zip** and run **Install STEVE.exe**.
- **macOS (Apple silicon):** extract **STEVE-0.6.2-macos-arm64.zip** and run **Install STEVE.command** through Terminal (`bash ` followed by dragging the file into the window).

Download the complete platform ZIP rather than GitHub's source archive. Packages remain unsigned previews. Codex updates independently of STEVE.
