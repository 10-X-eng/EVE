# Developing EVE

EVE is a Windows x64 Fusion add-in with ChatGPT sign-in, streaming chat, persistent history, and a general Python execution bridge into Fusion's installed APIs.

## Local setup

Developer prerequisites: Python 3.13+, Node.js for the renderer checks, and Fusion for integration testing. End users do not need Python, Node.js, or a separate Codex installation.

```powershell
py -3.13 scripts/fetch_runtime.py
py -3.13 -m unittest discover -s tests -v
node tests/test_panel.cjs
node tests/test_images.cjs
py -3.13 scripts/smoke_runtime.py
py -3.13 scripts/build_package.py
py -3.13 scripts/verify_package.py
py -3.13 scripts/audit_portability.py
```

The runtime download is pinned to Codex 0.153.4 and verified with SHA-256. Keep the entire package, including `codex-code-mode-host.exe`, resources, and package metadata. Code Mode is explicitly enabled, with `core`, `conversation`, and `view` kept as direct-call namespaces.

The smoke test uses `.cache/smoke-home`; it checks startup, account reads, model discovery, thread creation, and shutdown without signing in or making an inference request. It does not prove that a ChatGPT conversation works.

Builds require the Windows .NET Framework C# compiler. The generated zip contains a GUI installer and the complete payload. Existing output folders must be renamed before rebuilding. Installer tests run when the package exists and write only to disposable `.cache/installer-tests` fixtures.

`verify_package.py` checks the zip digest, extracts it under `.cache/package-verification`, runs the complete installer payload into that fixture, compares installed files with the source and checksums, and starts the installed runtime. It never installs into the actual Fusion add-in directory or signs in. The fixture remains available for inspection.

Toolbar PNGs are committed assets. To change the mark, update the SVG and `scripts/generate_icons.py`, then run the latter with Pillow installed.

## GitHub builds and releases

The **Windows build and release** workflow runs on pushes to `main`, pull requests, and manual dispatch. It downloads the checksum-pinned runtime, compiles `Install EVE.exe`, builds and audits the ZIP, runs Python/JavaScript and installer checks, and verifies an installation of the complete package. Successful builds upload the ZIP and SHA-256 file as an Actions artifact.

Releases are automatic: push a new version to `main`, and after the build passes the publishing job creates its version tag and a GitHub preview release with both assets. Pushes with an already-published version still run checks but skip publishing. Pull requests never publish. The job checks that `main` still matches the tested commit and never moves an existing tag. Publishing uses GitHub's built-in token; no personal token secret is needed. **Run workflow** on `main` is also available to retry a build.

Before the next release, update the add-in and package versions, related installer/documentation version strings, and `docs/RELEASE_NOTES.md`. A version already published must not be reused.

Upstream Codex binaries may contain their vendor's build paths. The portability audit accepts those only when the entire binary matches the checksum-pinned upstream archive. EVE's own files and modified vendor binaries receive no exception.

## Fusion development loop

1. Open **Scripts and Add-ins** in Fusion.
2. Add the local `addin/EVE` folder, select EVE, and run it.
3. Open EVE from the **Quick Access toolbar** at the top of Fusion in any workspace (also available under Design **Utilities > Add-ins** and command search).
4. Stop the add-in before editing/reloading it. Use Fusion's Edit/Debug integration with VS Code when needed.

The production runtime home is `%LOCALAPPDATA%\EVE`. Codex owns credentials under its `codex` subdirectory. Do not copy authentication from another Codex installation. EVE clears ambient API credentials from the child environment.

EVE validates the saved ChatGPT account on startup and before opening a new login. It checks again when the palette reopens or regains focus, handles account-change notifications, and polls while sign-in is pending. Browser login uses the runtime's local completion page instead of the hosted ChatGPT desktop handoff. Refresh the account after successful login.

`thread_start_params` is shared by the controller and runtime/package checks. Initialization enables `experimentalApi` for `thread/start.dynamicTools`. The pinned runtime validates and persists the five Fusion tools at thread creation. `thread/resume` restores those declarations; it does not accept replacement tools. Start a new chat when changing tool definitions in this prototype. See [execution details](FUSION_EXECUTION.md).

Before launching Codex, startup checks the bundled executable, Code Mode host, resources, and version metadata. Missing or incompatible files produce a setup card with EVE repair instructions and the official Codex download/setup page.

The embedded page paints its own opaque backgrounds in `panel/fusion.css` because Fusion's host styling may otherwise expose a light body background. Stop and Run EVE to reload changes; the panel's versioned stylesheet/script URLs also invalidate cached UI assets. Fully restart Fusion only if it retains stale modules.

Streaming snapshots are coalesced with `requestAnimationFrame`. Message articles and unchanged Markdown nodes remain mounted; token appends update existing text nodes. Controls render only when their state changes. Scrolling follows replies only when the reader is already near the bottom. `node tests/test_panel.cjs` checks incremental tree updates and snapshot batching without a browser. `node tests/test_streaming.cjs` adds real DOM, selection, scrolling, and mutation-count checks when Playwright and Edge are available. For manual browser testing, run it with `--fixture`, serve the repository root, and open `/.cache/streaming-check.html`.

Images use native Codex image inputs. The browser reads image files from the user's [paste event](https://developer.mozilla.org/en-US/docs/Web/API/Element/paste_event) using [getAsFile](https://developer.mozilla.org/en-US/docs/Web/API/DataTransferItem/getAsFile), or from a file picker. It decodes/re-encodes locally before Send, at most four images, 2,048 pixels on the longest edge, and 1 MiB per result. Python validates the bounded PNG/JPEG/WebP payloads and sends native `image` inputs through `turn/start` or `turn/steer`. The image cache is `%LOCALAPPDATA%\EVE\images`, named by content hash. Snapshots contain only image IDs and labels; the palette requests bytes separately through `imageAssets` and retains the existing image nodes while text streams. Assets can only be requested for messages in the current conversation. History never fetches remote URLs or reads arbitrary localImage paths for preview. Failed submissions expose **Reuse message**, without automatically repeating a potentially delivered operation.

The clipboard and image viewer still require live Fusion verification. The JavaScript tests exercise paste dispatch, draft lifetime, preparation errors, async submit races, and asset caching using stand-ins; they do not prove embedded browser clipboard or canvas behavior.

Codex persists new conversations under EVE's runtime home. The history drawer uses `thread/list` with the EVE workspace and supported interactive sources, followed by `thread/resume` to restore messages and model context. It loads 30 conversations at a time and searches the loaded titles locally. Closing/reopening the panel preserves the current conversation. Restarting the add-in or reconnecting opens a blank chat; saved conversations remain available through history. ChatGPT sign-in is persisted by Codex. Sessions created by earlier ephemeral builds are not recoverable after their runtime exits. Local history belongs to the Windows user, not a separate EVE account or cloud synchronization service.

All installed assets are resolved relative to the add-in. Runtime data uses the current user's `LOCALAPPDATA`, and the installer uses Windows' ApplicationData special folder. Compiler discovery uses PATH or SystemRoot; no drive letter or developer profile is assumed. The package build audits source and the complete zip, including binaries, for the current checkout/profile paths, literal absolute paths in text, and local debugger/bytecode artifacts.

## Structure

For diagnostics, open the account menu and enable **Debug logging**. It defaults off and remembers the choice in `%LOCALAPPDATA%\EVE\debug.json`. **Open logs folder** opens `%LOCALAPPDATA%\EVE\logs`; `eve-debug.jsonl` records UTC timestamps, correlated tool requests with generated code, results/errors, duration, transport request timing, and Codex stderr. Rotation keeps the current file and three backups at approximately 2 MiB each. Disabling logging stops new entries and preserves existing files. Authentication RPC payloads are excluded; common credential patterns in diagnostic text are redacted. Code and tool results may contain design details, so review logs before sharing. Logging is local and never automatically uploaded. This toggle controls EVE's diagnostics, not Codex's existing session history.

- `addin/EVE/EVE.py`: Fusion lifecycle, toolbar, palette, custom-event bridge.
- `addin/EVE/eve/transport.py`: subprocess lifecycle and JSON-RPC.
- `addin/EVE/eve/controller.py`: account, model, chat, and cancellation state.
- `addin/EVE/eve/tool_protocol.py`: general Fusion tool declarations, validation, and instructions.
- `addin/EVE/eve/fusion_tools.py`: main-thread document inspection, API help, and command execution.
- `addin/EVE/eve/python_runner.py`: generated script entry point, captured output, errors, and cooperative cancellation.
- `addin/EVE/panel/`: local HTML/CSS/JavaScript interface, with no runtime web dependencies.
- `scripts/installer/Install.cs`: per-user installer; validates files before installation and preserves previous versions.

Codex I/O runs on worker threads. The only Fusion call from those workers is `fireCustomEvent`; Fusion API work and panel updates run in the custom event handler on Fusion's main thread. Palettes are recreated after workspace changes when visible.

## Visual preview

```powershell
py -3.13 -m http.server 8765 --bind 127.0.0.1 --directory addin/EVE/panel
```

Open `http://127.0.0.1:8765/?preview=welcome` or `?preview=chat`. These pages display an explicit design-preview banner and use sample content. The sign-in button in preview mode only changes the sample UI; it never authenticates. The actual Fusion palette has no preview query parameter.

## Official references

- [Fusion add-in creation and manifests](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/WritingDebugging_UM.htm)
- [Fusion palettes and their JavaScript bridge](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Palettes_UM.htm)
- [Fusion threading and custom events](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Threading_UM.htm)
- [Fusion Python debugging](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/PythonSpecific_UM.htm)
- [Codex app-server protocol](https://learn.chatgpt.com/docs/app-server)

Current Autodesk docs and the installed Fusion API were inspected on September 19, 2026. Consult the pinned runtime's protocol when changing the Codex adapter.
