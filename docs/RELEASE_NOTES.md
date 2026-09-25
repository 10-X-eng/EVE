# STEVE 0.6.1 — DFM machine checks and catalog update

This patch improves the experimental DFM introduced in 0.6.0. The existing DFM switch and conversational workflow stay the same.

## Changes

- **Consistent report validity:** a check now revalidates every machine definition referenced by the part's ordered manufacturing plan. Changes to another stage's definition make findings stale; missing or invalid definitions leave them unverified. Measured values and original limits are retained without rerunning generated code. Unrelated catalog changes do not invalidate the report.
- **Resin and polymer SLS machines:** separate sourced files add Formlabs Form 4 and Fuse 1+ 30W nominal envelopes alongside MK4S and original CORE One. The Fuse definition records rounded chamber corners and material/settings-dependent usable-volume restrictions. No machine is selected automatically.
- **More live evidence:** a paired model test verifies machine discovery and orientation-dependent comparisons. Both DFM modes reached the same correct dimensional conclusions; this is integration evidence, not proof of improved design quality.

## Validation and scope

The combined changes passed live Windows Fusion checks for 24 machine/orientation cases and three machine-definition currency cases. Every inspected body revision remained unchanged. The local release branch ran 383 Python tests with 11 skips and no failures; focused DFM/catalog, chat, attachment and portability checks also passed. Windows and macOS CI run the complete Python suite, package installation and runtime checks before publication.

**DFM remains experimental.** Nominal XYZ comparisons do not prove printable placement, support success, drainage, powder removal, strength or manufacturability. Material/process qualification, slicer validation, live macOS DFM and a real authorized RMFG supplier report remain open.

See [machine definitions](https://github.com/10-X-eng/STEVE/blob/main/docs/MACHINES.md), [evaluation evidence](https://github.com/10-X-eng/STEVE/blob/main/docs/DFM_EVALUATION.md), and [remaining qualification](https://github.com/10-X-eng/STEVE/blob/main/docs/DFM_READINESS.md).

## Update or install

Use **Check for updates** in STEVE, then **Update STEVE**, and follow the installer prompts. Save your work and quit Fusion when prompted. Chats and preferences are retained.

- **Windows x64:** extract **STEVE-0.6.1-windows-x64.zip** and run **Install STEVE.exe**.
- **macOS (Apple silicon):** extract **STEVE-0.6.1-macos-arm64.zip** and run **Install STEVE.command** through Terminal (`bash ` followed by dragging the file into the window).

Download the complete platform ZIP rather than GitHub's source archive. Packages remain unsigned previews. Codex updates independently of STEVE.
