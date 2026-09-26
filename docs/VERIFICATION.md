# First milestone verification

- 0.8.1, issues #65–#68: 475 local Python tests passed (11 platform/installer skips), along with all six panel/browser suites and the actual runtime protocol smoke test. Regressions cover missing turn completion, either paused/idle event order, status refresh racing a new turn, unrelated threads, preserved document binding, protected active Fusion tools, long chats with paused goals, bounded transcript paging, browser links and a late turn-start reply racing an automatic continuation. The streaming fixture retains existing nodes across 240 token updates and rolling transcript windows. The reported paused-job screenshot's exact event sequence was not recovered; the placement race was reproduced in a controlled test.

- 0.8.1 update validation: the freshly built Windows package passed staging, activation, image migration, rollback and retry against the published 0.8.0 archive in an isolated filesystem fixture. Rollback restored every old installed file; chats, preferences, gallery access and release-note acknowledgement survived. Source and packaged-binary portability audits passed. The running Fusion add-in was not stopped or replaced. Clean Windows/macOS CI repeats the regression suite, installation and complete-package update checks before publication; native Fusion interaction remains a live user check.

- 0.8.0 update validation: the complete Windows 0.8.0 ZIP passed staging, activation, gallery migration, rollback and retry against the published 0.7.1 package in an isolated filesystem fixture. Every old installed file was restored on rollback; chat pixels/indexes and preferences remained byte-identical. Gallery permissions and release-note acknowledgement survived. Fusion was not stopped. The full local suite passed 466 tests (11 skipped), followed by 17 focused viewport tests including two additional restoration failures. Clean Windows/macOS CI verifies installer behavior and repeats package update checks.

- 0.8.0: a copy of the maintainer's real image store migrated 145 images with access off, preserving all 163 original files byte-for-byte. Repeat migration made no changes. Gallery fixtures cover damaged inputs, interrupted writes, permissions, duplicate images and removal tombstones. Real Edge checks cover gallery management, attachment drafts, responsive layouts and offline release notes. Close-up/isolation tests cover tiny parts inside large assemblies, hidden ancestors, repeated components, capture failure and cancellation. Native Fusion isolation and macOS appearance remain live checks; automated checks do not establish those results.

- September 26, 2026: the maintainer confirmed the installed 0.7.0 → 0.7.1 in-Fusion update worked on Windows. The confirmation button still displayed obsolete wording about closing Fusion; local changes correct the label and explicitly announce the STEVE restart. This report does not establish live macOS updater coverage.

- 0.7.0 release candidate: 439 Python tests passed locally (11 skipped), plus panel/image fixtures and real Edge checks for Settings, streaming DOM retention and Dream. The bundled runtime smoke test passed without inference. The Windows ZIP built and passed the portability audit. Local fixture installation was blocked by the installer's running-Fusion guard; Windows/macOS CI must verify installation before publication. The redesigned Dream transcript was also inspected at 440px and 340px widths.

- DFM follow-up (0.6.1): #49–#51 were merged and pulled main matched the tested integration tree. The release branch passed 383 local Python tests (11 skipped), with package installation covered separately by clean Windows/macOS CI. Local focused DFM/catalog, panel/image and 147-file portability checks passed. Live Fusion verified 24 nominal-envelope cases and three machine-definition currency cases without changing body revisions. These are scoped checks, not process qualification.

- Experimental DFM (0.6.0): the merged main tree matched the final reviewed branch and passed 381 local Python tests (11 skipped), panel/image checks, a real-browser streaming check and the portability audit. Live Windows Fusion measurements and scoped manufacturing limitations are recorded in [DFM evaluation](DFM_EVALUATION.md) and [readiness](DFM_READINESS.md). Machine definitions are sourced data, not full process qualification. Live macOS DFM and an authorized RMFG supplier report remain unverified.

The implementation is a prototype with user-confirmed streaming in Fusion; remaining lifecycle and visual checks are listed below. This document separates automated evidence, user-reported live results, and checks still required.

## Verified locally

- Fusion reliability and inspection (0.5.0): 295 local Python tests passed (3 skipped), including document/command waits, schematic GROUP selection, bounded product summaries, operation evidence, documentation tools, workflow helpers, and viewport camera restoration. The maintainer reported a selected cylindrical face was measured and a close-up captured in live Fusion on Windows, and reported the other manual tests passing without an itemized record. The blank-schematic report identified the normal GROUP command; the resulting inspection fix still needs live retesting. See [reliability validation](RELIABILITY_VALIDATION.md) for fixture coverage and remaining native checks.

- Independent Codex updates (0.4.0 release candidate): downloaded the actual official Windows 0.155.1 package through the in-app updater functions, verified its GitHub SHA-256, and passed the isolated initialization/model/thread/tool-declaration/goal probe before selecting the separate runtime. Tests cover stable release selection, both platform assets, checksum failures, malformed archives, cancellation, failed probes, duplicate requests, recovery, and preserving existing runtime files and active turns. The new runtime's ChatGPT catalog includes GPT-6-Sol and GPT-6-Luna. Browser checks cover version display, download controls, the in-menu Restart STEVE button, pending restart, recovery, and model refresh. An isolated check with the actual 0.153.4 and 0.155.1 executables downloaded/selected the update, invoked the controller restart action, confirmed the old process exited and the new executable started, and reopened the same persisted conversation without inference. Unit tests cover blocking restart during work/sign-in/download, chat restoration, and reporting failed activation; update readiness now requires reading back the selected version. The Mac 0.155.1 archive's digest and extraction layout were checked on Windows; executing this newer package on macOS still needs live confirmation. On September 22, 2026, the maintainer reported the update and in-menu restart working inside Fusion on Windows after testing the older-runtime upgrade path.

- OpenRouter provider (unreleased, experimental): automated tests cover PKCE challenge and callback-path checks, rejection of guessed callbacks, cancellation before key storage, key exchange, account summary, forgetting a rejected key while keeping it through network failures, sign-out, sign-in URL validation, catalog filtering (tools, text output, 64K context, batch and expired models), popularity default, per-model efforts and image support, gateway authentication at forward time, attribution headers, removal of local identifiers, path/Origin rejection, credit and sign-in error messages, context sizing per model, model switches, text-only image rejection, and provider preference isolation. The real bundled Codex runtime completed a fake OpenRouter tool loop with SSE keep-alive comments, replayed reasoning without null content, listed and resumed the chat after restart, and switched models. The controller DFM workflow also passed through the OpenRouter adapter. Panel and real-browser menu checks passed (menus run with Chrome locally). No live OpenRouter sign-in, key exchange, or paid inference has been performed. Still to verify live: the browser callback on `localhost` reaching STEVE's IPv4 loopback server on Windows and macOS, OpenRouter accepting replayed reasoning items and Codex's `include`, `prompt_cache_key` and `reasoning.summary` fields across model families, and Fusion work with several models.

- Claude subscription support (0.4.0 release candidate, experimental): official Claude Code 2.1.260 detected an existing Pro login outside PATH and enumerated account models without inference. Live Haiku 4.5 and Sonnet 5 each completed a document-inspection tool round through STEVE's bundled runtime against a simulated document; Sonnet used the full production prompt and tool schemas. These checks did not change real Fusion geometry. Offline checks with the real Claude executable cover text, tools, output/context limits, thinking-only recovery, refusal, upstream errors, truncation, and cancellation, with exactly one admitted upstream request per generation. Bundled-runtime fixtures cover images, steering, error propagation without retries, history after restart, signed replay isolation, and native goal continuation/completion. Setup and panel tests cover external sign-in guidance, missing clients, subscription-only authentication, environment conflicts, and model readiness. Native Fusion interaction and macOS Claude usage still require live confirmation. Claude web search is not connected.

- STEVE rename and upgrade: Windows installer fixtures verify previous-name discovery, replacement with a backup, unrelated add-in preservation, ambiguous-installation refusal, and retaining the upgrade record on reinstall. Data-transfer tests verify credentials/preferences/images remain byte-identical, chat paths (including canonical paths under aliased parent folders) and provider IDs are relocated, Codex goal records and historical messages remain unchanged, duplicate data folders are not merged, and interrupted or failed folder swaps recover. The bundled Codex runtime reopened a relocated conversation through the local inference fixture and continued it. macOS installer syntax is checked locally; native macOS installer execution remains a CI/user check. Earlier update checkers require one manual download after the repository rename. The local managed Windows installation was upgraded with the rebuilt package: 103 credential/preference/image files matched their backup byte-for-byte, the existing ChatGPT sign-in was recognized, and eight relocated ChatGPT chats were listed by the bundled runtime. The STEVE panel was checked at 436px and 320px widths. The user confirmed STEVE works in Fusion after the local upgrade.

- Job commands and controls are covered by controller, real Edge UI, and bundled-runtime checks. A local xAI-compatible inference fixture exercised automatic multi-turn continuation, native model goal tools, token limits, pause, Stop during a pending Fusion call, resume, model completion, replacement with fresh accounting, and saved active jobs loading paused without inference. Document-binding checks restore the original document/selection across chat switches and reject closed documents. Live local Gemma 4 E2B QAT at 32K context inspected a simulated document and marked its job complete using the native tool (5,520 reported tokens); no real Fusion geometry was modified. Job controls were visually inspected at 436×660 and 320×600. Live ChatGPT/Grok jobs and native Fusion visual behavior remain user checks.

- Submitted Python cards pass controller checks for overlapping calls, completion, failure, disconnects, stale callbacks, and restoration from saved dynamic tool items. Real Edge DOM checks cover safe code rendering, bounded panes, expansion state, and code-node/scroll retention; the panel was visually inspected at 436×660. Partial tool arguments are not streamed by the current protocol. Native Fusion visual confirmation remains a user check.

- Local Ollama was exercised through STEVE's actual controller and bundled runtime with Gemma 4 E2B QAT at 8K context on Windows. It called the document inspection tool against a read-only simulated Fusion fixture, used the returned data, reopened the conversation after a process restart, accepted steering during a pending tool call, and stopped a pending turn. A generated red image passed through STEVE's image pipeline and was correctly identified. No real Fusion design was modified. Native Fusion operations with a local model and macOS Ollama remain live user checks. Automated coverage checks offline recovery, no-sign-in UI, empty catalogs, local/cloud boundaries, tool and vision requirements, bounded metadata, allocated context, alias runner reuse, model switches, and provider preference isolation.

- Grok / X is included in the 0.3.0 release candidate. The new tests cover PKCE/state checks, device polling and slowdown, cancellation before token storage, private credential persistence, refresh rotation, logout, xAI URL validation, model discovery, provider preferences, stale runtime notifications, and switching restrictions. Windows DPAPI was exercised with fixture credentials. Local Grok connection and sign-in callback servers bind without reverse DNS, avoiding a macOS startup stall; regression checks also reject non-loopback binding. The real bundled Codex runtime completed a mock xAI response/tool/result loop, listed that Grok chat, restarted, resumed, and continued it. The live xAI device endpoint accepted the configured public client and scopes; no account sign-in was completed, credentials saved, or paid inference requested in that check. The user confirmed browser sign-in completes automatically without copying the browser code. Authenticated model discovery was checked against the live xAI catalog; supported effort levels and defaults populate correctly. The bundled runtime fixture verifies Extra High reaches both requests in a tool loop and a resumed chat can switch to Low. Live Grok inference inside Fusion remains for the user to verify.

- STEVE 0.2.0 adds update discovery and verified downloads. Tests cover preview releases, numeric version ordering, platform assets, missing checksums, drafts, unsafe metadata, offline recovery, overlapping checks, progress, cancellation, checksum mismatch, truncated downloads, existing-file preservation, and shutdown. Update checks and downloads preserve an active model turn. The Windows Known Folder API was exercised read-only. A real public v0.1.0 package was downloaded into an isolated test folder and its published SHA-256 verified. The local 0.2.0 Windows package passed installer/runtime verification with all 34 payload files matching source and checksums. Live update notices and downloads inside Fusion still need user confirmation.

- Tool activity is covered by controller and panel tests: overlapping calls, operation labels without Python payloads, continued text streaming, delayed callbacks from older turns, submission failure, disconnect, waiting and stopping states, folding finished steps into a summary, and showing a failed step's exception. The footer status line covers STEVE's seven Fusion and saved-image tools; native Codex web-search activity is not displayed here. Live appearance inside Fusion still needs confirmation.

- Current local suite: 214 Python tests (the Unix permission check is skipped on Windows), plus JavaScript checks. Native Windows bitmap/PNG conversion and the asynchronous image-paste bridge are tested without reading or changing the real system clipboard. Image coverage verifies bounded native inputs, image-only sends, exact-turn image steering, previews excluded from streaming state, local cache/history reconstruction, invalid input rejection without stopping a running task, and recovery after failed delivery. JavaScript fixtures check clipboard types, attachment preparation/removal, send/steer routing, retained failed drafts, submit races, and separate preview caching. The user confirmed screenshot paste works after the native clipboard change. macOS clipboard conversion, the image viewer, and actual model interpretation remain unverified.
- Image recall checks cover a durable conversation index, restart and history reopening, paging, deduplicated image files, cross-chat rejection, missing/corrupted images, repair on reattachment, cancellation, native image reinjection with historical labels, and cache failures after successful delivery. Reopened images stay out of streamed state and do not create duplicate index entries. These are controlled tests; model-driven recall inside Fusion still needs live verification.
- Model/effort and document coverage verifies persisted preferences across restart, reconnect and history; unsupported choices; explicit default-effort restoration; rejected sends not repinning; pinned selection/product; tab-switch waiting and automatic resumption; user-command waiting; cancellation; closed targets; the switch-before-command-execution race; intentional document creation; and rejection of live UI targeting in generated code. UI fixtures cover effort options, disabled controls, task labels and wait status. Actual Fusion event timing and visual layout remain live checks.
- The real bundled model catalog supplies model-specific effort levels. An unauthenticated `turn/start` schema check accepts a catalog effort and returns the expected unknown-thread error before inference. No model request is made by that check.

- The feature suite also covers JavaScript rendering, history, debug-menu and composer checks; successful bounded previews for oversized results; actionable errors; immutable selection snapshots; viewport capture/cleanup; native image delivery; exact-turn steering and failure handling; and Data Panel search followed by assembly insertion through a fake Autodesk host. No test performs a real cloud search or real Fusion insertion.
- The runtime accepts the current seven tool declarations and live web-search configuration. Native text/image `turn/steer` input reaches the expected "no active turn to steer" rejection in an unauthenticated smoke test; this validates schema compatibility, not live steering or image interpretation by a model.

- The dedicated Python query tool uses the shared runner without creating a Fusion command. Tests cover reading fake CAM setup/machine data, printed output, script errors, and stale-document rejection. Current prompts instruct STEVE to prefer this tool for information gathering. Actual model selection and access to the user's CAM libraries remain live checks.

- Debug logging checks cover default-off behavior, remembered on/off preference, no new writes after disabling, bounded file rotation, common-secret redaction, failed generated-code capture with correlated results and timing, Codex stderr draining, and the menu actions. The toggle and folder button still need visual confirmation inside Fusion.

- Command completion is checked after Python returns: a regression test simulates Fusion aborting the command after successful Python execution and confirms STEVE reports failure. The installed API's module documentation also confirms that stopping an add-in unloads its relative imports; STEVE uses relative imports for its controller and bridge, so no custom reload mechanism was added.
- Application execution mode covers APIs that cannot run inside command transactions. Tests confirm it runs from the main-thread event without starting a command, returns the new document identity after a document switch, and rejects cancelled or stale-target work. This mode intentionally offers no grouped Undo or automatic rollback.

- Python controller and subprocess transport tests exercise streamed message assembly, fast completion, cancellation during startup, interruption completion, browser-launch failure, timeout recovery, shutdown races, account/model state, JSONL events, unsupported server requests, Unicode, and isolated credentials.
- Installer tests exercise initial installation, update backups, corrupted payload rejection, path validation, and preservation of an unmanaged existing folder. They run against workspace fixtures, not a real Fusion installation.
- The complete generated zip was extracted and installed into a workspace fixture using the compiled installer. All payload files matched their checksums, the installed add-in matched current source, and its runtime passed startup, account/model reads, Code Mode thread creation, and actual process-exit checks. Fusion-generated local debugger settings are excluded from distribution.
- The actual bundled Codex 0.155.1 runtime completes initialization, account/read, model/list, thread/start with Code Mode enabled, and shutdown. The smoke test and live controller now share the exact same thread-start payload. This check is unauthenticated and does not send a model request.
- The browser design preview has been visually inspected at 440×760 and 320×600. Suggested prompts, keyboard send, Stop, settings, preview sign-out, and literal HTML-like input were exercised against sample responses. Narrow-width inspection found and fixed an initial welcome-screen scroll position bug; the welcome now starts at the top without horizontal overflow.
- The redesigned panel (turn grouping, activity blocks, tables and highlighted code, Settings view, **+** menu, chips, Dream cards) was rendered in headless Edge at 440×720, 440×1500 and 340×720 against a scripted bridge with a five-step bracket conversation, a running step, a failed step, a Dream concept and a pending concept. No page errors or horizontal overflow were observed. Live appearance inside Fusion's embedded browser still needs confirmation.

Commands:

```powershell
py -3.13 -m unittest discover -s tests -v
node tests/test_panel.cjs
node tests/test_images.cjs
py -3.13 scripts/smoke_runtime.py
py -3.13 scripts/verify_package.py
```

## User-reported live results and corrections

On September 19, the user loaded STEVE in Fusion and supplied a screenshot. The panel opened, but a light document background made its text unreadable. Browser sign-in attempted to launch ChatGPT desktop; the second login attempt succeeded. Starting a conversation then failed because `thread/start.environments` required an experimental capability.

Corrections now in source: opaque document and panel backgrounds, compact sign-in layout without a disabled composer, automatic saved-account validation and login-state recovery, a local browser completion page, and removal of the unused experimental `environments` field. Controller tests cover saved-account discovery, successful login, missed notifications, and preservation of pending sign-in. The exact corrected thread-start payload passed against the real runtime. The corrected welcome layout was checked in a browser at 436×626; confirmation of the fixes inside Fusion remains pending.

## Required live Fusion checks

- [ ] Select a model and effort, restart STEVE, reopen history, and confirm both choices and the next turn's settings.
- [ ] Start a task, change selection/workspace, and verify it retains the original entities and product.
- [ ] Switch document tabs while a call is pending; verify the target label, automatic wait/resume, and no edits or focus changes in the other document.
- [ ] Start/finish a user command, Stop while STEVE is waiting, and close the task document; verify each pending call is handled once.

- [ ] Search the user's Data Panel by name; verify project/folder scope, ambiguous matches, pagination and access errors, then insert a chosen design and verify its reference and placement.
- [ ] Capture real geometry and have the model verify the image alongside API measurements.
- [ ] Send a correction during a tool loop and confirm it affects subsequent work; test failed/stale delivery.
- [ ] Select an edge or component, send a request referring to it, and verify the intended original selection is used.
- [ ] Confirm web search finds current Autodesk API docs without private data in the query.
- [ ] Confirm the Quick Access STEVE button works in Design and Manufacture and is removed on Stop.
- [ ] Query a large tool library; verify partial results lead to smaller queries rather than repeated writes or user-facing size errors.

The general Python bridge now exposes document inspection, installed API help, and generated execution. Tests cover main-thread queue dispatch, access to a fake CAM product, document changes before and during command startup, active-command rejection, cancellation, command failure flags, bounded results, and a responsive JSON-RPC reader while execution is pending. Missing/incomplete/incompatible Codex runtime checks and the setup help flow are also tested. These are controlled fixtures, not actual Fusion geometry or Undo tests. The bundled runtime accepts and persists tool declarations at thread creation; start a new chat after updating from the chat-only prototype.

- [ ] Create a parametric component through a real model tool call, then verify its dimensions and bodies through the API.
- [ ] Create a document using application mode, then inspect and model in it using command mode.
- [ ] Undo the model operation once and confirm the original design remains intact.
- [ ] Trigger an API error and verify transaction behavior before correcting the script.
- [ ] Inspect an assembly and a manufacturing workspace and run representative API operations.

Saved history now uses Codex's native persistent threads. In an isolated runtime home with no signed-in account, a deliberately unauthenticated turn saved its input; after closing and restarting the actual bundled runtime, `thread/list` found it and `thread/resume` restored that input. This verifies local persistence and protocol compatibility, not a successful model reply. Unit tests cover listing, pagination, resuming, continuation on the original thread, invalid IDs, failure recovery, and excluding non-message items. The history drawer still needs live Fusion confirmation.

The source audit found no personal profile or checkout paths. A fixed Windows drive in compiler discovery was replaced with PATH/SystemRoot discovery. Build-time portability checks now scan source and release contents, including binaries, and reject embedded paths from the build machine and local debugger/bytecode files. This does not replace a clean-machine installation test.

The user subsequently confirmed that Stop/Run reloads STEVE and that replies stream in Fusion, but reported flickering on each token. The renderer had replaced all conversation HTML and restarted message entrance animations. It now retains message and Markdown nodes, appends text in place, batches snapshots per animation frame, and avoids updating unchanged controls. Local regression checks pass for node retention across 240 updates, Markdown corrections, clearing messages, burst coalescing, and delivery of the final state. The additional real-browser regression suite remains unrun: headless browser launch was denied (`EPERM`), and browser access to the local fixture was explicitly denied. Visual confirmation inside Fusion remains pending.

- [ ] Install the complete Windows package on the user's account.
- [x] Load the add-in and open the panel (user screenshot).
- [x] Complete real ChatGPT browser sign-in (user reported success on the second attempt).
- [ ] Verify the corrected styling and saved-account detection after restarting Fusion.
- [x] Receive an actual streamed reply with the corrected thread-start payload (user reported streaming, with flicker).
- [ ] Confirm smooth streaming after the incremental-rendering fix.
- [ ] Paste a screenshot and attach an image file; inspect/remove previews, send with/without text, steer a running task with an image, and reopen the saved chat.
- [ ] Open history, select an earlier chat, and continue it after restarting STEVE.
- [ ] Stop an actual response, then send another message successfully.
- [ ] Close/reopen the panel and confirm conversation state survives.
- [ ] Switch workspaces and confirm the palette recovers correctly.
- [ ] Stop/start the add-in and restart Fusion; confirm ChatGPT sign-in persists and old runtime processes exit.
- [ ] Sign out; confirm the UI and runtime both report no signed-in account.

Computer Use can list Fusion but still refuses to capture it because app approval is rejected. Live results above are explicitly attributed to the user's screenshot and report; direct agent verification remains unavailable.

The packages are unsigned: Windows x64 and macOS on Apple silicon. A clean-machine installation has not yet been verified on either platform.

## macOS port

The add-in, packaging, installer, and workflow now cover macOS on Apple silicon. Verified locally on a Mac with Fusion 2705 installed: the shared Python suite (including the platform data home, runtime target matching, executable-bit recovery, and process-group shutdown), the JavaScript suites, the runtime smoke test against the notarized `aarch64-apple-darwin` Codex 0.153.4 package, a package build with the `Install STEVE.command` installer, the installer tests, and `verify_package.py` installing that zip into a fixture and starting the installed runtime. On September 20, 2026 the maintainer installed that package on the same Mac and reported STEVE working inside Fusion; the itemized checks below record what has been confirmed individually.

- [x] Install the macOS package and load STEVE in Fusion (user report).
- [ ] Open the palette from the Quick Access toolbar; confirm dark styling and the ⌘V paste hint.
- [ ] Complete ChatGPT browser sign-in and receive a streamed reply.
- [ ] Paste a screenshot from the macOS clipboard and attach an image file.
- [ ] Run a query and an execute tool call; capture the viewport.
- [ ] Open the logs folder from Settings (⚙) → Diagnostics and confirm Finder shows it.
- [ ] Stop the add-in and quit Fusion; confirm no `codex-app-server` or `codex-code-mode-host` process remains.
- [ ] Verify the Gatekeeper path for `Install STEVE.command` on a clean Mac, including the Privacy & Security approval.

## Repository delivery

The source is published in the public STEVE repository. The build workflow performs package and installer verification on GitHub-hosted Windows and macOS runners before automatically publishing new versions pushed to `main`. Already-published versions are skipped. GitHub build validation does not replace the live Fusion checks listed above.

## Settings and RMFG checkout update

- Local regression suite: 398 tests run, 11 skipped, no failures. Menu, image, renderer and real-browser streaming checks passed; portability audit passed 151 files.
- Browser menu checks cover keyboard focus, exclusive account/settings/history panels, outside/Escape dismissal, action routing, busy locks, and 320/436/760 px layouts. The settings menu was visually inspected at 436 px.
- RMFG controlled-response tests cover automatic scoped uploads, cancellation, multiple quoted parts and quantities, effective supplier defaults, stale geometry, mismatched quotes/carts, blocked/expired quotes, identical retry keys, DFM-only connection compatibility and checkout-link privacy. Real-runtime Claude/Grok/Ollama fixtures enforce all five DFM/supplier tools while DFM is off.
- No live supplier quote/cart or payment was created for this update. Live supplier report and hosted-checkout validation remain documented limitations; #27 is closed with the initial DFM milestone for 0.6.2.

## In-Fusion update development checks

On September 25, 2026, Fusion 2705.1.25 on Windows successfully stopped a disposable
managed add-in, replaced it with a separately staged version, restarted it and
received the new version's startup receipt while Fusion stayed open. A second
fixture deliberately omitted the receipt: the helper restored the previous files
and restarted the previous version after the startup timeout. Both fixture add-ins
were unlinked afterward. The active Untitled document and SelectCommand were
unchanged; the user's running STEVE and design geometry were not replaced or edited.

These tests exercise the real Autodesk lifecycle and file-swap helper. Live macOS
reload and a complete released STEVE-to-STEVE update with chat restoration still
need user verification. Unit coverage checks payload tampering, unmanaged targets,
rename failures, interrupted-swap recovery, idle handoff and download reuse.

## STEVE Dream development checks

On September 26, 2026, a real ChatGPT-signed-in Codex 0.153.4 connection generated an
aluminum enclosure concept and refined it to green in the same STEVE controller chat.
Both native `imageGeneration` results were decoded, cached and indexed successfully.
No Fusion document operations were requested by the test harness.

Replaying the disposable test conversation in an isolated Codex 0.155.1 home
restored both concepts and passed its database integrity check.

Unit tests cover provider gating, image validation and bounds, cross-chat file access,
cache recovery, duplicate events, history reconstruction and non-overwriting exports.
Real-browser checks cover generation progress, previews larger than 1 MiB, unchanged
image nodes during later messages, refinement attachments, draft preservation, save
actions and unsupported providers/models. Real generated concepts were visually checked
at 440px and 340px panel widths. Live Fusion palette and macOS use still need user testing.
