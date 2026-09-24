# Helpers inside Fusion operations

Use `fusion_api_help` with `path: "steve.helpers"` to discover current signatures.
Helpers are available as `context['helpers']` in both query and modification scripts.
They do not change documents, units, selections, or geometry.

Instead of manually scanning an entire collection and slicing the result afterward:

```python
def run(context):
    bodies = context['root'].bRepBodies
    return [{'name': bodies.item(i).name} for i in range(bodies.count)]
```

Read a bounded page, preserving the next collection index even when filtering:

```python
def run(context):
    h = context['helpers']
    return h.page(context['root'].bRepBodies,
                  select=lambda body: {'name': body.name},
                  where=lambda body: 'bracket' in body.name.casefold(),
                  offset=0, limit=20, scan_limit=100)
```

Use the returned `nextOffset` on subsequent calls. `total` counts collection entries,
not matching entries. Results are not a snapshot across separate calls. Callbacks
must be bounded and read-only for queries; helpers do not enforce a Python sandbox.

Instead of assuming that millimeters are Fusion's internal unit or reading the live
UI selection, use the pinned context:

```python
def run(context):
    h = context['helpers']
    edge = h.selected(0, expected_type='adsk::fusion::BRepEdge')
    distance_cm = h.evaluate('8 mm', 'mm')
    return {'edgeType': edge.objectType, 'distanceCm': distance_cm}
```

`evaluate` uses the pinned Design's expression validation and returns Fusion internal
units (centimeters for length, radians for angles). It is not a CAM/Electronics unit
converter. `entity(token, expected_type=...)` resolves exactly one valid entity in the
pinned Design. Missing or ambiguous references raise actionable errors.

Validation: fixtures cover stale original selection indices, ambiguous/missing tokens,
type mismatches, invalid unit expressions, sparse filtered pages, and empty collections.
Live Autodesk entity resolution and expression evaluation remain native smoke checks.
