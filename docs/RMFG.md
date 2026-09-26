# Optional RMFG sheet-metal DFM (experimental)

Open **Settings (⚙) → Manufacturing** and turn on **Design for manufacturing**. The
**RMFG sheet metal** section appears below it; choose **Connect RMFG**. Approve the
connection in your browser and return to Fusion. RMFG is a separate supplier
account; it does not replace your AI provider. STEVE restores the saved connection
on startup and refreshes expired access tokens automatically. **Connect RMFG**
also reuses an existing connection. **Check RMFG connection** reads
the saved connection and refreshes an expired access token. **Disconnect RMFG**
removes the local connection and attempts to revoke it with RMFG.

Ask STEVE to check a sheet-metal part with RMFG. STEVE saves its manufacturing
intent, reads RMFG's live material catalog, and prepares a folded STEP snapshot.
With RMFG connected and DFM enabled, STEVE automatically uploads that snapshot
and shows upload progress in the chat. No per-upload confirmation is needed.
Connecting alone uploads nothing; uploads happen when STEVE requests a supplier
check. Stopping before submission prevents upload. Once submitted, supplier
processing may continue even if STEVE stops.

The initial exporter accepts a component containing exactly one solid BRep body,
no meshes and no child occurrences. It refuses broader exports rather than sending
neighboring parts. Multi-body components and complete assemblies are unsupported.
STEVE must not restructure a user's model merely to evade this restriction.

STEVE matches the catalog to the material and thickness already established in
your request or manufacturing plan. It asks only when that choice is missing,
ambiguous, or unavailable, and submits DFM for every analyzed sheet-metal part.
It reads the report, applies appropriate fixes within your design intent, and
rechecks changed geometry. Processing may outlast a response; the saved job can
be checked again without uploading the same part twice. Reports
retain RMFG's ready/requires_input/blocked status, visible issues and pagination.
Unresolved requirements need review on RMFG. A supplier report is specific to
its snapshot, material configuration and ruleset; it is not a universal DFM pass.
Changed geometry requires a new snapshot and upload.

## Quote parts and open checkout

After installing an update that adds tools, start a new chat with **+** to use
them. Existing Codex chats retain the tool definitions they started with.

Ask naturally: “Quote two of this bracket and seven of that cover, then get them
ready for checkout.” STEVE uses the checked snapshots and established materials,
quotes the requested quantities together, reads the findings, and creates the
cart when its quote is ready. Unresolved supplier requirements stay visible;
STEVE does not silently accept manufacturing risks or substitute stock.

Choose **Open checkout** in the chat to review the quoted parts, delivery and
final pricing, then pay on RMFG. STEVE never charges a card. The cart contains
the quoted snapshots; later Fusion edits require new snapshots and a new quote.
Each supported part is exported separately; several such parts can share a cart.

Existing connections made with DFM-only permissions keep working for checks.
Choose **Enable quotes & checkout** in the RMFG account section once to grant
the additional permissions. Reconnecting binds future jobs to the new connection;
STEVE will need fresh checks for parts saved under the previous connection.

## Credentials, data and retries

- OAuth requests `designs dfm quotes carts`; it does not request payment access.
  Payment takes place on RMFG's website. Automatic risk acceptance is not exposed.
- Tokens stay outside prompts/logs and panel state, protected by Windows DPAPI
  or macOS Keychain. Refresh is serialized across instances. RMFG rotates its
  refresh tokens; an ambiguous refresh requires reconnecting rather than replaying
  a potentially consumed token.
- Local snapshots and job receipts are under STEVE's data directory in
  `rmfg-jobs`. They contain design data. Snapshots remain for identical retries. Storage is capped at 100 snapshots or
  200 MiB. Old records can be removed with STEVE stopped when no longer needed.
- Upload, DFM, quote and cart write keys are saved before network submission. An interrupted
  upload can resume with its original job ID, exact bytes and key.
  Do not create another upload to retry an uncertain result.
- Jobs survive an add-in restart, but are bound to the saved RMFG connection.
  Reconnecting establishes a new connection; earlier jobs are not reused under
  it. Unsaved Fusion document identity also lasts only that STEVE session.
- API redirects are refused. Sign-in and checkout buttons open validated RMFG links.
  Checkout links are fetched only when clicked; they stay out of prompts, logs,
  panel state and local receipts. Signed geometry URLs and supplier-internal issues
  are excluded from tool output.

## Validation and remaining limits

Offline tests exercise device-code polling, token rotation, cross-instance
credential locks, automatic uploads, cancellation before submission, immutable retries, stale revisions,
configuration ownership and report filtering. The browser regression test checks
the RMFG connection controls and the unchanged incremental chat renderer. Native credential
storage is exercised on its corresponding platform.

Quote/cart tests cover multiple parts and quantities, supplier configuration
defaults, pending/blocked/expired quotes, changed geometry, foreign results,
identical retries after interrupted writes, private-link handling and the checkout
button. These use controlled responses from the current REST contract; a live
supplier checkout has not been validated by these tests.

On Windows Fusion 2705.1.25, a local STEP export of the disposable one-body
fixture succeeded (10,641 bytes); its body revision was unchanged. The temporary
export was removed and no geometry was uploaded. This verifies the installed
export API, not RMFG's analysis of a formed sheet-metal part.

Live account authorization, a real sheet-metal supplier report, macOS Fusion
export and model-driven end-to-end use still need validation before release.

Protocol references: [RMFG API](https://www.rmfg.com/docs/api),
[agent guide](https://www.rmfg.com/docs/api/agent-guide.txt),
[OpenAPI schema](https://api.rmfg.com/v1/openapi.json).
