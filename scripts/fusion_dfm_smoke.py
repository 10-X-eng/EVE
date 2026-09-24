"""Run inside Fusion against the explicitly named, disposable DFM fixture.

This is a developer check, not an add-in entry point. It imports STEVE under an
isolated package name so a running add-in is not reloaded. No network, document
save, or modification occurs. Create the 60 x 40 x 8 mm test block separately.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


def run(_context):
    app = adsk.core.Application.get()
    if app.activeDocument.name != 'STEVE DFM development tests':
        raise RuntimeError('Activate only the disposable STEVE DFM development tests document.')
    design = adsk.fusion.Design.cast(app.activeProduct)
    bodies = design.rootComponent.bRepBodies
    if bodies.count != 1 or bodies.item(0).name != 'DFM fixture block':
        raise RuntimeError('Expected one named DFM fixture body; no work was performed.')
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_dfm_development_probe'
    for name in list(sys.modules):
        if name == package or name.startswith(package + '.'):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['FusionTools'])
    body = bodies.item(0)
    before = body.revisionId
    with tempfile.TemporaryDirectory(prefix='steve-dfm-probe-') as folder:
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app, tools.task, tools.debug = app, None, None
        tools.document, tools.document_id, tools.closed = app.activeDocument, 'isolated-dfm-probe', False
        tools.dfm = bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        arguments = {'document_id': tools.document_id, 'part_token': body.entityToken}
        tools.dfm_plan({**arguments, 'stages': [{'process': 'milling', 'criteria': {
            'required_length': {'value': 65, 'units': 'mm', 'source': 'Deliberate fixture requirement', 'basis': 'requirement'},
            'envelope_length': {'value': 70, 'units': 'mm', 'source': 'Fixture machine envelope', 'basis': 'profile'}}}]})
        result = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**arguments,
            'stage': 0, 'title': 'Check real fixture dimensions', 'code': """def run(context):
    dfm = context['dfm']
    box = dfm.body.boundingBox
    length = 10 * (box.maxPoint.x - box.minPoint.x)
    dfm.compare('Required length', length, 'required_length', '>=', 'mm', 'Native body boundingBox X span, cm converted to mm')
    dfm.compare('Machine envelope length', length, 'envelope_length', '<=', 'mm', 'Native body boundingBox X span')
    dfm.unknown('Tool access', 'No tool or approach direction has been selected')
    return {'length_mm': length}
"""}, 'cancelled': lambda: False})
        assert result['ok'], result
        assert result['result']['length_mm'] == 60, result
        assert [f['status'] for f in result['dfm']['findings']] == ['concern', 'pass', 'unknown'], result
        assert before == body.revisionId, 'Read-only DFM changed the body'
        print(json.dumps({'fusionVersion': app.version, 'unchanged': True,
                          'test': 'Actual STEVE run_script and DFM plan on real Fusion geometry', 'result': result}, ensure_ascii=False))


if __name__ == '__main__':
    run(None)
