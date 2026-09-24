# STEVE 0.5.0 — Better Fusion inspection and verification

STEVE now has richer document context, explicit verification results, searchable Fusion documentation for every provider, and focused viewport captures.

## What changed

- **Preserve work while waiting.** Pending tools explain which document or Fusion command they are waiting for. Waits do not expire or cancel Fusion commands. Native-call time no longer consumes the Python loop budget.
- **Inspect Electronics selection mode.** The verified schematic GROUP state permits inspection and queries without interrupting selection. Editing operations remain gated and return actionable guidance.
- **Read richer document summaries.** Bounded Design, CAM, and Electronics summaries report useful state, missing capabilities, and incomplete collection coverage. Electronics design editing remains limited by the installed API.
- **Separate execution from verification.** Measured checks and limited feature-health comparisons distinguish code completion from verified outcomes. Missing evidence and failed checks are reported explicitly.
- **Find Fusion documentation with any provider.** Search installed API classes and official samples, inspect installed signatures, and fetch Autodesk API reference pages through dedicated tools.
- **Use consistent Python helpers.** Helpers resolve pinned selections and entity tokens, validate unit expressions, and page through collections without dumping entire documents or libraries.
- **Capture useful views.** Named views and selected-entity close-ups restore the original camera after capture, including failures. Images supplement API measurements.
- **Allow slower Windows image-paste startup.** The background clipboard helper now has a bounded 30-second deadline to accommodate slower PowerShell/.NET startup; it does not block Fusion's UI thread.

This release also includes the previously merged in-app STEVE update flow and the renamed **Jobs** controls. Use `/jobs` to manage ongoing work.

## Verification

Automated checks cover the new behavior with simulated Autodesk hosts, provider/runtime fixtures, and platform package tests. The maintainer reported selection measurement and close-up capture working inside Fusion on Windows. Some native Fusion workflows still need itemized live confirmation, including retesting the schematic GROUP inspection fix. See [verification status](https://github.com/10-X-eng/STEVE/blob/main/docs/VERIFICATION.md) and [reliability validation](https://github.com/10-X-eng/STEVE/blob/main/docs/RELIABILITY_VALIDATION.md).

DFM is planned separately and is not included in this release.

## Update or install

Existing users can choose **Check for updates**, then **Update STEVE**. Save your work and quit Fusion when prompted so the installer can replace the add-in. Saved chats and preferences are retained. **Download only** is also available.

- **Windows x64:** download **STEVE-0.5.0-windows-x64.zip**, extract the whole ZIP, close Fusion, then run **Install STEVE.exe**.
- **macOS (Apple silicon):** download **STEVE-0.5.0-macos-arm64.zip**, extract it, quit Fusion, then run **Install STEVE.command** through Terminal (type `bash `, drag the file in, press Return) or allow it under System Settings > Privacy & Security.

Each ZIP includes the conversation runtime, installer, and installation guide. GitHub's **Source code** downloads do not include the runtime or installer. These are unsigned previews; both platform packages must pass automated build and installation verification before publication. SHA-256 checksums accompany the ZIPs. Codex updates independently of STEVE.
