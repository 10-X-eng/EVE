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
tasks, multiple seeds, other providers, and additional process fixtures remain
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

## RMFG and platform status

Windows and macOS CI built and verified the foundation and RMFG packages. Native
Windows protected storage/locking and macOS Keychain round-trip tests passed on
their respective platforms. A local native STEP export passed without changing
geometry or uploading it. Actual RMFG browser authorization and a supplier report
for formed sheet metal are still pending. macOS Fusion behavior itself has not
been tested by these Windows live runs.
