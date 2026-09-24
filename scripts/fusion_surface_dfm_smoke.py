"""Create an isolated open-surface fixture and verify unknown print coverage."""
import importlib.util
import json
from pathlib import Path
import sys

import adsk.core
import adsk.fusion


def run(_context):
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests', 'Wrong document'
    assert app.userInterface.activeCommand == 'SelectCommand', 'Finish the active command'
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    name = 'DFM open surface fixture'
    assert not any(c.name == name for c in design.allComponents), 'Fixture exists; do not duplicate'
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_surface_dfm_probe'
    for key in list(sys.modules):
        if key == package or key.startswith(package + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['DfmGeometry'])
    face = next(f for f in root.bRepBodies.item(0).faces if adsk.core.Plane.cast(f.geometry))
    temporary = adsk.fusion.TemporaryBRepManager.get().copy(face)
    assert temporary and not temporary.isSolid
    component = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name = name
    base = component.features.baseFeatures.add()
    assert base.startEdit()
    try:
        created = component.bRepBodies.add(temporary, base)
        assert created is not None
    finally:
        assert base.finishEdit()
    assert component.bRepBodies.count == 1
    body = component.bRepBodies.item(0)
    body.name = 'DFM single open planar face'
    assert not body.isSolid and body.faces.count == 1 and body.revisionId
    revision = body.revisionId
    geometry = bridge.DfmGeometry(body, app, adsk.core, bridge.adsk.cam, fusion=adsk.fusion)
    result = geometry.planar_overhangs([1, 0, 0], [0, 1, 0])
    assert result['status'] == 'unknown' and result['items'] == [], result
    assert 'solid body' in result['reason'], result
    assert body.revisionId == revision
    assert all(b.isValid and b.revisionId == old for b, old in protected), 'Existing body changed'
    print(json.dumps({'fusionVersion': app.version, 'isSolid': body.isSolid, 'faceCount': body.faces.count,
                      'overhangResult': result, 'preExistingBodiesUnchanged': True}))


if __name__ == '__main__':
    run(None)
