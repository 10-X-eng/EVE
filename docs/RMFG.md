# Optional RMFG sheet-metal DFM (experimental)

Turn on **DFM** in the account menu, then choose **Connect RMFG**. Approve the
connection in your browser and return to Fusion. RMFG is a separate supplier
account; it does not replace your AI provider. **Check RMFG connection** reads
the saved connection and refreshes an expired access token. **Disconnect RMFG**
removes the local connection and attempts to revoke it with RMFG.

Ask STEVE to check a sheet-metal part with RMFG. STEVE saves its manufacturing
intent, reads RMFG's live material catalog, and prepares a folded STEP snapshot.
The chat shows the part name and size with **Upload to RMFG** and **Decline**.
Connecting does not upload geometry; each new snapshot needs that explicit click.
Declining or stopping before submission prevents upload. Once submitted, supplier
processing may continue even if STEVE stops.

The initial exporter accepts a component containing exactly one solid BRep body,
no meshes and no child occurrences. It refuses broader exports rather than sending
neighboring parts. Multi-body components and complete assemblies are unsupported.
STEVE must not restructure a user's model merely to evade this restriction.

After RMFG analyzes the geometry, choose the intended material through chat.
STEVE submits a standalone DFM configuration for every analyzed sheet-metal part.
Processing may outlast a response; ask it to check the saved job again. Reports
retain RMFG's ready/requires_input/blocked status, visible issues and pagination.
Unresolved requirements need review on RMFG. A supplier report is specific to
its snapshot, material configuration and ruleset; it is not a universal DFM pass.
Changed geometry requires a new snapshot and approval.

## Credentials, data and retries

- OAuth requests only `designs dfm`. No quotes, carts, purchases, payments,
  production files or acceptance of manufacturing risks are implemented.
- Tokens stay outside prompts/logs and panel state, protected by Windows DPAPI
  or macOS Keychain. Refresh is serialized across instances. RMFG rotates its
  refresh tokens; an ambiguous refresh requires reconnecting rather than replaying
  a potentially consumed token.
- Local snapshots and job receipts are under STEVE's data directory in
  `rmfg-jobs`. They contain design data. Declined snapshots are removed; approved
  snapshots remain for identical retries. Storage is capped at 100 snapshots or
  200 MiB. Old records can be removed with STEVE stopped when no longer needed.
- Upload and DFM write keys are saved before network submission. An interrupted
  approved upload can resume with its original job ID, exact bytes and key.
  Do not create another upload to retry an uncertain result.
- Jobs survive an add-in restart, but are bound to the saved RMFG connection.
  Reconnecting establishes a new connection; earlier jobs are not reused under
  it. Unsaved Fusion document identity also lasts only that STEVE session.
- API redirects are refused. Only RMFG approval links may open in the browser.
  Signed geometry URLs and supplier-internal issues are excluded from tool output.

## Validation and remaining limits

Offline tests exercise device-code polling, token rotation, cross-instance
credential locks, upload approval/decline, immutable retries, stale revisions,
configuration ownership and report filtering. The browser regression test checks
the upload card and the unchanged incremental chat renderer. Native credential
storage is exercised on its corresponding platform.

On Windows Fusion 2705.1.25, a local STEP export of the disposable one-body
fixture succeeded (10,641 bytes); its body revision was unchanged. The temporary
export was removed and no geometry was uploaded. This verifies the installed
export API, not RMFG's analysis of a formed sheet-metal part.

Live account authorization, a real sheet-metal supplier report, macOS Fusion
export and model-driven end-to-end use still need validation before release.

Protocol references: [RMFG API](https://www.rmfg.com/docs/api),
[agent guide](https://www.rmfg.com/docs/api/agent-guide.txt),
[OpenAPI schema](https://api.rmfg.com/v1/openapi.json).
