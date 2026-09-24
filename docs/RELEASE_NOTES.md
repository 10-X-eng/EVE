# STEVE 0.6.0 — Experimental DFM and machine definitions

Turn **DFM** on in STEVE's menu and describe how each part will be made. STEVE can retain ordered manufacturing stages, inspect actual Fusion geometry and report measured concerns, unsupported checks and unknowns. DFM starts off and can be disabled between tasks without losing plans.

## What's new

- **Process-aware checks:** milling/drilling, turning, sheet metal, FDM, resin and powder guidance, loaded when needed. Native helpers inspect supported radii, cylinder bands, selected face distances, sampled walls, build envelopes, planar overhangs, sealed cavities and existing sheet-metal bend lines.
- **One definition file per machine:** sourced capabilities are selected per process stage and bound by a content hash. The initial MK4S and original CORE One definitions cover nominal build envelopes. Missing capabilities remain unknown; changed definitions invalidate old checks instead of silently changing their limits.
- **Reports tied to current evidence:** geometry, ordered plans and selected machine definitions are checked for changes. Reports distinguish measured concerns, unknown coverage and evidence-backed exclusions; successful Python execution alone is not a manufacturing pass.
- **Optional RMFG sheet-metal workflow:** connect a supplier account and explicitly approve each selected-part STEP upload. Jobs retain snapshot identity and retry receipts; no orders, payments or automatic risk acceptance. Live supplier authorization/report qualification is still pending.
- **Clearer tools and documentation:** concise calling contracts, Python context loaded on demand, improved installed-API helper compatibility and current Autodesk reference candidates.

## Validation and scope

Live Windows Fusion fixtures exercised native and SAT-imported geometry, selected distances and assembly frames, counterbores/intersecting holes/open pockets, bent sheet and additive envelope/wall/cavity checks. The same rotated plate correctly exceeded the selected MK4S envelope while fitting the selected CORE One envelope. Inspection preserved body revisions; setup was confined to disposable fixtures.

The merged main checkout passed 381 Python tests (11 skipped), panel/image checks and a real browser streaming check. Scripted provider integration exercised DFM on/off/on through the actual Codex runtime with Claude, Grok and Ollama adapters. Windows and macOS release packages must also pass CI build, runtime and fixture-install verification before publication.

**DFM remains experimental.** These are scoped measurements and comparisons, not a certified manufacturing rule library or a guarantee of machining/printing success. Slicer outcomes, physical process qualification, complete machine profiles, live macOS DFM and an authorized RMFG supplier report remain unverified. Recorded paired model tasks succeeded with DFM both off and on; they do not establish better generated geometry yet.

See [DFM scope](https://github.com/10-X-eng/STEVE/blob/main/docs/DFM.md), [machine definitions](https://github.com/10-X-eng/STEVE/blob/main/docs/MACHINES.md), and [validation status](https://github.com/10-X-eng/STEVE/blob/main/docs/DFM_READINESS.md).

## Update or install

Existing users can choose **Check for updates**, then **Update STEVE**. Save your work and quit Fusion when prompted. Chats and preferences are retained. Start a **new chat** after updating to load the revised tool definitions; existing chats keep their registered definitions.

- **Windows x64:** download **STEVE-0.6.0-windows-x64.zip**, extract the complete ZIP, close Fusion and run **Install STEVE.exe**.
- **macOS (Apple silicon):** download **STEVE-0.6.0-macos-arm64.zip**, extract it, quit Fusion and run **Install STEVE.command** through Terminal (`bash ` followed by dragging the file into the window).

Both ZIPs include the runtime, installer and installation guide, with accompanying SHA-256 checksums. GitHub's Source code archives omit the runtime and installer. These are unsigned previews. Codex updates independently of STEVE.
