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

## Explicit applicability reporting

The evidence contract now supports `not_applicable` with a required reason and
evidence string. An all-not-applicable report retains that distinct status; it
does not become checked. Unknowns, concerns, failed execution and stale geometry
or plans retain precedence. Unit and queue/runner tests exercise those combinations
and evidence preservation. This validates the reporting contract, not the truth
of a model-written applicability judgment; unsupported measurements and missing
settings must still be reported as unknown.

## Existing native flat-pattern bend inspection

A disposable bent strip was created in the named test document: 2 mm wall,
R3 inside/R5 outside quarter bend, 25/30 mm straight legs and 20 mm width.
Its native volume was **2451.327412287183 mm³**, matching the independently
calculated cross-section volume. Analytic surface radii read 3 and 5 mm; inward
normal samples on both curved faces measured 2.0000000000000013 mm material.

Separate development setup converted this fixture to native sheet metal and
explicitly created its flat pattern. Conversion used an installed preview API
only in the local setup; no preview API is distributed in STEVE or the committed
fixture script. Before setup, sheet-metal/bend inspection correctly returned
unknown. The measurement query itself never converts or flattens anything.

On Fusion 2705.1.25, the existing flat pattern returned **two bend lines for one
physical bend**, on opposite sheet surfaces. Both reported 90 degrees and 20 mm
line length. `sheet_bends(limit=1)` followed by its `nextOffset` read both lines
without duplication or changes to any body revision. The native Python return
tuple and centimeter/radian conversions were exercised. The helper checks folded
body ownership, returns per-line failures as unknown and does not present line
count as a count of physical bends. Unit tests also cover missing/foreign patterns,
non-sheet bodies, missing wire geometry, invalid direction values and stale bodies.

`scripts/fusion_formed_sheet_smoke.py` creates only the guarded solid fixture.
Its `measure(component)` entry can recheck that fixture read-only before or after
explicit native sheet-metal setup. It refuses duplicate creation. The first
creation request exceeded the development HTTP observation timeout but completed
in Fusion; a read-only state check established this before further work, so it
was neither duplicated nor cancelled. All other fixture bodies remained unchanged
during setup; read-only inspection preserved every body revision.

This fixture validates measurement plumbing for one bend. It does not qualify
multi-bend parts, physical bend identification, relief, flange clearances,
springback, tooling/sequence, pattern currency or supplier acceptance.

## Selected trimmed-face distance validation

`face_distance(first_index, second_index)` measures two selected trimmed faces
through native MeasureManager. It does not enumerate candidate gaps, classify
intervening material, find directional clearances or substitute infinite planes.
It uses a root-context occurrence for component faces, requires a rigid transform,
maps the endpoints back to native part coordinates and rejects changed placement.
Unavailable native results remain unknown without a bounding-box approximation.

The first live run exposed `invalid argument geometryOne` for native component
faces; committing creation before inspection did not fix it. Explicit assembly
proxies did. The helper was corrected and then tested both at identity placement
and after rotating the disposable occurrence 90 degrees and translating it
70/-30/20 mm. Distances and native endpoint coordinates matched in both cases.
Native endpoint ordering did not consistently match the input faces, so the
result deliberately exposes an **unordered** endpoint pair.

Three U-section fixtures have independently specified 0.2/0.4/0.8 mm slots,
2 mm legs and base, and 5 mm extrusion. Native volumes matched 202/204/208 mm³.
Opposing slot walls and separate coplanar trimmed end faces both measured the
specified gap; infinite supporting planes of those end faces would incorrectly
give zero. A shared edge measured zero, while a pair across material measured
2 mm. Analytic construction and separate point-containment checks establish
air/material for these fixtures only, not a general classification algorithm.

Synthetic minimum-gap criteria of 0.4 mm were exercised through the actual DFM
runner for FDM, resin and powder stages. The 0.2 mm case produced a concern and
the 0.8 mm case passed its dimensional comparison. The nominal 0.4 mm case read
0.3999999999999959 mm: coordinate subtraction put it outside the existing narrow
binary64 comparison allowance. The face-distance guidance now requires an
**unknown boundary finding** when the measurement is within Fusion's modeling
tolerance of the criterion. It neither rounds away the raw value nor treats
modeling tolerance as a manufacturing allowance or certified uncertainty bound.
The boundary case stayed unknown for every process. Each report also retained
unknown actual manufacturing coverage, including when its dimension passed.

`scripts/fusion_face_distance_smoke.py` creates only the guarded fixture component;
call `measure(component)` separately for read-only checks. It rejects duplicate
creation. Existing body geometry was preserved during setup and every body
revision was preserved during inspection. Unit tests cover units, actual face
arguments, inverse placement, changed/nonrigid/unavailable placements, zero,
missing/malformed/failed native results, bad indices, stale bodies and cancellation.
This adds selected feature measurement evidence, not real print, fitting,
drainage, arbitrary geometry or manufacturing-process qualification.

## Tool contract and on-demand context review

All 13 STEVE tool descriptions were checked against their validators/handlers.
Repeated script-context text now lives at `fusion_api_help('steve.python')`;
purpose, required action relationships, ID provenance, defaults, side effects and
report interpretation remain visible in the relevant tool/schema. The core prompt
and tool inventory did not change. See [TOOL_CONTRACTS.md](TOOL_CONTRACTS.md) for
the per-tool review and runtime-registration evidence.

Compact JSON serialization of the complete tool schemas decreased from 14,144 to
10,910 characters (3,234 fewer, 22.9%). The 905-character script-context reference
loads when requested. These are schema character counts, not provider token
counts or a claim about full conversation size.

With the revised descriptions, a paired GPT-6-Astra/medium read-only test loaded
`steve.python` and `steve.helpers` in both modes, and `steve.dfm.milling` when
enabled. Both measured 3 mm remaining material and correctly reported failure of
the supplied 4 mm requirement without geometry changes. DFM-off used 4 calls in
20.140 seconds; DFM-on used 11 in 87.859 seconds. The latter guessed a nonexistent
`BRepFace.index`, received the installed-API recovery guidance, read the class help
and completed the inspection. No one-off warning was added to every tool for that
recovered API mistake. These are integration observations, not a latency or model
quality benchmark; no complete absence of ambiguity is claimed.

## Counterbores, intersecting bores and an open pocket

`scripts/fusion_milling_topology_smoke.py` creates three guarded disposable
fixtures. A separate read-only `measure(design)` invocation passed on Fusion
2705.1.25, preserving all body revisions. Independent analytic volumes matched
native geometry within 0.00001 mm³:

- A 20 × 20 × 12 mm block with a 4 mm through bore and an 8 mm counterbore
  3 mm deep measured 4536.106217098447 mm³. Full-band inspection returned
  internal diameter/span pairs of 4/9 and 8/3 mm, including one-item pagination.
  The narrow band's 9 mm span is not the complete 12 mm through-hole path.
  Native hole recognition returned unknown because the Manufacturing Extension
  was inactive; the result included the supported-band recovery guidance.
- A 10 mm cube with intersecting perpendicular 4 mm bores measured
  791.3392543794886 mm³, matching the cylinder subtraction plus their analytic
  intersection volume. All four cylindrical faces retained measurable R2
  internal surfaces, but every trimmed band was unsupported. No complete hole
  or full-band depth was inferred from those partial faces.
- A 20 × 20 × 10 mm block with an open 10 × 10 × 5 mm pocket measured
  3500 mm³. All faces were planar, so the cylinder helpers returned no candidates.
  Separate edge geometry and point containment established the two sharp inner
  corners and the open side for this fixture. Native pocket recognition returned
  one pocket, depth 5 mm, `isClosed=false`, `isThrough=false`. This is a successful
  installed native pocket-recognition call; it does not establish hole-recognition
  access or arbitrary pocket coverage.

Each actual DFM runner report retained an explicit unknown for complete machining
coverage. A second open-pocket query returned zero cylindrical candidates and
recorded no findings: its report correctly remained incomplete. Empty candidates
therefore did not create a passing report. These checks exercise existing behavior;
they add no prompt text, tools or manufacturing thresholds. Tool approach, reach,
holder clearance, workholding, NURBS corners and broader feature recognition remain
unqualified. No customer geometry was changed during fixture setup.

## Provider switch and disabled-tool enforcement

`tests/test_dfm_provider_runtime.py` exercises three complete on/off/on
conversations through the real local Codex runtime and STEVE's Claude, Grok and
Ollama transports. Provider inference is scripted through loopback fixtures;
Claude uses its actual Responses adapter, and Ollama retains its actual
model/context preparation with fixture metadata. No subscription credentials,
paid inference, supplier calls or live Fusion are used.

The tests use the actual controller, manufacturing plan store and queued Fusion
Python runner with a fake Autodesk host. Each enabled conversation saves an FDM
plan, compares a scripted 0.8 mm sample with an explicit 1.2 mm requirement and
records unknown manufacturing coverage. While disabled, the scripted provider
deliberately attempts all four DFM/supplier tools. Every attempt receives
`dfm_disabled` with `executionStarted=false` and ordinary-tool recovery guidance;
none reaches the Fusion submission queue or supplier service. Re-enabling reads
the original plan and checks it in the same chat, with the same plan hash.

Captured outbound provider requests show the latest switch value and pinned
document each time, with the private task key omitted. The four tool definitions
remain registered in every phase, so re-enabling needs no chat replacement.
Reports preserve both the dimensional concern and explicit coverage unknown;
no mutating Fusion command executes. All three local runtime tests passed.

This establishes delivery, gating and retained-plan behavior for these adapters.
The sample dimension is scripted, not a CAD measurement; the provider fixtures
do not establish real-model instruction following or manufacturing quality.
ChatGPT live model evidence is recorded separately above. Native Fusion and
independent manufacturing qualification remain separate gates.

## Sourced machine definitions and nominal FDM envelopes

Machine capabilities now load from separate JSON files and are selected per stage
by ID/content hash. There are no printer limits in the DFM execution code. The
first two definitions record official nominal XYZ envelopes for MK4S and the
original CORE One, with scope/source/date and explicit unverified areas; see
[MACHINES.md](MACHINES.md). Catalog discovery uses existing API help, not another
tool. Machine comparisons preserve source/scope and reject relation inversion,
reserved-key overrides, missing definitions, changed hashes and wrong processes.

On Fusion 2705.1.25, `scripts/fusion_sourced_envelope_smoke.py` created three
guarded test bodies and separately measured eight machine/orientation cases.
The 218 × 200 × 10 mm plate measured 436,000 mm³. At a quarter turn, its build
Y extent of 218 mm exceeded MK4S's 210 mm but fit CORE One's 220 mm. Upright fit
both nominal envelopes. A 250 × 20 × 10 mm boundary body fit nominal X exactly;
a 251 × 20 × 10 mm body exceeded both. Native volumes were 50,000 and 50,200 mm³.
All measured dimensions matched analytic fixture expectations. Every report kept
printing outcome unknown; fitting dimensions did not produce a printability pass.
Setup preserved existing bodies and inspection preserved every body revision.

Unit/runner checks cover definition validation, persisted old references, explicit
refresh, unavailable files, change during a check, historical binding status,
source/scope, and attempts to replace or invert limits. These validate selected
nominal capabilities; no physical printer, slicer outcome or complete machine
capability profile has been qualified.

### Resin and polymer SLS machine definitions

Separate Formlabs Form 4 and Fuse 1+ 30W files add resin and polymer SLS nominal
envelopes, sourced on 2026-09-24. The catalog records the Fuse chamber's rounded
corners and material/settings-dependent usable-volume restrictions explicitly;
it supplies no general powder-process or material qualification. See the source
links and exact limitations in [MACHINES.md](MACHINES.md).

The existing sourced-envelope script now measures 24 cases across four machines,
reusing the three plate bodies and original 60/40/8 mm block without new geometry.
It also measures the 250/20/10 mm plate on edge as 20/10/250 mm: within Fuse's
nominal XYZ limits, but exceeding Form 4's Z limit by 40 mm. The small block is
within both nominal boxes; the 218/200/10 mm plate exceeds both in the upright
frame. All 24 native measurements matched independent expected extents on Fusion
2705.1.25, and all body revisions remained unchanged. Every report retained an
explicit unknown print outcome; dimensionally passing cases stayed incomplete.

Catalog tests cover below/equal/above limits, all wrong process-family selections,
missing wall capabilities and retained process restrictions. No physical print,
material profile, rounded-chamber fit algorithm or PreForm validation was tested.

## RMFG and platform status

Windows and macOS CI built and verified the foundation and RMFG packages. Native
Windows protected storage/locking and macOS Keychain round-trip tests passed on
their respective platforms. A local native STEP export passed without changing
geometry or uploading it. Actual RMFG browser authorization and a supplier report
for formed sheet metal are still pending. macOS Fusion behavior itself has not
been tested by these Windows live runs.

## Machine currency across a complete plan

A regression reproduced a mismatch between fresh reports and historical plan
bindings: changing/removing the machine definition referenced by another stage
left the running check's configuration marked current, while a plan read returned
stale/unknown. Both paths now use the same complete-plan machine currency check.
Changed definitions invalidate findings as stale; missing/invalid definitions
leave findings unknown and the report incomplete. Measurements, original limits
and assessed plan hashes remain intact, and generated code executes only once.

Queue/runner tests change real temporary JSON definitions after measurement,
covering references before/after the checked stage, missing/invalid definitions
and an unrelated catalog change that must not invalidate the plan. The bridge
test imports were also ordered so an isolated test run patches the same catalog
module used by the runner, removing a dependency on full-suite import order.

On live Fusion 2705.1.25, an unchanged 60 mm fixture measurement remained checked
with unchanged definitions, became stale when a later stage's definition changed,
and became incomplete/unknown when that definition disappeared. All three cases
agreed with their subsequent historical bindings, preserved the original plan
hash, and executed once. Every body revision remained unchanged; only isolated
temporary test definitions were modified. This validates report currency rather
than manufacturing capability or physical machine configuration.
