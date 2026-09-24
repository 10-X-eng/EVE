# Experimental manufacturing checks

Enable **DFM** in STEVE's menu, then describe the manufacturing intent in chat.
There is one switch, initially off. Finish or pause a task before changing it.
Start a new conversation after installing this development build to register its
new tools. DFM is provider-independent and does not require another CAD service.

For example: "This bracket will be milled. Use my selected 6 mm end mill and
preserve the mounting-hole spacing. Check the part against that tooling."

STEVE can retain ordered process stages for each native body, with material,
notes and sourced numeric criteria. A part can be turned and then cross-drilled;
an assembly can contain parts made by different processes. Intent is supplied
through conversation, without a manufacturing-plan editor.
Ask STEVE to forget a selected part's manufacturing plan when it is no longer
applicable. This clears that native part's shared plan, including its repeated
instances, while retaining other parts and documents. Turning DFM off alone
retains plans for later use.

Saved-document plans persist locally across STEVE restarts. Unsaved-document
plans last only this session. Plans do not travel with shared Fusion documents.
Repeated occurrences share the native body's plan; placement, assembly context
and manufacturing orientation still need explicit consideration. A missing or
replaced body is not silently substituted.

## What is implemented

- `fusion_dfm_plan`: read/save bounded per-body context, or clear a requested
  part's plan with `stages=[]`, without editing Fusion.
- `fusion_dfm_check`: run read-only inspection code through STEVE's pinned Fusion
  execution path and return a report from measured comparisons.
- `fusion_api_help` at `steve.dfm` or `steve.dfm.<process>`: retrieve calling
  conventions and relevant process guidance without expanding every prompt.
- Criteria record units, source and whether they are a requirement, confirmed
  profile, guideline or assumption. Unconfirmed criteria remain conditional.
- Reports separate concerns, checked measurements and unknown coverage. Failed
  execution, missing revision information and geometry changes cannot validate
  a result. Historical chat reports refer only to their recorded body revision
  and configuration; recheck current geometry before relying on them.
- Native measurement helpers provide oriented envelopes, complete cylindrical
  wall bands, and downward planar face angles. The build axes are explicit;
  assembly transforms and support/brim/raft envelopes are not implicitly included.
  Open surface bodies return unknown for print-overhang classification because
  their normals do not establish the outside of printable solid material.
  Partial/intersected cylindrical faces and curved overhangs are reported as
  unsupported. A cylindrical band's axial span is not a complete-hole depth.
- A separate cylindrical-surface query measures analytic radii on partial faces,
  including rounded pocket corners. Pocket membership and approach must be
  established before comparing a radius with a cutter. Sharp corners and
  non-cylindrical surfaces remain unassessed; radius equality alone does not
  establish a suitable toolpath. Open surface bodies do not receive an inferred
  inside/outside classification.
- Native hole and pocket recognition adapters report missing APIs or extension
  access as unknown. Paging bounds results, not the duration of native Fusion
  calculations. No automatic cancellation of native recognition is attempted.
- Turning-axis checks classify analytic surfaces **and their trimming** as
  compatible, nonrotational or unknown. Read every face page. A compatible page
  does not prove a lathe setup, tool fit, stock allowance or workholding.
- Native sheet-metal inspection reads the folded-body flag, active rule and
  existing flat-pattern presence. Configured thickness is not a measurement;
  an imported solid is not assumed foldable.
- A normal-ray helper measures material at one interior face sample, requiring
  a confirmed solid interior and an exit on the same body. It does not find the
  global minimum wall thickness or qualify unsampled regions.
- Native closed-void shells provide resin/powder entrapment evidence. Missing
  shell volume remains unknown, never zero. An open cavity still needs process
  checks for escape-hole size, orientation, flow and washing. This criterion
  must not be transferred blindly to FDM or intentionally sealed designs.

Process guidance currently covers milling/drilling, turning, sheet metal, FDM,
resin and powder printing. Guidance is not a qualified algorithm library for all
those processes. Generated Python supplies measurements; validated numeric
comparisons cannot establish that the measurement algorithm itself is correct.
Read-only behavior is instructed, not sandbox-enforced. Native Fusion execution
and command-wait limitations remain the same as the ordinary query tool.

No universal manufacturing limits are built in. Actual profiles and requirements
must supply them. A passing dimensional check does not prove tool access,
fixture clearance, strength, successful printing, or full manufacturability.
Optional RMFG sheet-metal checks are described in [RMFG.md](RMFG.md). Native
checks remain available without a supplier account or geometry upload.

## Validation

Automated tests cover plan persistence and token resolution, unit/provenance
validation, conditional criteria, body revisions, bounded findings, switch
behavior and Fusion queue/runner integration with a host fixture.

A live Windows Fusion 2705.1.25 test exercised STEVE's actual plan and Python
runner in an isolated document with a 60 x 40 x 8 mm block. The checker measured
60 mm, correctly flagged a deliberately unmet 65 mm requirement, passed a 70 mm
envelope criterion, and reported unknown tool access. The body revision stayed
unchanged. `scripts/fusion_dfm_smoke.py` repeats this check inside Fusion against
that explicitly named fixture; it does not create or modify geometry. Its expanded
fixture includes a bottom-opening 4 mm diameter, 5 mm deep blind hole.

The live cylindrical-wall helper measured 4 mm diameter, 5 mm axial span and
62.831853 mm² area. Oriented envelope measurements were 60 x 40 x 8 mm and
40 x 60 x 8 mm with swapped build axes. Native hole recognition required an
inactive Manufacturing Extension on this installation and correctly returned
unknown. Successful native recognition is currently covered by contract fixtures,
not a live entitled run. Live planar-overhang checks found the blind-hole ceiling
and the lowest horizontal face, distinguishing the possible bed-contact face.
The rotated 40 x 60 x 8 mm envelope failed a 62 x 45 x 10 mm printer envelope;
the 60 x 40 x 8 mm orientation passed those dimensional comparisons. Curved
overhang coverage remained explicitly unsupported. A normal ray through the
blind-hole ceiling measured the independently known 3 mm remaining material.

`scripts/fusion_process_smoke.py` creates an additional disposable cylinder in
the named test document. All three faces of the 20 mm diameter, 40 mm long
cylinder were compatible with its axis. After a transverse cut, the checker
identified nonrotational surfaces and unsupported trimming; the old measurement
object rejected the changed revision. The original block remained unchanged.

`scripts/fusion_additive_smoke.py` creates a sealed cylindrical cavity inside a
separate cube, then opens it. Native shell topology detected the sealed void;
independent material-volume subtraction confirmed 50.265482 mm³ removed. A ray
measured its 3 mm ceiling. After opening it, no sealed void remained. This does
not establish practical resin drainage or powder removal. Fusion's inner-shell
token and volume getters raised internal validation errors on this fixture;
STEVE retains the valid topology finding and explicitly marks volume unknown.

The latter two scripts modify **only their new fixture components** and refuse
to run outside the explicitly named disposable test document or to duplicate
their existing fixtures. They are developer checks, not add-in entry points.

This is direct integration evidence, not broad manufacturing qualification or
macOS live qualification. Paired DFM-off/on real-model inspection and authorized
repair trials passed; both modes found and repaired the known defect, with the
enabled mode adding structured, sourced reporting. A native floating-point
boundary false concern was fixed and its exact generated check replayed.
Comparisons preserve raw values and disclose any allowance of up to eight
binary64 rounding steps; this is not a manufacturing tolerance.
Design-quality improvement, additional providers and embedded
panel workflows remain to be evaluated. See [DFM_EVALUATION.md](DFM_EVALUATION.md).

An opt-in inspection/repair benchmark is available as `scripts/dfm_model_probe.py`.
It uses STEVE's existing ChatGPT connection and an explicitly supplied loopback
development MCP endpoint, creates ephemeral model conversations, and compares
the same task with DFM off/on. By default its adapter allows only inspection and
local plan metadata. Explicit `--repair` creates two disposable child fixtures,
allows command edits, and independently verifies the resulting geometry and
preserved fixture revisions. Neither mode supplies upload capability.
This development script is not a product MCP dependency.
See the recorded validation results before treating it as a quality benchmark.
