# Open-source DFM reuse assessment

Research date: September 24, 2026. Scope: STEVE's proposed optional, per-part,
multi-process DFM in issue #23. This is a source and documentation assessment,
not a completed runtime qualification or an integration decision.

## Finding

There are mature open-source geometry/CAM components worth reusing. This search
did not establish a complete open-source DFM package with demonstrated production
readiness across milling, turning, and sheet metal that we can simply embed.
The best-established projects solve portions of the problem; the more complete
DFM applications need qualification, or reserve important functions for commercial
extensions. Repository activity and a feature list alone are not validation.

Production suitability here means supported Windows/macOS deployment, actual
geometry algorithms, realistic regression coverage, explicit failure/unknown
states, maintained dependencies, usable licensing, and evidence of real use.
Even a mature library needs qualification for STEVE's particular checks.

## Shortlist

### 1. Analysis Situs: recognition library with substantial native Fusion overlap

Its open-source core includes STEP/BREP handling, an attributed adjacency graph,
and recognition of holes, cavities, and blends. The project states that its
algorithms have been used in industrial and automatic-quotation systems; that is
vendor-reported deployment evidence, not an independent audit. The core is BSD-3-Clause.

The important boundary is the project's own [capability matrix](https://analysissitus.org/):
dedicated milling/turning recognition, thread detection, thickness/clearance,
accessibility, and sheet-metal recognition/unfolding/bend-sequence functions are
listed as commercial extensions. Do not budget those as free SDK capabilities.

The published [test report](https://analysissitus.org/results/summary.html) shows
514 passing tests and 18 known problems, generated December 18, 2025. Useful
evidence of a regression suite, but not a current all-green qualification.

**Assessment:** do not add it for capabilities Fusion already supplies. Fusion's
CAM API exposes hole and pocket recognition, including use from the Design
workspace. STEVE can call exposed APIs through its existing Python tools, though
it does not currently have a dedicated, tested recognition stage. Extension
entitlements must be checked. Existing design fillet features and recognition of
arbitrary blends on imported solids are separate capabilities; do not assume
identical API coverage. Consider Analysis Situs only for a demonstrated gap.
It is a C++/OCCT integration project, not a Fusion Python drop-in. A verified macOS
ARM build and a restricted inventory of genuinely open algorithms would be gates.

Native baseline: [Fusion feature recognition API](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/FeatureRecognition_UM.htm),
[recognized pockets](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/RecognizedPocket.htm),
[Find Features UI](https://help.autodesk.com/cloudhelp/ENU/Fusion-Model/files/GUID-C651DB91-81DC-43F6-90E9-52540DCA0C40.htm).
The UI documentation alone does not establish a callable Python equivalent.

Sources: [SDK and license](https://analysissitus.org/get_started.html),
[recognition architecture](https://analysissitus.org/features/features_feature-recognition-framework.html),
[industrial-use claims](https://analysissitus.org/faq.html),
[source repository](https://gitlab.com/ssv/AnalysisSitus).

### 2. OCCT with OCP/CadQuery: mature geometry infrastructure

OCCT provides CAD geometry, topology, data exchange, and modeling infrastructure.
The current stable release inspected was [8.0.1](https://github.com/Open-Cascade-SAS/OCCT/releases/tag/V8.0.1),
published July 30, 2026. CadQuery's current inspected release was
[2.8.0](https://github.com/CadQuery/cadquery/releases/tag/v2.8.0), June 20, 2026.
Open Cascade's [CAD Assistant](https://www.opencascade.com/products/cad-assistant/)
is a concrete product built using the open-source kernel.

**Assessment:** credible production infrastructure for an external geometry
worker, but not a DFM rules engine or manufacturing-feature recognizer by itself.
Fusion already gives STEVE native geometry APIs, so adding another kernel needs
a specific benefit, such as an algorithm that is otherwise unavailable.

CadQuery and the OCP wrapper use Apache-2.0; the underlying OCCT uses
[LGPL-2.1 with an additional exception](https://www.occt3d.com/dev/doc/overview/html/occt_public_license.html).
Do not infer the complete binary distribution's license from the Python wrapper.

### 3. FreeCAD SheetMetal: established sheet-metal algorithms

The [SheetMetal workbench](https://github.com/shaise/FreeCAD_SheetMetal) has a
development history extending to 2015, multiple contributors, folding/unfolding
algorithms, bend allowances, and material/K-factor handling. Its inspected
[package metadata](https://github.com/shaise/FreeCAD_SheetMetal/blob/master/package.xml)
is version 0.8.23, dated September 13, 2026. It is distributed through FreeCAD's
Addon Manager; the old GitHub release entry is not its current package version.

**Assessment:** excluded from STEVE's recommended integration route following
maintainer feedback on quality. Its history is not proof of a manufacturable
press-brake sequence. FreeCAD's Part
objects and application APIs differ from Fusion's, so reuse requires a port or
an external FreeCAD worker. Prefer Fusion's native flat-pattern information when
it already supplies the needed measurement.

Current package/LICENSE identify LGPL-2.1-or-later; the changelog records a 2024
relicense. A README section still says GPLv3. Verify the exact files and notices
being reused rather than relying on that stale summary.

### 4. FreeCAD DFM Workbench: useful architecture, not yet qualified

[DFM Workbench](https://github.com/ryankembrey/FreeCAD-DFM-Workbench) separates
geometric analyzers, rule checks, configurable processes/materials, and displayed
results. It includes thickness, draft, undercut, and corner analyses. Injection
molding is the supplied process profile; configurable processes do not establish
validated milling, turning, and sheet-metal rule packs.

Inspected commit: `8b1d3973c1abc564ddee713aeff197a55312a9dc`.
[Package version](https://github.com/ryankembrey/FreeCAD-DFM-Workbench/blob/8b1d3973c1abc564ddee713aeff197a55312a9dc/package.xml):
0.1.21, September 16, 2026. Source review found 27 test methods across two analyzer
test files, using real OCP primitives. The inspected workflow directory contained
documentation CI, not an analyzer-test workflow. I did not execute these tests.

There is an open [Windows/OCP 8 compatibility report](https://github.com/ryankembrey/FreeCAD-DFM-Workbench/issues/94)
where the workbench cannot import a required OCP class. This is evidence of a
specific dependency problem, not proof that every installation fails.

**Assessment:** excluded from STEVE's recommended integration route following
maintainer feedback on quality; not established as a production-qualified DFM
backend by this review. Some core analyzers
operate on OCP shapes separately from the UI, which is a useful integration seam.
The workbench uses LGPL-2.1-or-later and declares OCP and Gmsh dependencies.
Gmsh has its own GPL license.

### 5. OpenCAMLib: established CAM building block, limited DFM fit

[OpenCAMLib](https://github.com/aewallin/opencamlib) supplies cutter-contact and
toolpath algorithms, with C++/Python bindings and Windows/macOS binary releases.
FreeCAD documents its use for [surface machining](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/CAM_Surface.md).
Its latest inspected GitHub release was January 11, 2023; the repository's most
recent push was February 12, 2025. License: LGPL-2.1.

**Assessment:** potentially useful later for a narrowly defined cutter/mesh
calculation. It is not a ready-made hole/pocket DFM evaluator or complete
tool-holder, fixture, or machine collision checker. Lower priority because STEVE
already operates inside Fusion CAM.

## Candidates that do not meet the production bar yet

### Palmetto

MIT-licensed, broad DFM UI and C++ geometry experiments. Inspected commit:
`7141d6fbe02ad7b3720aa92da9ef00d576477007`; latest repository push January 19, 2026.

A concrete blocker exists in [accessibility_analyzer.cpp](https://github.com/connorkapoor/Palmetto/blob/7141d6fbe02ad7b3720aa92da9ef00d576477007/core/apps/palmetto_engine/accessibility_analyzer.cpp#L210):
without Embree, after an orientation check the unimplemented OCC intersection
branch returns accessible. That is not sufficient evidence of tool access and
can produce false acceptance. The bend-sequence implementation also uses a simple
angle-order heuristic with simplified interference logic. Its own implementation
summary describes unfinished integration. Do not equate the README's broad
process coverage with validated manufacturing checks.

### Casys mcp-dfm

[mcp-dfm](https://github.com/Casys-AI/mcp-dfm) has a sound reporting idea:
snapshot-bound input, caller-supplied limits, explicit mesh topology and sample
coverage, and no blanket manufacturability claim. Version 0.4.1 was published
September 12, 2026; the repository was created August 4, 2026.

Inspected commit: `e42d48ee1aa1db5afa5a1835ee76956da060ce5f`.
It measures envelope, overhangs, and sampled wall thickness. Those are principally
additive-manufacturing checks, not the requested machining/sheet-metal engine.
Its documented container targets are Linux AMD64/ARM64, adding deployment work
for a native Fusion add-in. Tests/fixtures exist, but this review found no
established production deployment evidence. MIT wrapper; GPL Gmsh dependency.
Its evidence contract is worth studying; no MCP integration is proposed.

### DFM Studio

The [website](https://www.dfmanalysis.com/) claims open source and over 100 rules.
Its linked repository, `ideepaks92/DFM-Studio`, returned 404 through both the web
and GitHub API during this review. Source, license, and validation could not be
verified. Do not select it on the strength of the demo or marketing claims.

## Reuse existing evaluation data

[BenDFM](https://github.com/UGent-CVAMO/bendfm) supplies 20,000 synthetic STEP
sheet-metal parts, unfolded representations, and labels covering tooling
collisions or unfolding overlaps. This can materially improve regression
coverage without inventing every sample ourselves. It remains a research
dataset, not a runtime checking engine or a substitute for shop-reviewed parts.

The repository is MIT. Separately, the [Zenodo dataset record](https://zenodo.org/records/18622958)
declares `gpl-3.0-or-later` in its API metadata. Treat code and dataset permissions
separately before redistributing fixtures. Its labels reflect its particular
generation/tooling assumptions; preserve those when evaluating a rule.

## Recommendation for STEVE

### Product direction after discussion

Expose one DFM on/off switch, rather than separate review/design-assist modes.
When enabled, STEVE should consider manufacturing during design and check the
result at meaningful checkpoints. Users supply intent through conversation;
STEVE retains per-component processes and asks only for consequential missing
information. Multiple processes per component remain supported by the design.

Include additive manufacturing from the start of the process model. Do not treat
all 3D printing as one profile: FDM, resin, and powder processes need different
criteria. Initial experiments can target FDM dimensions, selected build envelope,
orientation-dependent overhangs, and wall/feature measurements. Limits depend on
the printer, material, orientation and settings; geometry checks alone do not
establish strength, support success, or print success.

### RMFG: optional external sheet-metal DFM

RMFG's [API guide](https://www.rmfg.com/docs/api) and
[agent guide](https://www.rmfg.com/docs/api/agent-guide.txt) describe browser OAuth
device authorization and PKCE. The [live OpenAPI schema](https://api.rmfg.com/v1/openapi.json)
was read directly during this assessment. A DFM integration does not require
checkout or ordering: upload STEP through `POST /v1/analyze`, poll the returned
design, select current catalog material IDs, and submit `POST /v1/dfm`.
The DFM request supports `generate_production_files: false` for an initial
assessment without requesting generated production files. Authenticated runtime
behavior has not been tested in STEVE.

Reports include per-part findings, assembly issues, requirements, ruleset version,
configuration hash, and `ready`, `requires_input`, or `blocked` status. Reports
are immutable; changed geometry/configuration requires a new evaluation. A ready
result is specific to the evaluated RMFG configuration, not a universal
manufacturability or structural-strength guarantee.

The adjacent reference project's newer `origin/main` contains direct REST auth,
secure credential storage, transport, persisted jobs, and revision-bound export
snapshots. Its current working checkout predates that integration. Source review
confirmed rotating-token serialization, worker-based network operations, and
stale-result checks. Its validation notes record a live upload/ready quote;
that is prior project evidence, not a live test performed in this assessment.
The reviewed modules carry LGPL-2.1-or-later headers; preserve license obligations
if incorporating source. Fusion export, document revision binding, UI, and
credential-store integration need adaptation rather than copying the CAD/Qt layer.

Proposed STEVE experience: one DFM switch and an optional Connect RMFG account
action. Explain that enabling RMFG checks sends the chosen geometry to RMFG and
retain the user's upload authorization scope. Sign-in alone must not authorize
arbitrary document uploads. Use a dedicated application-owned integration shared
by all AI providers; keep credentials out of generated Python and model context.
Bind each response to exported geometry and manufacturing settings so results
cannot silently carry over after edits. General Fusion-based DFM remains useful
without an RMFG account. This remains a proposed integration, not shipped code.

### Native capabilities and qualification

1. Establish native Fusion coverage first: hole/pocket recognition, existing
   feature data, BRep measurements, and sheet-metal information. Verify public
   API access, extension requirements, and imported-solid limitations using
   representative parts. No additional geometry kernel is currently justified.
2. Build tested extraction around those native capabilities. Recognition alone
   does not prove manufacturability: Fusion's recognition documentation explicitly
   distinguishes recognized geometry from safe, non-gouging toolpaths.
3. Seek external algorithms only for measured gaps, and validated process rules
   and evaluation data that add value beyond Fusion. FreeCAD SheetMetal and DFM
   Workbench are not recommended dependencies. BenDFM remains a potential test
   source, subject to its assumptions and license review.
4. Keep manufacturing plans, material/shop profiles, multi-process applicability,
   user controls, evidence reporting, and design-assist integration in STEVE.
   These are the application-specific portions the shortlisted libraries do not
   collectively supply as a turnkey system.

Prefer a local external worker for additional native kernels. Pass an explicitly
scoped geometry snapshot, preserve assembly transforms and units, and return
measurements plus evidence. A worker can be stopped without terminating Fusion's
native work. Do not assume exported STEP face numbers are Fusion entity tokens;
mapping results back to the correct live geometry is a required acceptance test.

Before choosing a dependency, demonstrate Windows x64 and macOS ARM installation,
offline operation, bounded execution, exact revision binding, correct face
mapping, positive/negative/unsupported cases, and redistribution notices. Record
accuracy and packaging cost against the same native-Fusion baseline. This is the
next qualification step, not a promise that a library is already qualified.

No upstream application was installed or executed, no user CAD was uploaded, and
no dependency was added to STEVE during this research. Three upstream repositories
were cloned for read-only source inspection under the ignored research cache.
