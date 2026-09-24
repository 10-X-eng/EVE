"""Read-only native geometry probe with temporary DFM plan changes during reporting."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


def run(_context):
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests', 'Wrong document'
    assert app.userInterface.activeCommand == 'SelectCommand', 'Finish the active command'
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    body = root.bRepBodies.item(0)
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_dfm_currency_probe'
    for key in list(sys.modules):
        if key == package or key.startswith(package + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['FusionTools'])
    with tempfile.TemporaryDirectory(prefix='steve-dfm-currency-') as folder:
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app, tools.task, tools.debug = app, None, None
        tools.document, tools.document_id, tools.closed = app.activeDocument, 'currency-probe', False
        tools.dfm = bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        args = {'document_id': tools.document_id, 'part_token': body.entityToken}
        stages = [{'process': 'fdm', 'criteria': {'build_x': {'value': 62, 'units': 'mm',
            'basis': 'profile', 'source': 'Synthetic fixture build envelope'}}}, {'process': 'milling'}]
        code = '''def run(context):
    d = context['dfm']
    measured = d.measurements.envelope([1,0,0], [0,1,0])
    d.compare('Build X', measured['dimensions_mm'][0], 'build_x', '<=', 'mm', 'Native oriented envelope; this dimension only')
'''
        original_run = bridge.run_python
        results = []
        for change in ('none', 'other_stage', 'clear'):
            before = tools.dfm_plan({**args, 'stages': stages})
            def execute_then_change(*positional, **keywords):
                result = original_run(*positional, **keywords)
                if change == 'other_stage':
                    tools.dfm_plan({**args, 'stages': [stages[0], {'process': 'turning'}]})
                elif change == 'clear':
                    tools.dfm_plan({**args, 'stages': []})
                return result
            bridge.run_python = execute_then_change
            try:
                result = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**args,
                    'stage': 0, 'title': 'Check plan currency', 'code': code}, 'cancelled': lambda: False})
            finally:
                bridge.run_python = original_run
            assert result['ok'], result
            report = result['dfm']
            assert report['planHash'] == before['reportBinding']['planHash']
            assert report['revision'] == before['reportBinding']['revision']
            assert abs(report['findings'][0]['actual'] - 60) < 1e-6
            assert report['findings'][0]['limit'] == 62
            assert report['status'] == ('checked' if change == 'none' else 'stale'), report
            assert report['findings'][0]['status'] == ('pass' if change == 'none' else 'unknown'), report
            after = tools.dfm_plan(args)['reportBinding']
            assert (after['planHash'] == report['planHash']) == (change == 'none')
            results.append({'change': change, 'status': report['status'],
                            'configurationStatus': report['configurationStatus'],
                            'retainedActual_mm': report['findings'][0]['actual']})
    assert all(b.isValid and b.revisionId == old for b, old in protected), 'Existing body changed'
    print(json.dumps({'fusionVersion': app.version, 'cases': results, 'allBodiesUnchanged': True,
                      'scope': 'Explicit single-dimension comparison; not complete manufacturing coverage'}))


if __name__ == '__main__':
    run(None)
