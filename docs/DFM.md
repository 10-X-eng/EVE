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

Saved-document plans persist locally across STEVE restarts. Unsaved-document
plans last only this session. Plans do not travel with shared Fusion documents.
Repeated occurrences share the native body's plan; placement, assembly context
and manufacturing orientation still need explicit consideration. A missing or
replaced body is not silently substituted.

## What is implemented

- `fusion_dfm_plan`: read/save bounded per-body context without editing Fusion.
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

Process guidance currently covers milling/drilling, turning, sheet metal, FDM,
resin and powder printing. Guidance is not a qualified algorithm library for all
those processes. Generated Python supplies measurements; validated numeric
comparisons cannot establish that the measurement algorithm itself is correct.
Read-only behavior is instructed, not sandbox-enforced. Native Fusion execution
and command-wait limitations remain the same as the ordinary query tool.

No universal manufacturing limits are built in. Actual profiles and requirements
must supply them. A passing dimensional check does not prove tool access,
fixture clearance, strength, successful printing, or full manufacturability.
RMFG integration is planned separately; there is no account connection or upload
in this first block.

## Validation

Automated tests cover plan persistence and token resolution, unit/provenance
validation, conditional criteria, body revisions, bounded findings, switch
behavior and Fusion queue/runner integration with a host fixture.

A live Windows Fusion 2705.1.25 test exercised STEVE's actual plan and Python
runner in an isolated document with a 60 x 40 x 8 mm block. The checker measured
60 mm, correctly flagged a deliberately unmet 65 mm requirement, passed a 70 mm
envelope criterion, and reported unknown tool access. The body revision stayed
unchanged. `scripts/fusion_dfm_smoke.py` repeats this check inside Fusion against
that explicitly named fixture; it does not create or modify geometry.

This is direct integration evidence, not a model-driven design benchmark or
macOS live qualification. Broader process fixtures, paired DFM-off/on tasks,
provider behavior and embedded-panel interaction remain to be validated.
