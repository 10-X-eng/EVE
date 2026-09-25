# Install STEVE for Autodesk Fusion

STEVE 0.6.1 is a preview for Windows x64 and macOS on Apple silicon. You need Autodesk Fusion and either a ChatGPT account with Codex access, an xAI account with Grok access, a Claude subscription signed into Claude Code, or a local Ollama installation with a compatible downloaded model. Cloud providers and package/model downloads require an internet connection. Each complete package includes Codex; no separate Python, Node.js, API key, or STEVE account is required.

Download the package for your computer from the [STEVE releases page](https://github.com/10-X-eng/STEVE/releases): `STEVE-0.6.1-windows-x64.zip` or `STEVE-0.6.1-macos-arm64.zip`. Use the packaged zip, not GitHub's **Source code** download, which does not include the runtime. If no release is listed, a maintainer must build the package first.

## Install on Windows

1. Right-click the zip and choose **Extract All**. Keep the entire extracted folder together, including `Install STEVE.exe`, `SHA256SUMS`, and the `STEVE` folder.
2. Save your work and close Fusion.
3. Open **Install STEVE.exe** and click **Install STEVE**. Installation is for your current Windows account and does not need administrator access. This preview's installer is unsigned.
4. Open Fusion. Open **Scripts and Add-ins** (Design workspace: **Utilities > Add-ins**), select the **Add-ins** tab, select **STEVE**, and click **Run**. Enable **Run on Startup** if you want STEVE available every time you open Fusion.
5. Click **STEVE** in the **Quick Access toolbar** at the top of Fusion. It is also available through command search.
6. Choose **ChatGPT** or **Grok / X** and sign in, or follow [Claude subscription setup](#claude-subscription-experimental) or [local Ollama setup](#local-ollama). Existing STEVE sign-in is checked automatically.

To verify the download, run `Get-FileHash .\STEVE-0.6.1-windows-x64.zip -Algorithm SHA256` in PowerShell from the download folder and compare it with the accompanying `.zip.sha256` file.

## Install on macOS

1. Double-click the zip to extract it. Keep the extracted folder together, including `Install STEVE.command`, `SHA256SUMS`, and the `STEVE` folder.
2. Save your work and quit Fusion.
3. Open Terminal, type `bash ` (with a trailing space), drag **Install STEVE.command** from Finder into the Terminal window, and press Return. Installation is for your current macOS account and does not need administrator access.
   Double-clicking **Install STEVE.command** also works, but because this preview is not signed, macOS blocks it the first time. Open **System Settings > Privacy & Security**, choose **Open Anyway** next to the message about the installer, and confirm.
4. Open Fusion. Open **Scripts and Add-ins** (Design workspace: **Utilities > Add-ins**), select the **Add-ins** tab, select **STEVE**, and click **Run**. Enable **Run on Startup** if you want STEVE available every time you open Fusion.
5. Click **STEVE** in the **Quick Access toolbar** at the top of Fusion. It is also available through command search.
6. Choose **ChatGPT** or **Grok / X** and sign in, or follow [Claude subscription setup](#claude-subscription-experimental) or [local Ollama setup](#local-ollama). Existing STEVE sign-in is checked automatically.

To verify the download, run `shasum -a 256 STEVE-0.6.1-macos-arm64.zip` in Terminal from the download folder and compare it with the accompanying `.zip.sha256` file. The bundled Codex binaries are signed and notarized by OpenAI.

## First conversation

STEVE includes **Claude (experimental)** through your external Claude Code sign-in; see [Claude setup](#claude-subscription-experimental). **Grok / X** remains available in the **AI provider** selector. Select it, choose **Sign in with X / Grok**, and complete xAI authentication. If the browser shows a code for Grok Build after approval, return to Fusion; STEVE completes sign-in automatically without copying it. You can use **Use a device code instead** if the browser callback cannot reach Fusion. Link your X account in Grok account settings if needed; xAI determines your account's access. Switching providers opens that provider's history and saved model choice and is disabled during a task.

Open a design and start with: **“Inspect this document and summarize its components and parameters.”** Then ask for the change you want, including dimensions and units. Save the design before trying generated operations.

- Select geometry before sending to give STEVE context about “this.”
- Use the paperclip beside Send, or paste into the message box (Ctrl+V on Windows, ⌘V on macOS), to attach reference images.
- Choose a model and effort beside Send. STEVE remembers those preferences.
- Send another message to steer a running task. **Stop** cancels pending work; a long native Fusion operation may need to finish first.
- Use the history icon to reopen saved conversations.

A running task keeps its starting document and selection. If you switch documents, pending Fusion calls wait until you return. There is one active conversation per Fusion instance.

## Claude subscription (experimental)

1. Install the official [Claude Code client](https://code.claude.com/docs/en/setup) for your computer.
2. Open a terminal outside Fusion and run `claude auth login`. Choose your Claude subscription account and finish sign-in there. Use `claude auth status` to verify it.
3. In STEVE, select **Claude (experimental)** under **AI provider**. Existing sign-in is detected automatically. After signing in or changing accounts, click **Check connection**.
4. Choose a model and, where supported, an effort level. Model labels include their resolved version (for example, **Opus 5** or **Haiku 4.5**). The account menu shows your installed **Claude Code version**. After updating Claude Code, **Check connection** refreshes both that version and the model catalog without restarting STEVE. Start with a document inspection before asking for changes.

STEVE uses the unmodified Claude Code client and its own account store. It does not copy credentials or run an embedded sign-in flow. Sign out with `claude auth logout` in a terminal; this affects other apps using that same Claude Code account. STEVE reads the CLI's model picker without starting a generation. Model availability, usage credits, and extra usage remain controlled by Anthropic and your account. [Anthropic's current SDK guidance](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) says `claude -p` and third-party app usage draw from subscription usage limits; this is not unlimited access.

This experimental integration supports STEVE's Fusion tools, streamed replies, images, steering, history, and jobs. Claude web search is not connected yet; installed Fusion API documentation remains available. STEVE uses a conservative 200K conversation window. It keeps Claude conversations and signed replay data under its local `claude-runtime` directory, separate from the other providers; these may contain design information and do not appear in the Claude website's chat history. The transport adapts [Hermes's MIT-licensed Claude subscription client](https://github.com/NousResearch/hermes-plugin-claude-subscription-directsdk); attribution ships with the add-in.

If setup fails, update with `claude update`, verify `claude auth status`, then check the connection again. STEVE searches PATH and the standard native install directory (`~/.local/bin`). For a custom installation, set `STEVE_CLAUDE_COMMAND` to the executable before launching Fusion; `STEVE_CLAUDE_CONFIG_DIR` selects a separately CLI-managed account directory. API keys and alternate Anthropic backend overrides are rejected on this subscription path, with the conflicting variable names shown in the UI. The adapter relies on version-sensitive Claude Code replay behavior; Windows Claude Code 2.1.260 has been exercised locally. Native Fusion and macOS confirmation remain preview checks.

## Local Ollama

1. Install [Ollama](https://ollama.com/download) and start its app. STEVE connects to `http://127.0.0.1:11434` on your computer; no account or API key is needed.
2. Download a model with tool support. For a modest GPU, a starting point is `ollama pull gemma4:e2b-it-qat`. Model quality and speed depend on the model and your hardware.
3. Give the model at least 8K context. To keep the original model unchanged, save a plain-text file named `Modelfile` containing:

   ```text
   FROM gemma4:e2b-it-qat
   PARAMETER num_ctx 8192
   ```

   In the folder containing that file, run `ollama create steve-gemma4:8k -f Modelfile`. This reuses the downloaded weights. The saved setting matters: a temporary context override during model preload does not carry over to Ollama's Responses API.
4. In STEVE, choose **Ollama (local)** under **AI provider**, then select your configured model. Use **Refresh models** in the account menu after downloading or configuring models. **Local setup** opens these instructions.

Only downloaded models that advertise tool calling appear. Models with vision support can receive attachments and viewport images; text-only models cannot. The Ollama provider excludes cloud models and has no web search; STEVE can still query documentation from Fusion's installed API. Fusion's own cloud/data operations and STEVE's update checks can still use the internet.

STEVE checks the allocated context before each turn and reserves space for the reply. Small context allocations produce setup instructions instead of silently truncating the task. Ollama conversations and model preferences are separate from ChatGPT and Grok. Start with small, inspectable tasks; a small local model will not have the same capability as a frontier model.

## Codex updates

Codex can update without a new STEVE release. Under **STEVE logo → Updates**, **Check Codex updates** checks OpenAI's latest stable release for your platform. STEVE also checks automatically on startup and every 12 hours. The menu shows the version currently running.

Choose **Update Codex** to download the complete app-server package into STEVE's local data folder. STEVE verifies OpenAI's SHA-256 digest and tests startup, model discovery, Fusion tool declarations, and Codex's goal protocol before selecting it. This does not sign in or generate a model response. Downloading does not interrupt your current task or overwrite its runtime.

When the menu says the update is ready, finish or pause your task, then click **Restart STEVE** in that same menu. STEVE restarts its conversation engine, reopens your current chat, and refreshes the model catalog. Fusion and the add-in stay open. Saved sign-in, chats, images, and preferences stay in place. **Refresh models** in the ChatGPT account menu can also reload the catalog without resetting your chat. OpenAI controls which models your account can access.

If an updated runtime causes a problem, choose **Use bundled Codex**, then click **Restart STEVE**. The original runtime is preserved. Download failures leave your current runtime selected. These checks cover startup compatibility; they cannot guarantee every behavior of future Codex releases. Independently installed runtimes live in the `runtimes` subdirectory of STEVE's local data folder. Updating a separate Codex CLI or desktop app does not update this copy.

## Update or reload

STEVE checks the public GitHub releases on startup and every 12 hours while running. A notice appears when a newer complete package is available for your platform, including preview releases. Use **Check for updates** under **STEVE logo → Updates** to check immediately, including when you are signed out.

Choose **Update STEVE** and confirm. STEVE downloads the newest complete release for your platform into Downloads, verifies its SHA-256, stages the package, and starts a detached installer. Wait until the menu says **Update queued**, then save your work and quit Fusion. The installer waits for Fusion to exit, checks every packaged file, backs up the managed add-in, and installs the release. Reopen Fusion afterward. Neither Fusion nor your conversation is stopped automatically, and no terminal command is needed. **Download only** saves the verified ZIP without scheduling installation. If the install fails, STEVE reports it when reopened and records details in `pending-updates/STEVE-<version>-<platform>/install-result.txt` under its local data folder. Downloads use unique filenames so existing files are preserved. Network failures do not interrupt your task; retry from the menu.

Automatic installation requires a managed STEVE installation. A source checkout or unmanaged add-in folder must be updated manually. To update manually instead, choose **Download only**, extract the ZIP, close Fusion, and run the included installer as described above.

For the first release under the STEVE name, download the package manually from the releases page. Earlier installations cannot discover this update after the repository rename. Subsequent STEVE releases use the built-in update notice. You can also use **Watch → Custom → Releases** on the GitHub repository for release announcements.

For a packaged update, close Fusion and install the new complete package. The installer preserves the previous managed add-in under `STEVE-install-backups` beside the `AddIns` folder: `%APPDATA%\Autodesk\Autodesk Fusion 360\API` on Windows, `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API` on macOS. When upgrading a previous managed installation, its add-in folder is replaced by `STEVE`. On the first run, STEVE transfers the previous data folder to its new name before opening any accounts or starting Codex. Sign-ins, chat history, jobs, preferences, and cached images are preserved; stored chat paths and provider IDs are updated. An untouched data backup remains beside the new data folder as `STEVE-data-backup-<id>`. Keep enough free disk space for that backup. If both data folders already exist, STEVE stops and keeps both rather than merging or overwriting them. Manual/source installations must be removed from Fusion's add-in list separately; automatic discovery only recognizes previous managed installations.

For a development checkout, use **Stop**, then **Run** in Scripts and Add-ins after source changes. Start a new conversation after tool definitions change.

## Troubleshooting

- **STEVE is not listed:** use the add-in folder selection in Scripts and Add-ins to select the `STEVE` folder under `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns` (Windows) or `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns` (macOS), then Run.
- **macOS says the installer cannot be opened:** run it through Terminal as described above, or allow it under System Settings > Privacy & Security.
- **Installer reports an unmanaged STEVE folder:** preserve or rename your existing manually installed folder before installing. The installer will not overwrite it.
- **Sign-in does not finish:** return to STEVE and choose **Check again**, or use the device-code sign-in option. Use an account with access to the selected provider: Codex access for ChatGPT, or Grok access for xAI.
- **Codex setup needed:** after a Codex update, try **Use bundled Codex**, then **Restart STEVE** in the STEVE logo menu first. If the bundled runtime is damaged, extract and reinstall the complete STEVE package for your platform. Installing Codex separately does not replace STEVE's required bundled files. If STEVE reports that Codex lost its run permission, run the installer again instead of copying the `STEVE` folder by hand.
- **An operation fails:** enable **Debug logging** under **STEVE logo → Diagnostics**, reproduce the problem, then choose **Open logs folder**. Review logs for private design information before sharing them.

STEVE's local sign-in, history, preferences, image cache, and optional logs are under `%LOCALAPPDATA%\STEVE` on Windows and `~/Library/Application Support/STEVE` on macOS. These chats do not sync to the ChatGPT website.

## Uninstall

Close Fusion and remove only the `STEVE` folder under the `AddIns` folder named above. Local account data and history remain under STEVE's data folder; remove that separate folder only if you also want to erase STEVE's saved local data.
