# DFM development evidence

These results describe the development branches, not a production qualification
of every manufacturing process. The tracked process issues remain open.

## Native Fusion cases

Windows Fusion **2705.1.25**, in the disposable **STEVE DFM development tests**
document. The customer document was not edited or saved.

| Case | Independent expected result | Observed result |
| --- | --- | --- |
| 60 × 40 × 8 mm block, Ø4 × 5 mm blind hole | Cylinder wall diameter 4 mm, axial span 5 mm | Measured correctly; no claim that every cylindrical band is a complete hole |
| 62 × 45 × 10 mm printer envelope | 60 × 40 × 8 orientation fits; 40 × 60 × 8 exceeds Y | Checked/concern respectively |
| Blind-hole ceiling | 8 − 5 = 3 mm material | Normal-ray measurement 3 mm, same-body exit |
| Downward planar faces | Hole ceiling above the lowest face | Both found, lowest-face candidate distinguished; curved face unsupported |
| 20 mm diameter × 40 mm cylinder | Rotational about its Z axis | All three faces compatible |
| Cylinder after transverse cut | Final part is not purely rotational | Nonrotational surfaces identified; interrupted trimming remained unknown |
| Sealed Ø4 × 4 mm internal cylindrical cavity | One sealed void; π × 2² × 4 = 50.265482 mm³ missing material | Void detected; independent total-body volume verified fixture size |
| Same cavity after a 2 mm opening | No fully sealed void remains | Correctly detected; no practical drainage claim |
| Native 2 mm sheet-metal plate | Native folded flag, configured 2 mm rule, existing flat-pattern state | Read correctly before/after explicit fixture flat-pattern creation; inspection changed no geometry |
| Reuse measurement object after geometry edit | Reject old revision | Rejected |
| Native hole recognition without Manufacturing Extension | Unknown coverage | Reported the missing entitlement, not “no holes” |

Two Fusion getters failed on a valid inner shell: `entityToken` and `volume`.
The checking path now uses revision-bound indices and preserves detected voids
when volume is unavailable. It does not substitute zero or mutate the model.

The first transverse-cut fixture attempt targeted the wrong location/body and
failed its expected outcome assertion. The development MCP rolled that transaction
back; an inspection confirmed no fixture component remained before a corrected
attempt. The reproducible script now maps model points into sketch space, sets
participant bodies explicitly and verifies feature health. On-demand API guidance
also explains these constraints to STEVE.

The sheet-metal fixture was prepared using Fusion's preview conversion API only
in the development session. That conversion is **not used by the distributed
DFM implementation**. The shipped helper reads existing native sheet-metal data;
it never converts a solid or creates a flat pattern during inspection.

## Paired real-model inspection

Two ephemeral conversations used STEVE's actual instructions/tools, **GPT-6-Astra**
at **medium** effort, and the same live fixture and prompt. The prompt required
at least 4 mm of remaining material above the blind hole and forbade geometry
changes. The adapter ran actual Fusion queries with read-only enforcement.

| DFM | Tool calls | Result |
| --- | --- | --- |
| Off | Inspect, helper documentation, two Python queries | Correctly reported 3 mm, a 1 mm shortfall, and unchecked machining concerns |
| On | Inspect, three documentation reads, query, plan read/save, DFM check | Same correct result, plus a sourced criterion and revision-bound report containing the concern and explicit unknown coverage |

This single pair demonstrates tool selection and end-to-end measured reporting.
It **does not demonstrate higher design quality or lower latency**: both models
answered correctly, and the enabled workflow used more calls. Design/edit/recheck
tasks across multiple seeds, other providers, and additional process fixtures remain
necessary to measure an improvement in design outcomes.

The off run passed `adsk.fusion.BRepBody` as a class to the selection helper,
which previously accepted only a string and returned a misleading target error.
The helper now accepts the SDK class, its `classType()` string or a dotted public
class path. Replaying the exact previously failing generated script passed on
the same live eight-face body, without changing geometry. Genuine type mismatches
still fail with distinct recovery guidance.

Run the opt-in probe with your existing STEVE ChatGPT connection and the local
development MCP URL supplied explicitly:

```text
python scripts/dfm_model_probe.py --account-only
python scripts/dfm_model_probe.py --mcp-url <your-loopback-MCP-URL>
```

It writes local traces under `.cache`, creates no permanent chat, and never
copies credentials. The development adapter is not installed as a STEVE dependency.
Protocol reference: [Codex app-server](https://learn.chatgpt.com/docs/app-server).

## Paired authorized repair

A second pair used the same model/effort and two fresh child components in the
disposable document. Both started with the 60 × 40 × 8 mm block and bottom-entry
Ø4 × 5 mm blind hole. The instruction allowed only top growth to the smallest
whole-millimeter height meeting the 4 mm ceiling requirement, while preserving
the footprint, bottom plane, hole dimensions and center.

Both runs changed the existing height to **9 mm** and remeasured a **4 mm** ceiling.
An independent verifier checked the final bounds, cylindrical surface, hole
depth/position, solid volume and preservation of every pre-existing fixture body.
Both passed. The DFM-on run retained a manufacturing plan and produced a
revision-bound check of the repaired geometry. The off run also repaired the part
correctly, so this pair proves the repair/recheck path, not superior design quality.

The enabled check exposed a false concern: Fusion returned
`4.0000000000000036 mm` for the unchanged nominal 4 mm hole. Comparison now accepts
a boundary difference of at most eight binary64 representable steps (ULPs), keeps
both raw values, and discloses the numerical window whenever it changes an outcome.
This is arithmetic roundoff handling, **not a manufacturing tolerance**. Larger
differences remain concerns; assumed criteria and unmeasured coverage remain
unknown. Replaying the exact generated check in Fusion passed all nine measured
dimensions and retained the explicit unknown tooling/workholding coverage.

Run this opt-in, mutating development trial only with the named disposable document
active and idle:

```text
python scripts/dfm_model_probe.py --mcp-url <your-loopback-MCP-URL> --repair --output .cache/dfm-repair-probe.json
```

The two trial components remain available for inspection. Other fixture revisions
are checked after each call. The adapter permits command edits but excludes
document switching, exports, supplier/network tools and viewport capture; both
model runs requested a final viewport image and received an unsupported-tool result.
The model was able to finish using measured geometry. This development adapter is
not a security sandbox or a substitute for testing the add-in's normal UI queue.

## Repeated and nested assembly fixtures

A mixed-body component contained a **2 × 1 × 0.125 inch** plate and a separate
turning body. Two more instances repeated that definition: one translated and
rotated 90° about Z, and one nested under a rotated parent with a second 90°
rotation. A temporary process store resolved all three plate proxies to the same
ordered plan, while preserving the other body's independent turning plan.

The test explicitly mapped an assembly build frame into native body coordinates
using each root-context occurrence's inverse `transform2`. Against a supplied
60 × 30 × 5 mm envelope, the original and 180° nested instance measured
50.8 × 25.4 × 3.175 mm and fit. The 90° instance measured
25.4 × 50.8 × 3.175 mm and exceeded Y. Independently expected translated bounds
matched each proxy; all pre-existing body revisions were unchanged.

The reproducible developer fixture is `scripts/fusion_assembly_dfm_smoke.py`.
This validates plan ownership, inch conversion and explicit frame handling. It
does not qualify arbitrary mixed-process sequences, assembly collision clearance,
or automatic print orientation selection. Guidance now gives the tested frame
conversion steps instead of relying on the model to infer them.

Reference: [Autodesk occurrence transforms](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_Occurrence_transform2.htm)
and [assembly proxies](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/ComponentsProxies_UM.htm).

A separate two-instance regression reproduced lost saved plans and a reverted
remembered switch when a stale store overwrote another instance's file. Plan
reads/writes now refresh persistent data under a nonblocking process lock; writes
use unique temporary files and atomic replacement. Unsaved-document plans stay
local, and another instance's preference change does not toggle an active task.
Tests cover interleaved saves, preserved preferences, lock contention and retry.
The exact live repaired-part check also passed through the updated store.

## Stepped turning fixture

`scripts/fusion_turned_profile_smoke.py` creates a separate full-revolve fixture:
outside bands Ø20 × 10 mm, Ø15 × 10 mm, Ø12 × 2 mm (groove floor), and
Ø15 × 18 mm, with a Ø4 × 40 mm axial through bore. All five native cylindrical
bands matched independently specified dimensions, including when read in pages
of two. Its measured volume matched the analytic radial-profile volume
**7813.140929478 mm³**. All ten faces were compatible with the intended axis;
an axis offset by 1 mm correctly produced nonrotational evidence.

The same measured maximum outside diameter was checked against explicit fixture
limits of 19, 20 and 21 mm: concern, pass and pass, respectively. Unspecified
workholding, stock, approach, reach and groove-tool fit remained unknown in every
report. These are synthetic supplied limits, not general turning recommendations.
All pre-existing bodies and the checked fixture's revision were unchanged by
inspection. This extends measured feature coverage; it does not prove a safe
turning setup, tool fit, imported-geometry coverage or improved generated parts.

## Local additive wall samples

`scripts/fusion_wall_samples_smoke.py` creates a stepped plate with independently
known **0.8, 1.2 and 2 mm** thick regions. The normal-ray helper measured all three
correctly. A separate deliberately overlapping body was placed on the thick
region's ray; a direct native ray query confirmed that the neighbor was hit before
the target body's exit. The helper correctly ignored it and measured 2 mm.

Supplied synthetic test limits exercise FDM, resin and powder report paths without
claiming material or supplier rules. The respective 1.2/0.8/1.5 mm test limits
produced concern/pass/pass, pass/pass/pass and concern/concern/pass at the three
sample points. The test script explicitly added unknown coverage for unsampled
regions; the report retained that unknown even when all three samples passed.
This is a native measurement/report-contract test, not a real-model trial or
proof that every generated inspection script will include sufficient coverage.

All pre-existing body revisions and both checked fixture bodies were unchanged by
inspection. Sampled wall thickness is not a global minimum, a validated print
profile, a strength calculation or slicer certification.

## RMFG and platform status

Windows and macOS CI built and verified the foundation and RMFG packages. Native
Windows protected storage/locking and macOS Keychain round-trip tests passed on
their respective platforms. A local native STEP export passed without changing
geometry or uploading it. Actual RMFG browser authorization and a supplier report
for formed sheet metal are still pending. macOS Fusion behavior itself has not
been tested by these Windows live runs.
