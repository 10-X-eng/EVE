"""Disposable SAT round trips using Fusion's documented temporary B-Rep file API.

No document is saved, closed or uploaded. Local SAT files are temporary; imported
solids remain in named test components with base features and no modeling history.
This does not validate the separate STEP ImportManager path.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

import adsk.core
import adsk.fusion

def check_document(app):
    assert app.activeDocument.name == 'STEVE DFM development tests', 'Wrong document'
    assert app.userInterface.activeCommand == 'SelectCommand', 'Finish the active command before testing'


def inspect_imports():
    app = adsk.core.Application.get()
    check_document(app)
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_imported_dfm_probe_' + uuid4().hex
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['DfmGeometry'])
    manager = adsk.fusion.TemporaryBRepManager.get()
    cases = [('pocket', 'DFM rounded pocket fixture', 11004.292036732051),
             ('shaft', 'DFM stepped shaft fixture', 7813.140929477482)]
    results = []
    for kind, source_name, expected_volume in cases:
        check_document(app)
        name = 'DFM SAT imported ' + kind
        assert not any(c.name == name for c in design.allComponents), 'Import fixture exists; do not duplicate'
        component = next(c for c in design.allComponents if c.name == source_name)
        assert component.bRepBodies.count == 1
        original = component.bRepBodies.item(0)
        with tempfile.TemporaryDirectory(prefix='steve-dfm-sat-') as folder:
            path = Path(folder) / 'fixture.sat'
            assert manager.exportToFile([original], str(path)), 'SAT export failed'
            size = path.stat().st_size
            assert 0 < size < 2*1024*1024
            imported = manager.createFromFile(str(path))
            assert imported is not None and imported.count == 1 and imported.item(0).isSolid
            temporary = imported.item(0)
        target = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        target.name = name
        base = target.features.baseFeatures.add()
        assert base.startEdit()
        try:
            assert target.bRepBodies.add(temporary, base) is not None
        finally:
            assert base.finishEdit()
        assert target.bRepBodies.count == 1 and target.occurrences.count == 0
        body = target.bRepBodies.item(0)
        assert abs(body.volume * 1000 - expected_volume) < 1e-4, body.volume * 1000
        revision = body.revisionId
        geometry = bridge.DfmGeometry(body, app, adsk.core, bridge.adsk.cam, fusion=adsk.fusion)
        if kind == 'pocket':
            corners = geometry.cylindrical_surfaces(limit=20)
            assert corners['nextOffset'] is None and len(corners['items']) == 4, corners
            assert all(c['side'] == 'internal' and abs(c['radius_mm'] - 1) < 1e-6 for c in corners['items']), corners
            measured = {'cornerRadii_mm': [c['radius_mm'] for c in corners['items']]}
        else:
            bands, faces, offset = [], [], 0
            while offset is not None:
                page = geometry.cylindrical_walls(offset=offset, limit=2)
                assert not page['unsupported'], page
                bands.extend(page['items'])
                offset = page['nextOffset']
            expected = [('external',12,2),('external',15,10),('external',15,18),('external',20,10),('internal',4,40)]
            actual = sorted((b['side'], round(b['diameter_mm'],6), round(b['axial_span_mm'],6)) for b in bands)
            assert actual == expected, actual
            offset = 0
            while offset is not None:
                page = geometry.rotational_surfaces([0,0,0], [0,0,1], offset=offset, limit=3)
                faces.extend(page['items'])
                offset = page['nextOffset']
            assert len(faces) == body.faces.count and all(f['status'] == 'compatible' for f in faces), faces
            measured = {'bands': actual, 'compatibleFaces': len(faces)}
        assert body.revisionId == revision
        assert all(b.isValid and b.revisionId == old for b, old in protected), 'Pre-existing geometry changed'
        protected.append((body, revision))
        results.append({'case': kind, 'satBytes': size, 'volume_mm3': body.volume*1000, **measured})
    return {'fusionVersion': app.version, 'imports': results, 'allPreExistingBodiesUnchanged': True}


def run(_context):
    print(json.dumps(inspect_imports()))


if __name__ == '__main__':
    run(None)
