"""Small read-only helpers available inside a coherent generated operation."""
import inspect
import math
from .tool_protocol import ToolError


class FusionHelpers:
    def __init__(self, context, captured_selection):
        self._context = context
        self._selection = tuple(captured_selection)

    def selected(self, index=0, expected_type=None):
        """Resolve the captured selection. expected_type accepts an SDK class, classType() string or dotted adsk class path."""
        if type(index) is not int or not 0 <= index < len(self._selection):
            raise ToolError("entity_unavailable", "That index was not in the captured selection.")
        return self._checked(self._selection[index], expected_type)

    @staticmethod
    def _checked(entity, expected_type):
        if entity is None or getattr(entity, "isValid", True) is False:
            raise ToolError("entity_unavailable", "The original entity is no longer valid. Inspect the pinned document.")
        if expected_type is not None:
            if isinstance(expected_type, type) and callable(getattr(expected_type, 'classType', None)):
                expected_type = expected_type.classType()
            if not isinstance(expected_type, str) or not 1 <= len(expected_type) <= 250:
                raise ValueError('expected_type must be an installed SDK class, its classType() string, or a dotted adsk class path.')
            if expected_type.startswith('adsk.'):
                if any(not part.isidentifier() or part.startswith('_') for part in expected_type.split('.')):
                    raise ValueError('Use a public dotted adsk class path.')
                expected_type = expected_type.replace('.', '::')
            if entity.objectType != expected_type:
                raise ToolError('entity_type_mismatch',
                    'The resolved entity has objectType ' + entity.objectType + ', but ' + expected_type + ' was requested.')
        return entity

    def entity(self, token, expected_type=None):
        """Resolve exactly one pinned entity. expected_type accepts an SDK class, classType() string or dotted adsk path."""
        design = self._context.get("design")
        if design is None:
            raise ToolError("entity_unavailable", "Token resolution needs the pinned Design product.")
        if not isinstance(token, str) or not 1 <= len(token) <= 2048:
            raise ValueError("Use a bounded entity token from the pinned document.")
        matches = design.findEntityByToken(token)
        if len(matches) != 1:
            raise ToolError("entity_unavailable", "The token resolved to zero or multiple entities. Inspect before choosing a target.")
        return self._checked(matches[0], expected_type)

    def evaluate(self, expression, unit_type):
        """Validate a Design expression with a unit type (e.g. 'mm'); return internal units (cm/rad)."""
        units = self._context.get("units")
        if units is None:
            raise ValueError("Expression evaluation requires Design units; do not assume these units for CAM/Electronics.")
        if not isinstance(expression, str) or not 1 <= len(expression) <= 300 or not isinstance(unit_type, str) or not 1 <= len(unit_type) <= 40:
            raise ValueError("Supply a bounded expression and explicit unit type.")
        if not units.isValidExpression(expression, unit_type):
            raise ValueError("Expression is invalid or incompatible with the requested unit type.")
        result = units.evaluateExpression(expression, unit_type)
        if not math.isfinite(result):
            raise ValueError("Expression did not produce a finite value.")
        return result

    def page(self, collection, select, offset=0, limit=20, where=None, scan_limit=100):
        """Read a bounded collection page. select returns JSON fields; where filters locally.

        nextOffset is the next collection index, not the number of matches. Counts describe
        this scan, not a snapshot across calls. Keep select/where read-only and bounded.
        """
        if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20
                or type(scan_limit) is not int or not 1 <= scan_limit <= 200):
            raise ValueError("Use offset >= 0, limit 1..20 and scan_limit 1..200.")
        total = collection.count
        rows, cursor = [], min(offset, total)
        while cursor < total and cursor - offset < scan_limit and len(rows) < limit:
            entity = collection.item(cursor)
            cursor += 1
            if where is None or where(entity):
                rows.append(select(entity))
        return {"items": rows, "total": total, "offset": offset, "returned": len(rows),
                "scanned": max(0, cursor - offset), "nextOffset": cursor if cursor < total else None,
                "complete": cursor >= total}


def helper_help():
    return {"ok": True, "path": "steve.helpers", "members": {
        name: {"signature": str(inspect.signature(getattr(FusionHelpers, name))),
               "documentation": inspect.getdoc(getattr(FusionHelpers, name))}
        for name in ("selected", "entity", "evaluate", "page")},
        "example": "def run(context):\n    h = context['helpers']\n    return h.page(context['root'].bRepBodies, lambda b: {'name': b.name})",
        "guidance": "Helpers read the pinned context. They do not enforce read-only callbacks or sandbox Python. "
                    "Use fusion_execute_python for modifications, and verification.check for measured outcomes."}
