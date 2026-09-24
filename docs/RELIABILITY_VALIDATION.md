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

Live Fusion verification remains required: reproduce the Electronics idle command,
record its ID, inspect during Design/CAM commands, and run a long native calculation.
The Electronics command ID has not been verified, so no new idle command is allowlisted.
These checks do not establish that native calculations are interruptible.

## Product summaries (#11)

Design summaries include bounded component, occurrence, sketch constraint, feature
health, and parameter details. CAM summaries read setup/operation state without
typed parameter values. Electronics summaries cast the pinned product through the
installed namespace and describe board, schematic, or library collections with the
documented read-only limitation. Missing properties are explicitly unavailable.
Collections report completeness and offsets, and the combined report is bounded.

Fixture tests cover large and empty collections, missing properties, profile-free
inspection, CAM parameter avoidance, and Electronics capability reporting. Native
Fusion validation of all three product summaries remains required.
