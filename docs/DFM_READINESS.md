# DFM implementation and qualification status

The DFM preview is experimental. The process issues remain open; passing
unit tests, package CI or individual geometry fixtures does not qualify a
manufacturing process. PRs #31–#47 were merged in dependency order for the 0.6.0
preview; their implemented scope and remaining qualification are listed below.
The 0.6.1 follow-up merges #49–#51: paired additive machine discovery, consistent
currency checks across all planned machines, and sourced Form 4/Fuse 1+ nominal
envelopes. These additions do not close the manufacturing qualification gates.

## Shared workflow

Implemented: one remembered switch, initially off; conversational per-body plans
with ordered stages; native identity across repeated occurrences; sourced criteria;
bounded reports; geometry and plan currency; and explicit pass, concern, unknown
and evidence-backed not-applicable findings. Inspection uses the existing pinned
Fusion query runner and does not authorize edits. Process guidance is loaded on
demand. General DFM requires neither a supplier login nor a product MCP connection.
Machine definitions live in separate sourced JSON files and bind plan stages by
content hash. Initial printer envelopes and the extension contract are documented
in [MACHINES.md](MACHINES.md); absent machine capabilities remain unknown.

The reports describe the code's stated measurements and applicability judgments.
They cannot establish that arbitrary generated code inspected every relevant
feature correctly. Unknown inputs, unsupported geometry and incomplete scans must
remain unknown, not be labeled not applicable. An all-not-applicable report is
not a passing manufacturing assessment.

## Process evidence and remaining work

| Issue | Implemented and exercised | Remaining qualification or implementation |
| --- | --- | --- |
| #24 Foundation | Saved/session plans, shared-instance updates, stage ordering, native identity, clear/reset semantics, source/unit checks, failed/stale reports; live query/edit/recheck cases; actual-runtime Claude/Grok/Ollama on/off/on delivery and enforcement with scripted inference/fake CAD | Broader real-provider/panel workflows and independently reviewed outcome corpus; live macOS Fusion |
| #25 Milling/drilling | Full cylindrical bands, partial cylindrical radii; native and SAT-imported pocket/shaft measurements; counterbore spans and intersected-band rejection; successful native open-pocket recognition, missing-extension hole handling and sharp-pocket empty-candidate reporting; library-derived cutter criterion; two paired model repair cases | Broader recognition and entitled hole recognition, tooling/reach/workholding qualification, general sharp/NURBS corner detection and measured design-quality improvement |
| #26 FDM/FFF | Explicit build-frame envelopes, rotated/repeated assemblies, planar underside slopes, sampled walls and open-surface rejection; selected trimmed-face distances on known slots before/after rigid placement; synthetic boundary profiles | A confirmed printer/material profile; broader fine-feature, directional/assembly clearance and support/bridge coverage; paired additive design outcomes and independent printing review |
| #27 Sheet metal/RMFG | Native rule and existing flat-pattern metadata; paged native bend lines on a 2 mm bent-strip fixture (R3 inside, 90 degrees, 20 mm bend lines); single-body STEP export; optional OAuth, protected storage, upload approval, immutable retry jobs and scoped reports | Multi-bend/relief/sequence and tooling qualification; real account authorization and approved supplier upload/report with an actionable finding; live macOS export |
| #28 Turning | Axis/trimming classification and full bands on native/SAT stepped shafts with a groove and bore; wrong-axis rejection and sourced diameter boundaries | Machine/tool/workholding profile, tool approach/reach/groove fit, interrupted and more complex turning fixtures, paired design outcomes |
| #29 Resin | Build frame, sampled walls, closed-void screening; sealed/open cavity fixtures, unavailable-volume handling and selected face distances with synthetic slot criteria | Confirmed resin/machine/support intent; multiple-opening/flow/suction-cup and broader fine-feature coverage; paired resin outcomes |
| #30 Powder | Shared envelope/wall/closed-void and selected face-distance measurements with process-specific guidance and synthetic profiles | Select and qualify one actual polymer or metal process/profile; escape passages and removal evidence; post-processing, broader fine features and paired outcomes. No powder variant is production-qualified |

Detailed measurements, fixture commands, failure observations and boundaries are
in [DFM_EVALUATION.md](DFM_EVALUATION.md). Supplier authorization and data handling
are in [RMFG.md](RMFG.md).

## Evidence that cannot be inferred

- Five paired model runs have exercised milling inspection (including a repeat
  after the tool-description audit), two authorized milling repairs and FDM
  machine/envelope discovery on unchanged geometry.
  Both modes succeeded in every recorded pair. The results support integration;
  they do **not** establish better design quality with DFM enabled. The overall
  improvement target needs a manufacturing-reviewed, held-out task set and frozen
  scoring criteria before it can be evaluated honestly.
- Windows live Fusion runs and Windows/macOS package CI are different evidence.
  macOS package tests do not establish live Fusion behavior on macOS.
- A local STEP export and offline RMFG contracts do not establish that a real
  supplier accepts the part or produces an actionable DFM report. Account sign-in
  and a separately approved snapshot upload are still required for that test.
- Analytic SAT round trips do not establish STEP import or arbitrary supplier-file
  support. The development MCP's command callback cannot run ImportManager's STEP
  import; its attempted idle dispatch was rejected and cleaned up.
- Synthetic dimensional limits exercise comparisons without inventing a universal
  manufacturing rule. They are not validated printer, resin, powder or shop profiles.

## Implementation history

The merged PRs formed one ordered stack: foundation (#31), optional supplier path
(#32), native process geometry (#33), shared state/assemblies (#34), partial radii
(#35), build orientation (#36), report currency (#37), imported solids (#38),
paired pocket repair (#39), reference discovery (#40), applicability/readiness
(#41), existing-pattern bend inspection (#42), selected face distances (#43),
the tool-contract/on-demand-context review (#44), milling topology fixtures (#45),
provider toggle integration tests (#46), and machine definitions (#47).
The combined main checkout matched the tested final branch and passed 381 Python
tests (11 skipped), panel/image checks, a real-browser streaming check and the
145-file portability audit. Package CI is distinct from process qualification.

The local source add-in contains this stack under `addin/STEVE`. Loading the source
add-in and starting a new conversation exposes the new tool definitions. This is
separate from building or publishing an installer.

The tool-description audit and dynamic-tool registration constraints are recorded
in [TOOL_CONTRACTS.md](TOOL_CONTRACTS.md).
