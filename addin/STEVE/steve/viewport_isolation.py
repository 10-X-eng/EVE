"""Temporary body/occurrence visibility, with complete preflight and restoration."""
from contextlib import contextmanager
from .tool_protocol import ToolError
from .viewport import focus_target


def items(collection):
    return [collection.item(index) for index in range(collection.count)]


def visibility_plan(context, arguments):
    target = focus_target(context, arguments)
    occurrence_target = target.objectType.endswith('::Occurrence')
    body = None if occurrence_target else getattr(target, 'body', target)
    occurrence = target if occurrence_target else getattr(body, 'assemblyContext', None)
    path = occurrence.fullPathName if occurrence is not None else ''
    root = context['root']
    occurrences = items(root.allOccurrences)
    if path and not any(item.fullPathName == path for item in occurrences):
        raise ToolError('viewport_unavailable', 'Resolve the target in the root assembly context before isolating it.')
    plan = []
    components = [(root, False)]

    def set_value(obj, attribute, desired):
        original = getattr(obj, attribute)
        if original != desired:
            plan.append((obj, attribute, original, desired))

    for item in occurrences:
        item_path = item.fullPathName
        ancestor = bool(path) and (path == item_path or path.startswith(item_path + '+'))
        descendant = occurrence_target and item_path.startswith(path + '+')
        if ancestor:
            set_value(item, 'isLightBulbOn', True)
        elif not descendant:
            set_value(item, 'isLightBulbOn', False)
        # Components on the selected branch need their own body visibility handled.
        if ancestor or descendant:
            keep_contents = occurrence_target and (item_path == path or descendant)
            if not any(component == item.component for component, _ in components):
                components.append((item.component, keep_contents))
    native = (getattr(body, 'nativeObject', None) or body) if body is not None else None
    for component, keep_contents in components:
        for attribute in ('isSketchFolderLightBulbOn', 'isConstructionFolderLightBulbOn',
                          'isOriginFolderLightBulbOn', 'isCanvasFolderLightBulbOn'):
            set_value(component, attribute, False)
        if keep_contents:
            continue  # Preserve intentional visibility inside the selected component.
        selected_component = native is not None and native.parentComponent == component
        set_value(component, 'isBodiesFolderLightBulbOn', selected_component)
        if selected_component:
            for candidate in items(component.bRepBodies) + items(component.meshBodies):
                set_value(candidate, 'isLightBulbOn', candidate == native)
    return plan


@contextmanager
def temporary_isolation(viewport, context, arguments, cancelled):
    if not arguments.get('isolate', False):
        yield
        return
    # Preflight all reads before touching visibility. Unsupported API/product fails closed.
    if context['product'] is None or context['product'].productType != 'DesignProductType':
        raise ToolError('viewport_unavailable', 'Isolation requires the Design workspace. Capture without isolate in CAM or other products.')
    try:
        plan = visibility_plan(context, arguments)
    except (AttributeError, RuntimeError) as exc:
        if isinstance(exc, ToolError):
            raise
        raise ToolError('viewport_unavailable', 'Fusion could not read visibility for this target. Capture without isolate or resolve its assembly-context proxy.') from exc
    changed = []
    try:
        for obj, attribute, original, desired in plan:
            if cancelled():
                raise ToolError('cancelled', 'Capture cancelled while isolating the target.')
            changed.append((obj, attribute, original))
            setattr(obj, attribute, desired)
            if getattr(obj, attribute) != desired:
                raise ToolError('viewport_unavailable', 'Fusion refused a visibility change. Capture without isolate.')
        viewport.refresh()
        if cancelled():
            raise ToolError('cancelled', 'Capture cancelled after isolating the target.')
        yield
    finally:
        failures = []
        for obj, attribute, original in reversed(changed):
            try:
                setattr(obj, attribute, original)
                if getattr(obj, attribute) != original:
                    failures.append(attribute)
            except (AttributeError, RuntimeError):
                failures.append(attribute)
        viewport.refresh()
        if failures:
            raise ToolError('visibility_restore_failed', 'Fusion could not restore all visibility. Stop captures and ask the user to inspect the browser visibility before continuing.')
