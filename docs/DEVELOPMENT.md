# Developing STEVE

STEVE is a Fusion add-in for Windows x64 and macOS on Apple silicon, with ChatGPT sign-in, streaming chat, persistent history, and a general Python execution bridge into Fusion's installed APIs.

## Release updates

`STEVE.manifest` owns the STEVE version; `steve.version` supplies it to the panel, Codex handshake, and packaging scripts. Coordinate a new, unused version with the upstream maintainer and update the release notes and installation examples before the next upstream release. Only `10-X-eng/STEVE` publishes a release after verified builds on its `main`; forks build artifacts without publishing from `main`.

`steve.updates` checks the public [GitHub releases API](https://docs.github.com/en/rest/releases/releases) in a separate worker on add-in startup and every 12 hours, plus manual requests. It includes previews, ignores drafts and malformed tags, compares numeric versions, and requires the current platform's ZIP and checksum assets. It sends no ChatGPT credentials, conversations, or design data. HTTP failures update only the menu status and never cancel a model turn.

`steve.downloads` streams a requested package to a unique partial file in Downloads, then verifies the published SHA-256 before renaming it to ZIP. Windows uses [SHGetKnownFolderPath](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath) for redirected Downloads folders; macOS uses the current user's Downloads folder. Closing STEVE cancels pending work and removes partial files when the download worker exits. Completed downloads and existing files are preserved. **Download only** saves the verified ZIP without installing. **Update STEVE**, after confirmation, downloads and verifies the package, stages it outside the running add-in, and launches a detached installer that waits for Fusion to quit before replacing a managed STEVE installation. The installer retains a backup; restart Fusion after installation completes. Restart STEVE in the STEVE logo menu restarts only the conversation runtime, not the Fusion add-in. Failed installations are reported on the next add-in start; verify the new version in the STEVE logo menu after reopening Fusion.

## Independent Codex updates

`steve.runtime_updates` checks OpenAI's latest stable release and the host's complete app-server asset. It requires the official asset URL, uploaded status, bounded size, and SHA-256 digest from GitHub. Downloads and extraction are bounded, archive links and escaping paths are rejected, and package version/target/layout are verified. A temporary isolated runtime checks initialization, model discovery, thread creation with STEVE's tools/Code Mode, and Codex goal reads without credentials or inference.

A successful update moves into a unique directory under the user's `runtimes` folder and atomically replaces `active.json`. Running processes keep their original files. Selection applies on the next transport startup, including provider changes or reconnects. The STEVE logo menu’s **Restart STEVE** action closes and reconnects the owned conversation transport, refreshes models, and resumes the current saved thread while leaving Fusion and the add-in running. Active/queued tasks, jobs, sign-ins, and downloads block this action. A restart verifies that the pending version actually activated, and the updater reads back its saved selection before reporting readiness. It shows the running version separately from the pending version. Recovery clears the selection for the next start; existing runtime directories are retained. Invalid or missing selections use the bundled runtime. Chats and credentials stay in their existing provider homes.

`transport.VERSION` specifies only the reproducible package-build baseline. Runtime validation requires internally consistent metadata and supporting files, not equality with that constant. Build downloads have version-specific cache paths and stage a complete package before replacing the development runtime; the previous directory is preserved under `.cache`. Stop the local add-in before replacing a development runtime. Installed users use the background updater instead.

## Grok provider

Model discovery reads `capabilities.reasoning_effort` and `capabilities.default_reasoning_effort` from xAI's [model catalog](https://docs.x.ai/developers/rest-api-reference/inference/models). Only levels understood by the bundled runtime are offered; models without capability metadata keep the provider default. Selected effort travels through Codex's turn settings into Responses `reasoning.effort`, including tool continuations and resumed conversations.

`grok_auth.py` implements browser authorization-code login with PKCE and state validation, cancellable device polling, refresh rotation, userinfo lookup, and revocation. Endpoints and scopes come from [xAI's OpenID metadata](https://auth.x.ai/.well-known/openid-configuration). It uses the public Grok CLI client ID. Credentials live only in STEVE's `grok` folder: Windows uses current-user DPAPI; macOS uses a private directory and owner-only file. No OAuth tokens reach the UI, Codex config, or debug logs.

`GrokTransport` adapts account/model RPCs and uses Codex's [custom Responses provider configuration](https://learn.chatgpt.com/docs/config-file/config-reference). Its random-path loopback gateway forwards only Responses requests to xAI, resolves tokens at request time, retries an authentication failure once after refresh, streams without buffering a full response, and removes the unsupported replayed reasoning items and `external_web_access` search flag. Grok receives STEVE's ordinary Python function tools rather than Code Mode wrappers. Images, steering, tool results, and histories still use the existing Codex protocol.

ChatGPT keeps its existing data paths. Grok has a separate `grok-runtime` home and explicit history provider filter; selection and model preferences are remembered separately. A provider change cannot interrupt a running task, and stale events from the closed runtime are ignored. Tests use fake xAI responses, not real credentials or paid inference. `test_grok_runtime.py` exercises the actual bundled runtime through a tool call, response, history listing, process restart, and continuation.

## Local setup

`OllamaTransport` connects the bundled runtime directly to Ollama's [Responses API](https://docs.ollama.com/api/openai-compatibility). The default endpoint is `http://127.0.0.1:11434`. **Server** in the panel saves a host, optional port, optional path or query, and optional API key under the `ollama` data folder. The path is a prefix on both discovery and `/v1`. The query is appended to discovery requests and sent to Codex as `query_params`. The key is stored in the system credential store and passed to the conversation runtime as `STEVE_OLLAMA_API_KEY`; thread config records only that variable name. There is no web search and no Code Mode for this provider. Discovery uses `/api/version`, `/api/tags`, and `/api/show`; cloud and non-tool models are excluded. Before a turn, `/api/generate` loads the selected model with its saved settings and `/api/ps` supplies the actual context allocation. The adapter recognizes a reused parent runner for configured model aliases, caps context at the model's reported limit, and reserves at least 2048 tokens or 25% for output. A model/context change refreshes the runtime's thread configuration. Vision checks also apply to steering and tool-delivered images. All provider files use the platform's STEVE data directory, with an `ollama-runtime` home and `ollama` preferences folder.

Developer prerequisites: Python 3.13+, Node.js for the renderer checks, and Fusion for integration testing. End users do not need Python, Node.js, or a separate Codex installation.

```bash
python3 scripts/fetch_runtime.py
python3 -m unittest discover -s tests -v
node tests/test_panel.cjs
node tests/test_images.cjs
python3 scripts/smoke_runtime.py
python3 scripts/build_package.py
python3 scripts/verify_package.py
python3 scripts/audit_portability.py
```

Use `py -3.13` in place of `python3` on Windows. Every script defaults to the platform it runs on: the runtime download, package name, installer, and verification follow `host_target()` in `steve/transport.py`. `fetch_runtime.py --target` downloads another platform's runtime for inspection; packages are built and verified on their own platform.

The reproducible build baseline is Codex 0.155.1 per platform (`x86_64-pc-windows-msvc` and `aarch64-apple-darwin`) and verified with SHA-256. Keep the entire package, including the Code Mode host, resources, and package metadata. `steve-runtime.json` records the version and target, and startup refuses a runtime built for another platform. Code Mode is explicitly enabled, with `core`, `conversation`, and `view` kept as direct-call namespaces.

The smoke test uses `.cache/smoke-home`; it checks startup, account reads, model discovery, thread creation, and shutdown without signing in or making an inference request. It does not prove that a ChatGPT conversation works.

Windows builds require the .NET Framework C# compiler and produce `Install STEVE.exe`. macOS builds copy the `Install STEVE.command` shell installer, which performs the same checksum verification, staging, backup, and marker steps and restores executable bits on the runtime. The generated zip contains the installer and the complete payload, with Unix permission bits recorded for Finder. Existing output folders must be renamed before rebuilding. Installer tests run when the package exists and write only to disposable `.cache/installer-tests` fixtures.

`verify_package.py` checks the zip digest, extracts it under `.cache/package-verification`, runs the platform's installer in its test mode into that fixture, compares installed files with the source and checksums, and starts the installed runtime. It never installs into the actual Fusion add-in directory or signs in. The fixture remains available for inspection.

Toolbar PNGs are committed assets. To change the mark, update the SVG and `scripts/generate_icons.py`, then run the latter with Pillow installed.

## GitHub builds and releases

The **Build and release** workflow runs on pushes to `main`, pull requests, and manual dispatch. A Windows job compiles `Install STEVE.exe` and a macOS (Apple silicon) job packages `Install STEVE.command`. Each downloads its checksum-verified runtime baseline, builds and audits the ZIP, runs Python/JavaScript and installer checks, and verifies an installation of the complete package. Successful builds upload both ZIPs and SHA-256 files as Actions artifacts.

Releases are automatic only in `10-X-eng/STEVE`: push a new version to its `main`, and after the build passes the publishing job creates its version tag and a GitHub preview release with the Windows and macOS assets. Fork `main` pushes build artifacts but do not publish releases. Pushes with an already-published version still run checks but skip publishing. Pull requests never publish. The job checks that `main` still matches the tested commit and never moves an existing tag. Publishing uses GitHub's built-in token; no personal token secret is needed. **Run workflow** on upstream `main` is also available to retry a build.

Before the next release, update the add-in and package versions, related installer/documentation version strings, and `docs/RELEASE_NOTES.md`. A version already published must not be reused.

Upstream Codex binaries may contain their vendor's build paths. The portability audit accepts those only when the entire file matches the checksum-pinned upstream archive for the package's target, read from its `steve-runtime.json`. STEVE's own files and modified vendor binaries receive no exception.

## Fusion development loop

The core behavior prompt lives in `steve/tool_protocol.py`. Python calling conventions live in the tool descriptions; CAM discovery, Data Panel search, and cloud insertion recipes are returned on demand by `fusion_api_help` at the API paths named in the prompt. Keep recovery instructions with tool errors rather than repeating them in the core prompt. Start a new conversation after changing tool descriptions so the session uses the current declarations.

1. Open **Scripts and Add-ins** in Fusion.
2. Add the local `addin/STEVE` folder, select STEVE, and run it.
3. Open STEVE from the **Quick Access toolbar** at the top of Fusion in any workspace (also available under Design **Utilities > Add-ins** and command search).
4. Stop the add-in before editing/reloading it. Use Fusion's Edit/Debug integration with VS Code when needed.

The production runtime home is `%LOCALAPPDATA%\STEVE` on Windows and `~/Library/Application Support/STEVE` on macOS. Codex owns credentials under its `codex` subdirectory. Do not copy authentication from another Codex installation. STEVE clears ambient API credentials from the child environment.

STEVE validates the saved ChatGPT account on startup and before opening a new login. It checks again when the palette reopens or regains focus, handles account-change notifications, and polls while sign-in is pending. Browser login uses the runtime's local completion page instead of the hosted ChatGPT desktop handoff. Refresh the account after successful login.

`thread_start_params` is shared by the controller and runtime/package checks. Initialization enables `experimentalApi` for `thread/start.dynamicTools`. The runtime validates and persists the five Fusion tools and two chat-image tools at thread creation. `thread/resume` restores those declarations; it does not accept replacement tools. Start a new chat when changing tool definitions in this prototype. See [execution details](FUSION_EXECUTION.md).

Before launching Codex, startup checks the bundled executable, Code Mode host, resources, and version metadata. Missing or incompatible files produce a setup card with STEVE repair instructions and the official Codex download/setup page.

The embedded page paints its own opaque backgrounds in `panel/fusion.css` because Fusion's host styling may otherwise expose a light body background. Stop and Run STEVE to reload changes; the panel's versioned stylesheet/script URLs also invalidate cached UI assets. Fully restart Fusion only if it retains stale modules.

Streaming snapshots are coalesced with `requestAnimationFrame`. Message articles and unchanged Markdown nodes remain mounted; token appends update existing text nodes. Controls render only when their state changes. Scrolling follows replies only when the reader is already near the bottom. `node tests/test_panel.cjs` checks incremental tree updates and snapshot batching without a browser. `node tests/test_streaming.cjs` adds real DOM, selection, scrolling, and mutation-count checks when Playwright and Edge are available. For manual browser testing, run it with `--fixture`, serve the repository root, and open `/.cache/streaming-check.html`.

With Playwright and Edge available, `node tests/test_menus.cjs` checks the STEVE settings and account menus: keyboard focus, Escape/outside dismissal, mutual exclusion with history, moved bridge actions, busy guards, and layouts from 320 to 760 pixels wide. The STEVE logo opens app settings; the person icon opens provider and supplier connections. Updates and Diagnostics expand without replacing the conversation.

Jobs use `thread/goal/set|get|clear` and the corresponding notifications. STEVE enables `features.goals`, injects the user's objective and pinned context while paused, configures the selected model/effort, then activates the job; Codex starts and continues turns. There is no STEVE retry loop. Stop pauses before interrupting, and job controls remain usable between turns. History loads pause persisted active jobs before `thread/resume`. In-memory Fusion bindings preserve document objects and selections across pauses and chat switches; after restart, explicit Resume captures the active document. Replacement clears the previous job first because runtime 0.153.4 retains accounting on an objective-only update. `tests/test_job_runtime.py` exercises the real runtime against a local inference fixture, including Codex's native goal tools, budgets, continuation, cancellation, replacement, persistence, and inactive history restoration.

Images use native Codex image inputs. File attachments use the browser picker. Image paste is read from the operating-system clipboard through STEVE's palette bridge: an isolated Windows STA helper reads PNG/bitmap formats, and a macOS AppKit helper reads PNG/TIFF. The helpers use built-in OS runtimes, run on a worker, and never read clipboard text or modify clipboard contents. Completion reaches the palette through Fusion's main-thread custom event, separately from streaming state. Both paths use the same browser preparation and attachment previews: at most four images, 2,048 pixels on the longest edge, and 1 MiB per result. Plain text paste remains native. Temporary clipboard files are deleted immediately after reading; pixels are not logged. Python validates the bounded PNG/JPEG/WebP payloads and sends native `image` inputs through `turn/start` or `turn/steer`. The image cache is the `images` folder under the runtime home, named by content hash. Snapshots contain only image IDs and labels; the palette requests bytes separately through `imageAssets` and retains the existing image nodes while text streams. Assets can only be requested for messages in the current conversation. History never fetches remote URLs or reads arbitrary localImage paths for preview. Failed submissions expose **Reuse message**, without automatically repeating a potentially delivered operation.

Image recall uses a durable per-conversation index under `images/chats`, with hashed conversation filenames and content-addressed image files. Only confirmed attachment/steering deliveries and delivered viewport captures enter the index. `list_chat_images` returns up to 20 metadata entries per page; `view_chat_image` checks membership in the active conversation and reinjects the selected pixels through the existing native image-input path. It cannot select another conversation or arbitrary path. Reopened captures are labeled historical; reopening does not add another catalog entry. Cache integrity is checked against the content hash. Missing or damaged files produce an explicit error, and a cache failure after delivery never changes a successful send into a failed send. Viewport caching preserves the existing 8 MiB capture limit; user attachments remain limited to 1 MiB after preparation. Old unindexed images are not scanned or imported automatically. Start a new conversation once after this update to register the image tools; conversations created with these tools retain them when resumed.

Native Windows bitmap/PNG conversion and image-paste bridge/race checks pass automated tests. Actual clipboard paste inside Fusion, macOS clipboard conversion, and the image viewer still require live verification. The JavaScript tests exercise paste dispatch, draft lifetime, preparation errors, async submit races, and asset caching using stand-ins; they do not prove embedded browser clipboard or canvas behavior.

Codex persists new conversations under STEVE's runtime home. The history drawer uses `thread/list` with the STEVE workspace and supported interactive sources, followed by `thread/resume` to restore messages and model context. It loads 30 conversations at a time and searches the loaded titles locally. Closing/reopening the panel preserves the current conversation. Restarting the add-in or reconnecting opens a blank chat; saved conversations remain available through history. ChatGPT sign-in is persisted by Codex. Sessions created by earlier ephemeral builds are not recoverable after their runtime exits. Local history belongs to the operating-system user, not a separate STEVE account or cloud synchronization service.

All installed assets are resolved relative to the add-in. Runtime data uses the current user's `LOCALAPPDATA` or `~/Library/Application Support`, and the installers use Windows' ApplicationData special folder or `$HOME`. Compiler discovery uses PATH or SystemRoot; no drive letter or developer profile is assumed. The package build audits source and the complete zip, including binaries, for the current checkout/profile paths, literal absolute paths in text, and local debugger/bytecode artifacts.

## Structure

For diagnostics, open **STEVE logo → Diagnostics** and enable **Debug logging**. It defaults off and remembers the choice in `debug.json` under the runtime home. **Open logs folder** opens the `logs` folder there in Explorer or Finder; `steve-debug.jsonl` records UTC timestamps, correlated tool requests with generated code, results/errors, duration, transport request timing, and Codex stderr. Rotation keeps the current file and three backups at approximately 2 MiB each. Disabling logging stops new entries and preserves existing files. Authentication RPC payloads are excluded; common credential patterns in diagnostic text are redacted. Code and tool results may contain design details, so review logs before sharing. Logging is local and never automatically uploaded. This toggle controls STEVE's diagnostics, not Codex's existing session history.

- `addin/STEVE/STEVE.py`: Fusion lifecycle, toolbar, palette, custom-event bridge.
- `addin/STEVE/steve/transport.py`: subprocess lifecycle and JSON-RPC.
- `addin/STEVE/steve/controller.py`: account, model, chat, and cancellation state.
- `addin/STEVE/steve/tool_protocol.py`: general Fusion tool declarations, validation, and instructions.
- `addin/STEVE/steve/fusion_tools.py`: main-thread document inspection, API help, and command execution.
- `addin/STEVE/steve/python_runner.py`: generated script entry point, captured output, errors, and cooperative cancellation.
- `addin/STEVE/panel/`: local HTML/CSS/JavaScript interface, with no runtime web dependencies.
- `scripts/installer/Install.cs` and `scripts/installer/Install STEVE.command`: per-user Windows and macOS installers; both validate files before installation and preserve previous versions.
- `scripts/steve_package.py`: package names, installer names, and test-mode installer commands shared by build, verification, and tests.

Codex I/O runs on worker threads. The only Fusion call from those workers is `fireCustomEvent`; Fusion API work and panel updates run in the custom event handler on Fusion's main thread. Palettes are recreated after workspace changes when visible.

## Visual preview

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory addin/STEVE/panel
```

Open `http://127.0.0.1:8765/?preview=welcome` or `?preview=chat`. These pages display an explicit design-preview banner and use sample content. The sign-in button in preview mode only changes the sample UI; it never authenticates. The actual Fusion palette has no preview query parameter.

## macOS notes

Fusion on macOS runs add-ins with its bundled Python (3.14 in Fusion 2705) and renders palettes with Qt WebEngine, so the panel code is shared with Windows; only the paste hint switches to ⌘V. The add-in manifest declares `windows|mac`. Codex runs as a child process in its own process group; on shutdown STEVE closes its stdin, waits briefly, then kills the group so the Code Mode host cannot linger. OpenAI signs and notarizes the macOS Codex binaries, so Gatekeeper accepts the bundled runtime after a browser download; only the unsigned installer script needs Terminal or a Privacy & Security approval. Codex keeps sign-in in `auth.json` under the runtime home on both platforms. `Open logs folder` uses Finder through `open`.

## Official references

- [Fusion add-in creation and manifests](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/WritingDebugging_UM.htm)
- [Fusion palettes and their JavaScript bridge](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Palettes_UM.htm)
- [Fusion threading and custom events](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Threading_UM.htm)
- [Fusion Python debugging](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/PythonSpecific_UM.htm)
- [Codex app-server protocol](https://learn.chatgpt.com/docs/app-server)

Current Autodesk docs and the installed Fusion API were inspected on September 19, 2026. Consult the current runtime's protocol when changing the Codex adapter.
