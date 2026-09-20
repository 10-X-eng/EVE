# First milestone verification

The implementation is a prototype with user-confirmed streaming in Fusion; remaining lifecycle and visual checks are listed below. This document separates automated evidence, user-reported live results, and checks still required.

## Verified locally

- Current suite: 120 Python tests, plus JavaScript checks. Image coverage verifies bounded native inputs, image-only sends, exact-turn image steering, previews excluded from streaming state, local cache/history reconstruction, invalid input rejection without stopping a running task, and recovery after failed delivery. JavaScript fixtures check clipboard types, attachment preparation/removal, send/steer routing, retained failed drafts, submit races, and separate preview caching. Live Fusion clipboard, canvas decoding, image viewer, and actual model interpretation remain unverified.
- Model/effort and document coverage verifies persisted preferences across restart, reconnect and history; unsupported choices; explicit default-effort restoration; rejected sends not repinning; pinned selection/product; tab-switch waiting and automatic resumption; user-command waiting; cancellation; closed targets; the switch-before-command-execution race; intentional document creation; and rejection of live UI targeting in generated code. UI fixtures cover effort options, disabled controls, task labels and wait status. Actual Fusion event timing and visual layout remain live checks.
- The real bundled model catalog supplies model-specific effort levels. An unauthenticated `turn/start` schema check accepts a catalog effort and returns the expected unknown-thread error before inference. No model request is made by that check.

- The feature suite also covers JavaScript rendering, history, debug-menu and composer checks; successful bounded previews for oversized results; actionable errors; immutable selection snapshots; viewport capture/cleanup; native image delivery; exact-turn steering and failure handling; and Data Panel search followed by assembly insertion through a fake Autodesk host. No test performs a real cloud search or real Fusion insertion.
- The pinned runtime accepts the current five tool declarations and live web-search configuration. Native text/image `turn/steer` input reaches the expected "no active turn to steer" rejection in an unauthenticated smoke test; this validates schema compatibility, not live steering or image interpretation by a model.

- The dedicated Python query tool uses the shared runner without creating a Fusion command. Tests cover reading fake CAM setup/machine data, printed output, script errors, and stale-document rejection. Current prompts instruct EVE to prefer this tool for information gathering. Actual model selection and access to the user's CAM libraries remain live checks.

- Debug logging checks cover default-off behavior, remembered on/off preference, no new writes after disabling, bounded file rotation, common-secret redaction, failed generated-code capture with correlated results and timing, Codex stderr draining, and the menu actions. The toggle and folder button still need visual confirmation inside Fusion.

- Command completion is checked after Python returns: a regression test simulates Fusion aborting the command after successful Python execution and confirms EVE reports failure. The installed API's module documentation also confirms that stopping an add-in unloads its relative imports; EVE uses relative imports for its controller and bridge, so no custom reload mechanism was added.
- Application execution mode covers APIs that cannot run inside command transactions. Tests confirm it runs from the main-thread event without starting a command, returns the new document identity after a document switch, and rejects cancelled or stale-target work. This mode intentionally offers no grouped Undo or automatic rollback.

- Python controller and subprocess transport tests exercise streamed message assembly, fast completion, cancellation during startup, interruption completion, browser-launch failure, timeout recovery, shutdown races, account/model state, JSONL events, unsupported server requests, Unicode, and isolated credentials.
- Installer tests exercise initial installation, update backups, corrupted payload rejection, path validation, and preservation of an unmanaged existing folder. They run against workspace fixtures, not a real Fusion installation.
- The complete generated zip was extracted and installed into a workspace fixture using the compiled installer. All payload files matched their checksums, the installed add-in matched current source, and its runtime passed startup, account/model reads, Code Mode thread creation, and actual process-exit checks. Fusion-generated local debugger settings are excluded from distribution.
- The actual bundled Codex 0.153.4 runtime completes initialization, account/read, model/list, thread/start with Code Mode enabled, and shutdown. The smoke test and live controller now share the exact same thread-start payload. This check is unauthenticated and does not send a model request.
- The browser design preview has been visually inspected at 440×760 and 320×600. Suggested prompts, keyboard send, Stop, account menu, preview sign-out, and literal HTML-like input were exercised against sample responses. Narrow-width inspection found and fixed an initial welcome-screen scroll position bug; the welcome now starts at the top without horizontal overflow.

Commands:

```powershell
py -3.13 -m unittest discover -s tests -v
node tests/test_panel.cjs
node tests/test_images.cjs
py -3.13 scripts/smoke_runtime.py
py -3.13 scripts/verify_package.py
```

## User-reported live results and corrections

On September 19, the user loaded EVE in Fusion and supplied a screenshot. The panel opened, but a light document background made its text unreadable. Browser sign-in attempted to launch ChatGPT desktop; the second login attempt succeeded. Starting a conversation then failed because `thread/start.environments` required an experimental capability.

Corrections now in source: opaque document and panel backgrounds, compact sign-in layout without a disabled composer, automatic saved-account validation and login-state recovery, a local browser completion page, and removal of the unused experimental `environments` field. Controller tests cover saved-account discovery, successful login, missed notifications, and preservation of pending sign-in. The exact corrected thread-start payload passed against the real runtime. The corrected welcome layout was checked in a browser at 436×626; confirmation of the fixes inside Fusion remains pending.

## Required live Fusion checks

- [ ] Select a model and effort, restart EVE, reopen history, and confirm both choices and the next turn's settings.
- [ ] Start a task, change selection/workspace, and verify it retains the original entities and product.
- [ ] Switch document tabs while a call is pending; verify the target label, automatic wait/resume, and no edits or focus changes in the other document.
- [ ] Start/finish a user command, Stop while EVE is waiting, and close the task document; verify each pending call is handled once.

- [ ] Search the user's Data Panel by name; verify project/folder scope, ambiguous matches, pagination and access errors, then insert a chosen design and verify its reference and placement.
- [ ] Capture real geometry and have the model verify the image alongside API measurements.
- [ ] Send a correction during a tool loop and confirm it affects subsequent work; test failed/stale delivery.
- [ ] Select an edge or component, send a request referring to it, and verify the intended original selection is used.
- [ ] Confirm web search finds current Autodesk API docs without private data in the query.
- [ ] Confirm the Quick Access EVE button works in Design and Manufacture and is removed on Stop.
- [ ] Query a large tool library; verify partial results lead to smaller queries rather than repeated writes or user-facing size errors.

The general Python bridge now exposes document inspection, installed API help, and generated execution. Tests cover main-thread queue dispatch, access to a fake CAM product, document changes before and during command startup, active-command rejection, cancellation, command failure flags, bounded results, and a responsive JSON-RPC reader while execution is pending. Missing/incomplete/incompatible Codex runtime checks and the setup help flow are also tested. These are controlled fixtures, not actual Fusion geometry or Undo tests. The bundled runtime accepts and persists tool declarations at thread creation; start a new chat after updating from the chat-only prototype.

- [ ] Create a parametric component through a real model tool call, then verify its dimensions and bodies through the API.
- [ ] Create a document using application mode, then inspect and model in it using command mode.
- [ ] Undo the model operation once and confirm the original design remains intact.
- [ ] Trigger an API error and verify transaction behavior before correcting the script.
- [ ] Inspect an assembly and a manufacturing workspace and run representative API operations.

Saved history now uses Codex's native persistent threads. In an isolated runtime home with no signed-in account, a deliberately unauthenticated turn saved its input; after closing and restarting the actual bundled runtime, `thread/list` found it and `thread/resume` restored that input. This verifies local persistence and protocol compatibility, not a successful model reply. Unit tests cover listing, pagination, resuming, continuation on the original thread, invalid IDs, failure recovery, and excluding non-message items. The history drawer still needs live Fusion confirmation.

The source audit found no personal profile or checkout paths. A fixed Windows drive in compiler discovery was replaced with PATH/SystemRoot discovery. Build-time portability checks now scan source and release contents, including binaries, and reject embedded paths from the build machine and local debugger/bytecode files. This does not replace a clean-machine installation test.

The user subsequently confirmed that Stop/Run reloads EVE and that replies stream in Fusion, but reported flickering on each token. The renderer had replaced all conversation HTML and restarted message entrance animations. It now retains message and Markdown nodes, appends text in place, batches snapshots per animation frame, and avoids updating unchanged controls. Local regression checks pass for node retention across 240 updates, Markdown corrections, clearing messages, burst coalescing, and delivery of the final state. The additional real-browser regression suite remains unrun: headless browser launch was denied (`EPERM`), and browser access to the local fixture was explicitly denied. Visual confirmation inside Fusion remains pending.

- [ ] Install the complete Windows package on the user's account.
- [x] Load the add-in and open the panel (user screenshot).
- [x] Complete real ChatGPT browser sign-in (user reported success on the second attempt).
- [ ] Verify the corrected styling and saved-account detection after restarting Fusion.
- [x] Receive an actual streamed reply with the corrected thread-start payload (user reported streaming, with flicker).
- [ ] Confirm smooth streaming after the incremental-rendering fix.
- [ ] Paste a screenshot and attach an image file; inspect/remove previews, send with/without text, steer a running task with an image, and reopen the saved chat.
- [ ] Open history, select an earlier chat, and continue it after restarting EVE.
- [ ] Stop an actual response, then send another message successfully.
- [ ] Close/reopen the panel and confirm conversation state survives.
- [ ] Switch workspaces and confirm the palette recovers correctly.
- [ ] Stop/start the add-in and restart Fusion; confirm ChatGPT sign-in persists and old runtime processes exit.
- [ ] Sign out; confirm the UI and runtime both report no signed-in account.

Computer Use can list Fusion but still refuses to capture it because app approval is rejected. Live results above are explicitly attributed to the user's screenshot and report; direct agent verification remains unavailable.

The packages are unsigned: Windows x64 and macOS on Apple silicon. A clean-machine installation has not yet been verified on either platform.

## macOS port

The add-in, packaging, installer, and workflow now cover macOS on Apple silicon. Verified locally on a Mac with Fusion 2705 installed: the shared Python suite (including the platform data home, runtime target matching, executable-bit recovery, and process-group shutdown), the JavaScript suites, the runtime smoke test against the notarized `aarch64-apple-darwin` Codex 0.153.4 package, a package build with the `Install EVE.command` installer, the installer tests, and `verify_package.py` installing that zip into a fixture and starting the installed runtime. On September 20, 2026 the maintainer installed that package on the same Mac and reported EVE working inside Fusion; the itemized checks below record what has been confirmed individually.

- [x] Install the macOS package and load EVE in Fusion (user report).
- [ ] Open the palette from the Quick Access toolbar; confirm dark styling and the ⌘V paste hint.
- [ ] Complete ChatGPT browser sign-in and receive a streamed reply.
- [ ] Paste a screenshot from the macOS clipboard and attach an image file.
- [ ] Run a query and an execute tool call; capture the viewport.
- [ ] Open the logs folder from the account menu and confirm Finder shows it.
- [ ] Stop the add-in and quit Fusion; confirm no `codex-app-server` or `codex-code-mode-host` process remains.
- [ ] Verify the Gatekeeper path for `Install EVE.command` on a clean Mac, including the Privacy & Security approval.

## Repository delivery

The source is published in the public EVE repository. The build workflow performs package and installer verification on GitHub-hosted Windows and macOS runners before automatically publishing new versions pushed to `main`. Already-published versions are skipped. GitHub build validation does not replace the live Fusion checks listed above.
