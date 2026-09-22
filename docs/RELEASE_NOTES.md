# STEVE 0.4.0 — Claude subscriptions and independent Codex updates

Use your Claude subscription in Autodesk Fusion through the official Claude Code client. Select **Claude (experimental)** alongside ChatGPT, Grok / X, and local Ollama.

## What changed

- **Update Codex independently.** The account menu shows the running Codex version, checks OpenAI's latest stable release, and downloads verified updates without waiting for a STEVE release. Downloads run alongside your current task; click **Restart STEVE** in the account menu to activate the update and reopen your chat without restarting Fusion. The bundled runtime remains available for recovery.
- **Refresh OpenAI models.** Refresh the ChatGPT model catalog without resetting your conversation. The packaged Codex baseline is now 0.155.1; newer compatible stable versions can be installed independently.

- **Use your existing Claude sign-in.** Install Claude Code and run `claude auth login` in a terminal outside Fusion. STEVE detects the account automatically and provides installation and sign-in guidance when needed. Credentials stay with Claude Code.
- **See model versions and effort choices.** The picker shows resolved names such as Opus 5.5 and Haiku 4.5, preserves context and usage-credit labels, and exposes supported reasoning levels.
- **Refresh after Claude updates.** The account menu shows the installed Claude Code version. **Check connection** refreshes that version and the model catalog without resetting your chat.
- **Keep STEVE's tools and conversations.** Claude supports Fusion tool calls, streaming, images, steering, saved history, and native goal controls through the existing conversation engine. Signed replay data is isolated by chat.
- **Handle failures clearly.** Interrupted or incomplete responses do not dispatch unfinished tool batches. Claude errors reach the chat, and cancellation stops the owned process. The adapter prevents additional upstream generations within a single model request.

Claude support is experimental. Web search is not connected for this provider; Fusion's installed API documentation remains available. Claude Code is installed separately. Anthropic controls model access, subscription limits, and any usage-credit or extra-usage charges. No API key or separate STEVE account is required.

Live Haiku and Sonnet checks completed tool rounds against a simulated document. Automated checks cover the protocol, images, steering, history, goals, and cancellation. Native Fusion workflows and macOS Claude usage still need live confirmation; see [verification status](https://github.com/10-X-eng/STEVE/blob/main/docs/VERIFICATION.md).

## Update or install

- **Windows x64:** download **STEVE-0.4.0-windows-x64.zip**, extract the whole ZIP, close Fusion, then run **Install STEVE.exe**.
- **macOS (Apple silicon):** download **STEVE-0.4.0-macos-arm64.zip**, extract it, quit Fusion, then run **Install STEVE.command** through Terminal (type `bash `, drag the file in, press Return) or allow it under System Settings > Privacy & Security.

Existing STEVE users can use **Check for updates** once this release is published. The installer preserves saved chats and preferences. Each ZIP includes the conversation runtime, installer, and installation guide. GitHub's **Source code** downloads do not include the runtime or installer.

These are unsigned previews. Both platform packages must pass automated build and installation verification before publication. Each package's SHA-256 checksum is included as a separate release asset.
