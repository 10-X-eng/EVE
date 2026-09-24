# Machine definitions for DFM

Machine capabilities live in `addin/STEVE/steve/machine_definitions/`, one JSON
file per machine. `steve/machines.py` loads and validates the data. Adding a
definition does not require editing the DFM engine or its tool inventory.
Definitions apply to a particular model/configuration, not every machine from a
manufacturer. No machine is selected by default or inferred from the host computer.

Tell STEVE which machine you intend to use. It discovers the catalog through
`fusion_api_help` at `steve.machines`, then reads `steve.machines.<id>`. The returned
`selection` goes into the relevant plan stage's `machine` field. Different parts
and stages can select different machines; omission leaves machine capability
unknown. The existing DFM switch remains the only DFM mode control.

Inside a check, `context['dfm'].machine` is a copy of the selected definition.
Compare a measurement with `machine.<capability>` through the normal `compare`
method, using the capability's declared units and relation. For example:

```python
def run(context):
    d = context['dfm']
    # Build axes must come from the confirmed part orientation.
    envelope = d.measurements.envelope([1, 0, 0], [0, 1, 0])
    for axis, dimension in zip('xyz', envelope['dimensions_mm']):
        d.compare(axis, dimension, 'machine.nominal_build_' + axis, '<=', 'mm')
    d.unknown('Print outcome', 'Supports, placement and slicer result are not verified')
```

Machine limits cannot be overwritten by ordinary criteria or compared with an
inverted relation. Separate part/setup criteria still record confirmed material,
tooling, slicer or functional requirements. A catalog limit is not a substitute
for those settings. Each machine finding retains its source and capability scope;
reports also include the definition's unverified areas.

## Definition format

Filename is `<id>.json`, using a lowercase ID with letters, digits, hyphens or
underscores. Required fields:

- `id`, `name`, `manufacturer`, `revision`: exact identity and reviewed revision.
- `processes`: one or more of milling, turning, sheet_metal, fdm, resin, powder.
- `verified_on`: ISO date when the cited specifications were checked.
- `sources`: named public HTTPS references; no credentials or local paths.
- `capabilities`: named numeric limits. Each has `value`, `units`, `relation`
  (`<=`, `>=`, `==`), a `source` key and a `scope` explaining what the limit covers.
- `unverified`: explicit capability areas not established by this definition.

Follow an existing file for syntax. Definitions are bounded to 16 KB and 24
capabilities. Use sources specific to the exact machine/configuration. Do not
turn nominal CNC travel into guaranteed machinable-part size, nozzle diameter
into minimum wall thickness, or nominal print volume into successful printing.
Unknown capabilities must remain absent and documented, not assigned guessed
defaults. Definitions are data; loading them executes no plugin code or requests.

The catalog includes these separately sourced nominal XYZ envelopes:

| Definition | Process | Nominal XYZ (mm) | Manufacturer reference |
| --- | --- | --- | --- |
| `prusa-mk4s` | FDM | 250 / 210 / 220 | [Original Prusa MK4S](https://www.prusa3d.com/product/original-prusa-mk4s-kit/) |
| `prusa-core-one` | FDM | 250 / 220 / 270 | [Original CORE One](https://blog.prusa3d.com/introducing-prusa-core-one-fully-enclosed-corexy-3d-printer-with-active-temperature-control_105477/) |
| `formlabs-form-4` | Resin | 200 / 125 / 210 | [Form 4 build volume](https://formlabs.com/support/What-is-the-build-volume-of-the-Form-3L-and-Form-3BL/) |
| `formlabs-fuse-1-plus-30w` | Polymer SLS | 165 / 165 / 300 | [Fuse 1+ 30W specifications](https://formlabs.com/3d-printers/fuse-1/tech-specs/) |

These files do not define material-specific wall, support, strength or clearance
rules. No CNC or sheet-metal machine is bundled yet. Resin and powder definitions
cannot be selected for FDM (or vice versa); the powder entry specifically covers
polymer SLS, not MJF or metal processes. Technology/material compatibility still
requires confirmation; the broad `powder` stage category alone does not prove it.

The Fuse entry describes chamber dimensions, not guaranteed printable dimensions.
Formlabs documents material/settings-dependent compensation and 16 mm inside
corner radii: a full-width square cannot fit even though its XYZ box equals the
nominal dimensions. Review the [usable-volume restrictions](https://formlabs.com/support/What-is-the-build-volume-of-the-Form-3L-and-Form-3BL/)
and verify the actual job in PreForm. Those restrictions stay in the definition's
unverified coverage; STEVE does not implement rounded-chamber containment or
PreForm validation. A nominal comparison alone is not a printability result.

## Updates and historical reports

Plans store the machine ID and a canonical content hash. A changed or missing
definition does not delete the saved plan or silently replace its limits.
Checks require the selected revision to exist and match. After inspection, every
machine referenced by the ordered plan is rechecked, including other stages.
Changes during a check make the report stale; unavailable definitions leave it
unverified. The measurements are retained without rerunning inspection. Machines
outside that plan do not affect its report. Plan reads
also expose `reportBinding.machineStatus`; historical findings require this to
be `current` as well as matching geometry and plan hashes.

Review a changed definition before explicitly refreshing its plan reference.
Changing a definition is not proof that the installed physical machine changed,
and a matching hash cannot detect tooling, calibration or external configuration
changes. Repository definitions ship with STEVE updates. Hand edits inside the
installed add-in can be replaced by an update; contribute maintained definitions
to the repository rather than treating the installation as persistent user data.
