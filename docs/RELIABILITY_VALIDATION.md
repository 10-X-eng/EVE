# Fusion reliability validation

## Tool waits (#10)

Unknown active commands now receive metadata-only inspection, including command,
workspace, and product IDs. No geometry evaluation is attempted in that state.
Generated queries and writes retain their command and document gates. The assistant
is instructed to explain deferred inspection rather than enqueue dependent work.
Queued waits have no expiry and log their reason and elapsed time when revisited.
Native C-call duration is excluded from the Python loop time budget; explicit Stop
still takes effect only after control returns to Python.

Automated host fixtures cover metadata-only inspection, long waits, cancellation,
document transitions, command completion, and exactly-once results. Runner tests
cover a native wait longer than the Python budget and a Python loop afterward.

A live blank schematic reported `Electron::Group`, `SchematicProductType`, and
`SchEditorEnvironement`. Autodesk documents [GROUP as active by default](https://help.autodesk.com/cloudhelp/ENU/Fusion-ECAD/files/ECD-LAYOUT-EDITOR-REF.htm).
That exact state now permits inspection, queries, and current-view capture when the
active product matches the task's product. Writes still cannot preempt GROUP and
receive an actionable read-only-state error instead of waiting forever. Query code
is instructed to be read-only; it is not a security sandbox.

Fixtures cover this selection state, editing commands, product/workspace mismatches,
and write rejection. Live verification of the fix remains required, along with
inspection during Design/CAM commands and a long native calculation. These checks
do not establish that native calculations are interruptible.
