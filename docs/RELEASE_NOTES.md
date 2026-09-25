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

Open **STEVE logo → Updates → Check for updates**, then choose **Update STEVE**. Save your work and quit Fusion when prompted. Chats and preferences are retained.

- **Windows x64:** extract **STEVE-0.6.2-windows-x64.zip** and run **Install STEVE.exe**.
- **macOS (Apple silicon):** extract **STEVE-0.6.2-macos-arm64.zip** and run **Install STEVE.command** through Terminal (`bash ` followed by dragging the file into the window).

Download the complete platform ZIP rather than GitHub's source archive. Packages remain unsigned previews. Codex updates independently of STEVE.
