import copy
from types import SimpleNamespace as Obj
import unittest
from pathlib import Path
from unittest.mock import patch
from test_fusion_bridge import bridge, Host
from steve.viewport import temporary_camera
from steve.python_helpers import FusionHelpers
from steve.tool_protocol import validate_call


class Camera:
    def __init__(self):
        self.eye = Obj(x=0, y=0, z=10)
        self.target = Obj(x=0, y=0, z=0)
        self.viewOrientation = 'original'
        self.cameraType = 'perspective'
        self.isFitView = False
        self.isSmoothTransition = False
    def setExtents(self, width, height):
        self.extents = (width, height)
        return True


class Viewport:
    def __init__(self):
        self.saved = Camera()
        self.width, self.height = 400, 800
        self.moves = []
    @property
    def camera(self):
        return copy.deepcopy(self.saved)
    @camera.setter
    def camera(self, value):
        self.saved = copy.deepcopy(value)
        self.moves.append(self.saved)
    def refresh(self):
        pass


class ViewportTests(unittest.TestCase):
    def setUp(self):
        self.view = Viewport()
        self.core = Obj(ViewOrientations=Obj(FrontViewOrientation='front', TopViewOrientation='top'),
                        CameraTypes=Obj(OrthographicCameraType='ortho'),
                        Point3D=Obj(create=lambda x,y,z: Obj(x=x,y=y,z=z)))
        self.context = {'product': Obj(productType='DesignProductType'), 'root': Obj()}

    def test_bridge_labels_image_and_restores_camera_before_completion(self):
        host = Host()
        host.activeViewport = self.view
        observed = []
        def save(path, width, height):
            observed.append(self.view.camera.viewOrientation)
            Path(path).write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            return True
        self.view.saveAsImageFile = save
        tools = bridge.FusionTools(host)
        tools.namespaces = lambda: []
        results = []
        try:
            token = tools.selection_context()['document_id']
            with patch.object(bridge.adsk.core, 'ViewOrientations', self.core.ViewOrientations, create=True):
                tools.submit('fusion_capture_viewport', {'document_id':token, 'view':'top'}, results.append, lambda:False)
                host.pump()
            self.assertEqual(observed, ['top'])
            self.assertEqual(results[0]['view'], 'top')
            self.assertEqual(self.view.camera.viewOrientation, 'original')
            self.assertTrue(results[0]['imageUrl'].startswith('data:image/png;base64,'))
        finally:
            tools.close()

    def test_named_view_restores_camera_after_success_and_failure(self):
        for failing in (False, True):
            try:
                with temporary_camera(self.view, self.context, {'view': 'front'}, self.core, lambda: False):
                    self.assertEqual(self.view.camera.viewOrientation, 'front')
                    if failing:
                        raise RuntimeError('capture failed')
            except RuntimeError:
                self.assertTrue(failing)
            self.assertEqual(self.view.camera.viewOrientation, 'original')
            self.assertEqual(self.view.camera.cameraType, 'perspective')

    def test_closeup_fits_bounding_sphere_in_narrow_viewport(self):
        target = Obj(objectType='adsk::fusion::BRepBody', parentComponent=self.context['root'],
                     boundingBox=Obj(minPoint=Obj(x=10,y=20,z=0), maxPoint=Obj(x=12,y=22,z=2)))
        self.context['helpers'] = FusionHelpers(self.context, [target])
        with temporary_camera(self.view, self.context, {'selection_index': 0}, self.core, lambda: False):
            camera = self.view.camera
            self.assertEqual((camera.target.x,camera.target.y,camera.target.z), (11,21,1))
            self.assertEqual(camera.cameraType, 'ortho')
            self.assertGreater(camera.extents[1], camera.extents[0])
        self.assertEqual(self.view.camera.cameraType, 'perspective')

    def test_cancellation_after_moving_camera_restores_it(self):
        calls = []
        def cancelled():
            calls.append(True)
            return len(calls) > 1
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            with temporary_camera(self.view, self.context, {'view':'top'}, self.core, cancelled):
                self.fail('Must not capture')
        self.assertEqual(self.view.camera.viewOrientation, 'original')

    def test_unsupported_product_and_stale_selection_never_move_camera(self):
        self.context['product'].productType = 'ElectronicsProduct'
        with self.assertRaisesRegex(RuntimeError, 'Design and CAM'):
            with temporary_camera(self.view, self.context, {'view':'front'}, self.core, lambda:False):
                pass
        self.context['product'].productType = 'DesignProductType'
        self.context['helpers'] = FusionHelpers(self.context, [Obj(isValid=False)])
        with self.assertRaisesRegex(RuntimeError, 'no longer valid'):
            with temporary_camera(self.view, self.context, {'selection_index':0}, self.core, lambda:False):
                pass
        self.assertFalse(self.view.moves)

    def test_schema_rejects_ambiguous_target_and_invalid_orientation(self):
        for arguments in ({'view':'unknown'}, {'selection_index':True}, {'entity_token':'x','selection_index':0}):
            with self.assertRaises(ValueError):
                validate_call('fusion_capture_viewport', {'document_id':'doc', **arguments})
        validate_call('fusion_capture_viewport', {'document_id':'doc','view':'isometric'})
