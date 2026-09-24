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

The plan tool also supports an explicit requested clear with `stages=[]`. Store
and queue tests verify native/proxy identity, preservation of other parts and
documents, idempotence and missing-plan recovery on the next check. A live Fusion
temporary plan was saved, cleared and read back as absent with unchanged geometry.

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

## Partial cylindrical pocket corners

`scripts/fusion_pocket_radius_smoke.py` creates a 40 × 30 × 10 mm block with a
20 × 10 × 5 mm rounded pocket and independently specified R1 corners. The new
`cylindrical_surfaces` helper measured all four partial cylindrical radii as
1 mm, classified them as internal using solid-face normals, and returned the
expected vertical axes through paged queries. Independent quarter-cylinder areas,
axial bounds and analytic remaining volume matched. The original full-band query
still rejected all four partial faces, so this does not weaken its recognition.

The test identified the intended pocket faces from the fixture and compared their
radii with supplied cutter radii of 0.5, 1 and 3 mm: all four dimensional comparisons
passed for the first two tools and raised concerns for the 3 mm radius. Every
report retained unknown machining-strategy/clearance coverage, including at equal
radius. Those are synthetic fixture tool inputs, not general recommendations.
All pre-existing bodies and the inspected fixture revision were preserved.

This query measures analytic surface radii without requiring the feature-recognition
extension. It does not itself identify pockets, sharp zero-radius corners, complete
holes, NURBS curvature, reach or tool clearance. No matches is not proof that a
part has no problematic corners. Unit tests also confirm that open surface bodies
and unavailable normals retain unknown inside/outside classification.

Reference: [Autodesk B-Rep geometry and solid-face normals](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/BRepGeometry_UM.htm).

## Library-derived cutter criterion

A read-only local Fusion test retrieved one selected flat end mill from an existing
tool library. Its JSON declared `inches`: `geometry.DC` of 0.5 and `LCF` of 1
converted to a 12.7 mm diameter and 25.4 mm flute length. A temporary DFM plan
retained the library/item provenance, source field and unit, and used the derived
6.35 mm cutter radius against the four independently identified R1 pocket corners.
All four comparisons raised concerns. Setup safety remained unknown; flute length
was not treated as safe reach. All existing body revisions were unchanged, and no
tool, setup or user DFM plan was changed.

This checks the measurement/report path with a real library entry; it is not a
model tool-selection trial or evidence that the cutter is physically available.
CAM help now distinguishes numeric parameter units (cm/degrees), expression
units, and a tool JSON's own declared units. Unsupported tool types and missing
units still require investigation rather than guessed conversions.

Reference: [Autodesk CAM parameters and tool JSON](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/CAMParameters_UM.htm).

## Build orientation and unsupported surface bodies

`scripts/fusion_build_orientation_smoke.py` inspects the existing blind-hole block
without changing it. Independently expected underside slopes matched in four
frames: upright (two 0-degree faces), upside down (one), sideways (one), and
30 degrees about X (30/30/60 degrees). Each axis-aligned placement had one lowest
horizontal bed-contact candidate; the tilted frame had none. Pagination at one
result per page preserved the curved hole wall as unsupported in every frame.

Synthetic minimum-slope profiles of 29/30/31 degrees exercised below, equal and
above-boundary comparisons. The first two passed the three planar comparisons;
31 degrees raised two concerns. The unmeasured curved wall and printing outcome
remained unknown. These limits are test inputs, not recommended printer settings,
and the test does not calculate bridge spans, supports, adhesion or slicer output.

An adjacent bug allowed the same classifier to use open-surface normals even
though they do not establish the outside of printable solid material. It now
returns unknown before classifying such a body. Unit tests cover this guard,
revision invalidation and unavailable normals across pages.
`scripts/fusion_surface_dfm_smoke.py` also verified the guard in live Fusion by
copying one planar face into a separate disposable surface component. Inspection
did not change that surface; both scripts verified all pre-existing body revisions.

## Manufacturing-plan currency

The DFM runner now re-reads the part's full ordered plan after inspection. A
second STEVE instance can update saved plans, so checking only the native geometry
revision was insufficient. Changes to another process stage, stage ordering or
plan removal now mark the result stale and preserve its raw measurements as
unknown evidence. A contended/unreadable plan leaves the report incomplete without
rerunning the inspection. Report metadata records the assessed plan hash, stage
index and document. Plan reads expose current revision/hash bindings for comparing
historical reports. The public stage snapshot cannot relabel the criteria used by
earlier measurements through accidental dictionary edits.

Queue/runner tests use a separate store instance to change, reorder and remove
saved plans between measurement and report construction. They also cover a failed
plan re-read, unchanged plans, later geometry changes and retained measurement
values. The live `scripts/fusion_dfm_currency_smoke.py` uses real native geometry
with temporary session plans: an unchanged 60 mm envelope comparison is checked;
changing the second process stage or clearing the plan makes the same comparison
stale. All measured values and original criteria remain in the report, and every
existing body revision is preserved. No user settings or geometry are changed.

These bindings cover recorded plans and native body geometry. They do not track
external library edits, machine state or occurrence placement automatically, and
do not retroactively rewrite chat history or certify a generated algorithm.

## Imported neutral-format solids

`scripts/fusion_imported_dfm_smoke.py` exported the rounded pocket and stepped shaft
to temporary SAT files with `TemporaryBRepManager.exportToFile`, read them back
with `createFromFile`, and persisted each returned solid in its own base feature.
The resulting bodies have no source sketch/extrude history. This is an actual
native file round trip, not a copy-only geometry mock.

The imported pocket retained four internal R1 cylindrical corners and the
independently expected **11004.292036732051 mm³** volume. The imported shaft
retained its five expected cylindrical bands, including the Ø4 × 40 mm axial
bore, and **7813.140929477482 mm³** volume. All ten shaft faces were compatible
with the intended turning axis; paged band and face queries completed. Every
pre-existing body revision and each imported body's inspected revision remained
unchanged. Only the two explicitly named disposable import components were added.

This covers these analytic SAT solids, not arbitrary supplier files, healing,
split/NURBS replacements or STEP import. The separate STEP ImportManager method
cannot run in Command events. A development idle-event dispatch was rejected;
its event was unregistered and inspection confirmed no STEP imports were created.
No native computation was cancelled. STEVE's on-demand ImportManager guidance now
directs authorized imports through its application execution mode and requires
inspection of possible partial results before retrying; that STEP path still
needs a live test outside the development MCP's command callback.

References: [temporary B-Rep file import](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_TemporaryBRepManager_createFromFile.htm),
[temporary B-Rep export](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_TemporaryBRepManager_exportToFile.htm),
[ImportManager command-event limitation](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_ImportManager_importToTarget.htm).

## Paired base-body pocket repair

A third paired model task used two fresh base-body copies of the rounded pocket,
without source sketch parameters. Both received the same confirmed R3 requirement
and permission to change only the four R1 corner blends, retaining the 40 × 30 ×
10 mm outer block, pocket bounds X=10..30 / Y=10..20 mm, floor Z=5 mm and opening
Z=10 mm. Both used GPT-6-Astra at medium effort with the same 24-call/300-second
limits and STEVE instructions/tool definitions through the development adapter.

| DFM | Tool calls | Observed elapsed time | Independent geometry outcome |
| --- | --- | --- | --- |
| Off | 14 | 71.531 seconds | Passed |
| On | 15 | 92.907 seconds | Passed |

Both healed the old corner blends and created editable R3 fillets. Independent
checks read native geometry directly, without using the generating model's check
report or DFM measurement helpers: all four quarter-cylinder radii, axes, positions,
areas and depth bounds; outer bounds; flat-floor bounds; topology; and analytic
remaining volume **11038.628330588459 mm³** matched. All pre-existing fixture
bodies remained unchanged. This verifier is specific to this analytic shape and
is not a general equivalence or manufacturing-certification algorithm.

The enabled run saved the sourced radius requirement and checked the edited
revision, retaining unknown tooling, reach, collision, workholding and manufactured
accuracy. Its nominal R3 measurements were `3.0000000000000004` mm; the disclosed
binary64 boundary handling correctly avoided a false concern. Both runs reported
unchecked manufacturing conditions and neither saved/exported/uploaded a document.

This is another successful design/edit/recheck integration case, **not evidence of
better generated geometry with DFM enabled**: both repaired the part correctly,
and the enabled run was slower in this one pair. The development adapter does not
provide viewport capture; each run requested it once and received an unsupported
response. The off run also recovered from one missing API-class lookup. Those
calls are included in the counts; timings are observations, not a performance
benchmark. A manufacturing-reviewed held-out corpus remains necessary.

Reproduce with the existing disposable rounded-pocket fixture. This command creates
and edits two additional test components:

```text
python scripts/dfm_model_probe.py --mcp-url <your-loopback-MCP-URL> --pocket-repair
```

`--pocket-repair` and `--repair` are mutually exclusive. Local traces include the
scenario, elapsed time, generated tool calls and independent verification results.

## Current API reference discovery

Installed API help and installed-class search now supply namespace-prefixed web
reference candidates for core, fusion and cam classes/members. These candidates
are explicitly unverified until fetched; discovery performs no network I/O on
Fusion's thread. Missing-page recovery distinguishes obsolete page naming from
an unavailable installed API and directs the model to class-page links.

A live end-to-end check obtained paths from Fusion's installed API and fetched
them with STEVE's bounded documentation reader: `ImportManager.importToTarget`,
`TemporaryBRepManager.createFromFile` and `Tool.toJson`. All three current pages
loaded and contained their expected API details. Unit tests cover naming, unsafe
or unsupported paths, the unverified flag, and discovery without method invocation
or network access. This verifies these references, not every generated candidate.

## RMFG and platform status

Windows and macOS CI built and verified the foundation and RMFG packages. Native
Windows protected storage/locking and macOS Keychain round-trip tests passed on
their respective platforms. A local native STEP export passed without changing
geometry or uploading it. Actual RMFG browser authorization and a supplier report
for formed sheet metal are still pending. macOS Fusion behavior itself has not
been tested by these Windows live runs.
