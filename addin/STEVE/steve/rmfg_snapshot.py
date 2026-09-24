"""Main-thread STEP snapshots. Refuse exports that include unintended geometry."""
from pathlib import Path
import tempfile

from .rmfg import MAX_STEP_BYTES
from .tool_protocol import ToolError


def export_snapshot(body, design, document_key):
    component = body.parentComponent
    if (not body.isSolid or component.bRepBodies.count != 1
            or component.bRepBodies.item(0) != body or component.occurrences.count
            or component.meshBodies.count):
        raise ToolError('rmfg_export_scope', 'This STEP exporter needs a component containing exactly the chosen solid body, no meshes and no child occurrences.')
    revision = body.revisionId
    if not revision:
        raise ToolError('rmfg_export_scope', 'Fusion did not provide a geometry revision for this part.')
    with tempfile.TemporaryDirectory(prefix='steve-rmfg-') as folder:
        path = Path(folder) / 'part.step'
        options = design.exportManager.createSTEPExportOptions(str(path), component)
        if options is None or not design.exportManager.execute(options) or not path.is_file():
            raise ToolError('rmfg_export_scope', 'Fusion could not export this component as STEP.')
        if not 0 < path.stat().st_size <= MAX_STEP_BYTES:
            raise ToolError('rmfg_export_scope', 'The exported STEP snapshot must be between 1 byte and 50 MiB.')
        data = path.read_bytes()
    if body.revisionId != revision:
        raise ToolError('rmfg_export_scope', 'Geometry changed during export. Inspect before preparing another snapshot.')
    return {'ok': True, 'step': data, 'body': body.name, 'documentKey': document_key,
            'partToken': body.entityToken, 'revision': revision}
