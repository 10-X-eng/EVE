"""Temporary, nonanimated camera changes with restoration on every exit path."""
from contextlib import contextmanager
import math
from itertools import product
from .tool_protocol import ToolError

VIEWS = {"front": "FrontViewOrientation", "top": "TopViewOrientation",
         "right": "RightViewOrientation", "left": "LeftViewOrientation",
         "back": "BackViewOrientation", "bottom": "BottomViewOrientation",
         "isometric": "IsoTopRightViewOrientation"}


def focus_target(context, arguments):
    helper = context['helpers']
    target = (helper.entity(arguments['entity_token']) if 'entity_token' in arguments
              else helper.selected(arguments.get('selection_index', 0)))
    kind = target.objectType.rsplit('::', 1)[-1]
    if kind not in ('BRepBody', 'BRepFace', 'BRepEdge', 'Occurrence'):
        raise ToolError('viewport_unavailable', 'Close-up framing supports bodies, faces, edges, and occurrences. Use the current view for this selection.')
    body = getattr(target, 'body', target)
    parent = getattr(body, 'parentComponent', None)
    if parent is not None and parent != context['root'] and getattr(target, 'assemblyContext', None) is None:
        raise ToolError('viewport_unavailable', 'This native entity is in component coordinates. Resolve its assembly-context proxy before framing it.')
    box = target.boundingBox
    if box is None:
        raise ToolError('viewport_unavailable', 'The selected entity has no supported bounding box.')
    return target


def focus_box(context, arguments):
    return focus_target(context, arguments).boundingBox


@contextmanager
def temporary_camera(viewport, context, arguments, core, cancelled):
    view = arguments.get('view', 'current')
    focus = 'selection_index' in arguments or 'entity_token' in arguments
    if view == 'current' and not focus:
        yield
        return
    if context['product'] is None or context['product'].productType not in ('DesignProductType', 'CAMProductType'):
        raise ToolError('viewport_unavailable', 'Named views and close-up framing are supported for Design and CAM only. Request the current view for this product.')
    box = focus_box(context, arguments) if focus else None
    original = viewport.camera
    camera = viewport.camera
    try:
        camera.isSmoothTransition = False
        if view != 'current':
            camera.viewOrientation = getattr(core.ViewOrientations, VIEWS[view])
        if box is None:
            camera.isFitView = True
        else:
            lo, hi = box.minPoint, box.maxPoint
            radius = math.sqrt(sum((getattr(hi, axis) - getattr(lo, axis)) ** 2 for axis in ('x', 'y', 'z'))) / 2
            if not math.isfinite(radius) or radius <= 0:
                raise ToolError('viewport_unavailable', 'Cannot frame a zero-sized or invalid bounding box.')
            center = [(getattr(lo, axis) + getattr(hi, axis)) / 2 for axis in ('x', 'y', 'z')]
            if not all(math.isfinite(value) for value in center):
                raise ToolError('viewport_unavailable', 'Cannot frame an invalid bounding-box center.')
            direction = [getattr(camera.eye, axis) - getattr(camera.target, axis) for axis in ('x', 'y', 'z')]
            length = math.sqrt(sum(value * value for value in direction))
            if not math.isfinite(length) or length <= 0:
                raise ToolError('viewport_unavailable', 'Camera direction is unavailable.')
            direction = [value / length for value in direction]
            # Orthographic zoom comes from extents, not eye distance. A distance
            # based only on a tiny face/pin can put the eye inside its assembly.
            distance = max(length, radius * 4)
            scene = getattr(context['root'], 'boundingBox', None)
            if scene is not None:
                corners = product(*[(getattr(scene.minPoint, axis), getattr(scene.maxPoint, axis))
                                    for axis in ('x', 'y', 'z')])
                depths = [sum((point[i] - center[i]) * direction[i] for i in range(3)) for point in corners]
                if not all(math.isfinite(value) for value in depths):
                    raise ToolError('viewport_unavailable', 'Cannot place the camera outside an invalid assembly bounding box.')
                distance = max(distance, max(depths) + radius * 2)
            camera.cameraType = core.CameraTypes.OrthographicCameraType
            camera.isFitView = False
            camera.target = core.Point3D.create(*center)
            camera.eye = core.Point3D.create(*(center[i] + direction[i] * distance for i in range(3)))
            aspect = max(1, viewport.width) / max(1, viewport.height)
            diameter = radius * 2.4
            if not camera.setExtents(diameter * max(1, aspect), diameter * max(1, 1 / aspect)):
                raise ToolError('viewport_unavailable', 'Fusion could not set orthographic framing extents.')
        if cancelled():
            raise ToolError('cancelled', 'Capture cancelled before moving the camera.')
        viewport.camera = camera
        viewport.refresh()
        if cancelled():
            raise ToolError('cancelled', 'Capture cancelled after framing.')
        yield
    finally:
        try:
            original.isSmoothTransition = False
            viewport.camera = original
            viewport.refresh()
        except (AttributeError, RuntimeError) as exc:
            raise ToolError('camera_restore_failed', 'Fusion could not restore the original camera. Inspect your view before another capture.') from exc
