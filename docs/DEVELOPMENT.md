# Developing EVE

EVE is a Fusion add-in for Windows x64 and macOS on Apple silicon, with ChatGPT sign-in, streaming chat, persistent history, and a general Python execution bridge into Fusion's installed APIs.

## Local setup

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

Use `py -3.13` in place of `python3` on Windows. Every script defaults to the platform it runs on: the runtime download, package name, installer, and verification follow `host_target()` in `eve/transport.py`. `fetch_runtime.py --target` downloads another platform's runtime for inspection; packages are built and verified on their own platform.

The runtime download is pinned to Codex 0.153.4 per platform (`x86_64-pc-windows-msvc` and `aarch64-apple-darwin`) and verified with SHA-256. Keep the entire package, including the Code Mode host, resources, and package metadata. `eve-runtime.json` records the version and target, and startup refuses a runtime built for another platform. Code Mode is explicitly enabled, with `core`, `conversation`, and `view` kept as direct-call namespaces.

The smoke test uses `.cache/smoke-home`; it checks startup, account reads, model discovery, thread creation, and shutdown without signing in or making an inference request. It does not prove that a ChatGPT conversation works.

Windows builds require the .NET Framework C# compiler and produce `Install EVE.exe`. macOS builds copy the `Install EVE.command` shell installer, which performs the same checksum verification, staging, backup, and marker steps and restores executable bits on the runtime. The generated zip contains the installer and the complete payload, with Unix permission bits recorded for Finder. Existing output folders must be renamed before rebuilding. Installer tests run when the package exists and write only to disposable `.cache/installer-tests` fixtures.

`verify_package.py` checks the zip digest, extracts it under `.cache/package-verification`, runs the platform's installer in its test mode into that fixture, compares installed files with the source and checksums, and starts the installed runtime. It never installs into the actual Fusion add-in directory or signs in. The fixture remains available for inspection.

Toolbar PNGs are committed assets. To change the mark, update the SVG and `scripts/generate_icons.py`, then run the latter with Pillow installed.

## GitHub builds and releases

The **Build and release** workflow runs on pushes to `main`, pull requests, and manual dispatch. A Windows job compiles `Install EVE.exe` and a macOS (Apple silicon) job packages `Install EVE.command`. Each downloads its checksum-pinned runtime, builds and audits the ZIP, runs Python/JavaScript and installer checks, and verifies an installation of the complete package. Successful builds upload both ZIPs and SHA-256 files as Actions artifacts.

Releases are automatic: push a new version to `main`, and after the build passes the publishing job creates its version tag and a GitHub preview release with the Windows and macOS assets. Pushes with an already-published version still run checks but skip publishing. Pull requests never publish. The job checks that `main` still matches the tested commit and never moves an existing tag. Publishing uses GitHub's built-in token; no personal token secret is needed. **Run workflow** on `main` is also available to retry a build.

Before the next release, update the add-in and package versions, related installer/documentation version strings, and `docs/RELEASE_NOTES.md`. A version already published must not be reused.

Upstream Codex binaries may contain their vendor's build paths. The portability audit accepts those only when the entire file matches the checksum-pinned upstream archive for the package's target, read from its `eve-runtime.json`. EVE's own files and modified vendor binaries receive no exception.

## Fusion development loop

1. Open **Scripts and Add-ins** in Fusion.
2. Add the local `addin/EVE` folder, select EVE, and run it.
3. Open EVE from the **Quick Access toolbar** at the top of Fusion in any workspace (also available under Design **Utilities > Add-ins** and command search).
4. Stop the add-in before editing/reloading it. Use Fusion's Edit/Debug integration with VS Code when needed.

The production runtime home is `%LOCALAPPDATA%\EVE` on Windows and `~/Library/Application Support/EVE` on macOS. Codex owns credentials under its `codex` subdirectory. Do not copy authentication from another Codex installation. EVE clears ambient API credentials from the child environment.

EVE validates the saved ChatGPT account on startup and before opening a new login. It checks again when the palette reopens or regains focus, handles account-change notifications, and polls while sign-in is pending. Browser login uses the runtime's local completion page instead of the hosted ChatGPT desktop handoff. Refresh the account after successful login.

`thread_start_params` is shared by the controller and runtime/package checks. Initialization enables `experimentalApi` for `thread/start.dynamicTools`. The pinned runtime validates and persists the five Fusion tools at thread creation. `thread/resume` restores those declarations; it does not accept replacement tools. Start a new chat when changing tool definitions in this prototype. See [execution details](FUSION_EXECUTION.md).

Before launching Codex, startup checks the bundled executable, Code Mode host, resources, and version metadata. Missing or incompatible files produce a setup card with EVE repair instructions and the official Codex download/setup page.

The embedded page paints its own opaque backgrounds in `panel/fusion.css` because Fusion's host styling may otherwise expose a light body background. Stop and Run EVE to reload changes; the panel's versioned stylesheet/script URLs also invalidate cached UI assets. Fully restart Fusion only if it retains stale modules.

Streaming snapshots are coalesced with `requestAnimationFrame`. Message articles and unchanged Markdown nodes remain mounted; token appends update existing text nodes. Controls render only when their state changes. Scrolling follows replies only when the reader is already near the bottom. `node tests/test_panel.cjs` checks incremental tree updates and snapshot batching without a browser. `node tests/test_streaming.cjs` adds real DOM, selection, scrolling, and mutation-count checks when Playwright and Edge are available. For manual browser testing, run it with `--fixture`, serve the repository root, and open `/.cache/streaming-check.html`.

Images use native Codex image inputs. The browser reads image files from the user's [paste event](https://developer.mozilla.org/en-US/docs/Web/API/Element/paste_event) using [getAsFile](https://developer.mozilla.org/en-US/docs/Web/API/DataTransferItem/getAsFile), or from a file picker. It decodes/re-encodes locally before Send, at most four images, 2,048 pixels on the longest edge, and 1 MiB per result. Python validates the bounded PNG/JPEG/WebP payloads and sends native `image` inputs through `turn/start` or `turn/steer`. The image cache is the `images` folder under the runtime home, named by content hash. Snapshots contain only image IDs and labels; the palette requests bytes separately through `imageAssets` and retains the existing image nodes while text streams. Assets can only be requested for messages in the current conversation. History never fetches remote URLs or reads arbitrary localImage paths for preview. Failed submissions expose **Reuse message**, without automatically repeating a potentially delivered operation.

The clipboard and image viewer still require live Fusion verification. The JavaScript tests exercise paste dispatch, draft lifetime, preparation errors, async submit races, and asset caching using stand-ins; they do not prove embedded browser clipboard or canvas behavior.

Codex persists new conversations under EVE's runtime home. The history drawer uses `thread/list` with the EVE workspace and supported interactive sources, followed by `thread/resume` to restore messages and model context. It loads 30 conversations at a time and searches the loaded titles locally. Closing/reopening the panel preserves the current conversation. Restarting the add-in or reconnecting opens a blank chat; saved conversations remain available through history. ChatGPT sign-in is persisted by Codex. Sessions created by earlier ephemeral builds are not recoverable after their runtime exits. Local history belongs to the operating-system user, not a separate EVE account or cloud synchronization service.

All installed assets are resolved relative to the add-in. Runtime data uses the current user's `LOCALAPPDATA` or `~/Library/Application Support`, and the installers use Windows' ApplicationData special folder or `$HOME`. Compiler discovery uses PATH or SystemRoot; no drive letter or developer profile is assumed. The package build audits source and the complete zip, including binaries, for the current checkout/profile paths, literal absolute paths in text, and local debugger/bytecode artifacts.

## Structure

For diagnostics, open the account menu and enable **Debug logging**. It defaults off and remembers the choice in `debug.json` under the runtime home. **Open logs folder** opens the `logs` folder there in Explorer or Finder; `eve-debug.jsonl` records UTC timestamps, correlated tool requests with generated code, results/errors, duration, transport request timing, and Codex stderr. Rotation keeps the current file and three backups at approximately 2 MiB each. Disabling logging stops new entries and preserves existing files. Authentication RPC payloads are excluded; common credential patterns in diagnostic text are redacted. Code and tool results may contain design details, so review logs before sharing. Logging is local and never automatically uploaded. This toggle controls EVE's diagnostics, not Codex's existing session history.

- `addin/EVE/EVE.py`: Fusion lifecycle, toolbar, palette, custom-event bridge.
- `addin/EVE/eve/transport.py`: subprocess lifecycle and JSON-RPC.
- `addin/EVE/eve/controller.py`: account, model, chat, and cancellation state.
- `addin/EVE/eve/tool_protocol.py`: general Fusion tool declarations, validation, and instructions.
- `addin/EVE/eve/fusion_tools.py`: main-thread document inspection, API help, and command execution.
- `addin/EVE/eve/python_runner.py`: generated script entry point, captured output, errors, and cooperative cancellation.
- `addin/EVE/panel/`: local HTML/CSS/JavaScript interface, with no runtime web dependencies.
- `scripts/installer/Install.cs` and `scripts/installer/Install EVE.command`: per-user Windows and macOS installers; both validate files before installation and preserve previous versions.
- `scripts/eve_package.py`: package names, installer names, and test-mode installer commands shared by build, verification, and tests.

Codex I/O runs on worker threads. The only Fusion call from those workers is `fireCustomEvent`; Fusion API work and panel updates run in the custom event handler on Fusion's main thread. Palettes are recreated after workspace changes when visible.

## Visual preview

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory addin/EVE/panel
```

Open `http://127.0.0.1:8765/?preview=welcome` or `?preview=chat`. These pages display an explicit design-preview banner and use sample content. The sign-in button in preview mode only changes the sample UI; it never authenticates. The actual Fusion palette has no preview query parameter.

## macOS notes

Fusion on macOS runs add-ins with its bundled Python (3.14 in Fusion 2705) and renders palettes with Qt WebEngine, so the panel code is shared with Windows; only the paste hint switches to ⌘V. The add-in manifest declares `windows|mac`. Codex runs as a child process in its own process group; on shutdown EVE closes its stdin, waits briefly, then kills the group so the Code Mode host cannot linger. OpenAI signs and notarizes the macOS Codex binaries, so Gatekeeper accepts the bundled runtime after a browser download; only the unsigned installer script needs Terminal or a Privacy & Security approval. Codex keeps sign-in in `auth.json` under the runtime home on both platforms. `Open logs folder` uses Finder through `open`.

## Official references

- [Fusion add-in creation and manifests](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/WritingDebugging_UM.htm)
- [Fusion palettes and their JavaScript bridge](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Palettes_UM.htm)
- [Fusion threading and custom events](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Threading_UM.htm)
- [Fusion Python debugging](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/PythonSpecific_UM.htm)
- [Codex app-server protocol](https://learn.chatgpt.com/docs/app-server)

Current Autodesk docs and the installed Fusion API were inspected on September 19, 2026. Consult the pinned runtime's protocol when changing the Codex adapter.
