import unittest
from unittest.mock import patch
from types import SimpleNamespace as Obj
from test_viewport import Viewport
from steve.viewport_isolation import temporary_isolation
from steve.python_helpers import FusionHelpers
from steve.tool_protocol import validate_call


class Entity:
    def __init__(self, **values):
        self.__dict__.update(values)


def collection(*values):
    return Obj(count=len(values), item=lambda index: values[index])


def component():
    return Entity(isSketchFolderLightBulbOn=True, isConstructionFolderLightBulbOn=True,
                  isOriginFolderLightBulbOn=False, isCanvasFolderLightBulbOn=True,
                  isBodiesFolderLightBulbOn=True, bRepBodies=collection(), meshBodies=collection())


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.root, self.mount, self.hardware = component(), component(), component()
        self.boom = self.body(self.root)
        self.pin, self.washer = self.body(self.hardware), self.body(self.hardware)
        self.washer.isLightBulbOn = False
        self.hardware.bRepBodies = collection(self.pin, self.washer)
        self.root.bRepBodies = collection(self.boom)
        self.parent = self.occurrence('Mount:1', self.mount, False)
        self.target = self.occurrence('Mount:1+Hardware:1', self.hardware, False)
        self.other = self.occurrence('Hardware:2', self.hardware, True)
        self.child = self.occurrence('Mount:1+Hardware:1+Child:1', component(), True)
        self.root.allOccurrences = collection(self.parent, self.target, self.other, self.child)
        self.proxy = self.body(self.hardware)
        self.proxy.nativeObject = self.pin
        self.proxy.assemblyContext = self.target
        self.context = {'root':self.root,'product':Obj(productType='DesignProductType')}
        self.view = Viewport()
        self.objects = [self.root,self.mount,self.hardware,self.parent,self.target,self.other,self.child,self.pin,self.washer,self.boom]
        self.before = self.snapshot()

    def snapshot(self):
        return [{key:value for key,value in obj.__dict__.items() if isinstance(value,bool)} for obj in self.objects]

    @staticmethod
    def body(parent):
        return Entity(objectType='adsk::fusion::BRepBody',parentComponent=parent,isLightBulbOn=True,boundingBox=Obj())

    @staticmethod
    def occurrence(path, comp, visible):
        return Entity(objectType='adsk::fusion::Occurrence',fullPathName=path,component=comp,isLightBulbOn=visible,boundingBox=Obj())

    def capture(self, target, cancelled=lambda:False):
        self.context['helpers'] = FusionHelpers(self.context,[target])
        return temporary_isolation(self.view,self.context,{'selection_index':0,'isolate':True},cancelled)

    def test_face_isolates_owning_body_through_hidden_parents_and_restores_every_flag(self):
        face = Entity(objectType='adsk::fusion::BRepFace',body=self.proxy,assemblyContext=self.target,boundingBox=Obj())
        with self.capture(face):
            self.assertTrue(self.parent.isLightBulbOn)
            self.assertTrue(self.target.isLightBulbOn)
            self.assertFalse(self.other.isLightBulbOn)
            self.assertFalse(self.child.isLightBulbOn)
            self.assertFalse(self.root.isBodiesFolderLightBulbOn)
            self.assertTrue(self.pin.isLightBulbOn)
            self.assertFalse(self.washer.isLightBulbOn)
            self.assertFalse(self.hardware.isSketchFolderLightBulbOn)
        self.assertEqual(self.snapshot(),self.before)

    def test_occurrence_keeps_subtree_and_existing_hidden_contents(self):
        with self.capture(self.target):
            self.assertTrue(self.child.isLightBulbOn)
            self.assertFalse(self.other.isLightBulbOn)
            self.assertFalse(self.washer.isLightBulbOn)
            self.assertTrue(self.hardware.isBodiesFolderLightBulbOn)
        self.assertEqual(self.snapshot(),self.before)

    def test_root_body_hides_all_occurrences_and_restores_after_capture_failure(self):
        with self.assertRaisesRegex(RuntimeError,'render failed'):
            with self.capture(self.boom):
                self.assertFalse(self.other.isLightBulbOn)
                self.assertFalse(self.target.isLightBulbOn)
                self.assertTrue(self.root.isBodiesFolderLightBulbOn)
                raise RuntimeError('render failed')
        self.assertEqual(self.snapshot(),self.before)

    def test_cancel_during_visibility_changes_restores_all_prior_changes(self):
        count = 0
        def cancelled():
            nonlocal count
            count += 1
            return count > 3
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            with self.capture(self.proxy,cancelled):
                self.fail('Must not capture')
        self.assertEqual(self.snapshot(),self.before)

    def test_preflight_failure_changes_nothing(self):
        del self.hardware.isCanvasFolderLightBulbOn
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError,'could not read visibility'):
            with self.capture(self.proxy):
                self.fail('Must not capture')
        self.assertEqual(self.snapshot(),before)

    def test_failed_visibility_setter_restores_changes_already_applied(self):
        calls = 0
        def setter(obj, name, value):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise RuntimeError('visibility setter failed')
            setattr(obj, name, value)
        with patch('steve.viewport_isolation.setattr', setter, create=True):
            with self.assertRaisesRegex(RuntimeError, 'setter failed'):
                with self.capture(self.proxy):
                    self.fail('Must not capture')
        self.assertEqual(self.snapshot(), self.before)

    def test_restore_failure_reports_error_but_still_restores_other_flags(self):
        restoring = False
        def setter(obj, name, value):
            if restoring and obj is self.parent:
                raise RuntimeError('parent restoration failed')
            setattr(obj, name, value)
        with patch('steve.viewport_isolation.setattr', setter, create=True):
            with self.assertRaisesRegex(RuntimeError, 'could not restore all visibility'):
                with self.capture(self.proxy):
                    restoring = True
        after = self.snapshot()
        index = self.objects.index(self.parent)
        self.assertEqual(after[:index]+after[index+1:], self.before[:index]+self.before[index+1:])

    def test_native_nonroot_entity_and_cam_are_rejected_without_changes(self):
        with self.assertRaisesRegex(RuntimeError,'assembly-context proxy'):
            with self.capture(self.pin):
                self.fail('Must not capture')
        self.context['product'].productType = 'CAMProductType'
        with self.assertRaisesRegex(RuntimeError,'Design workspace'):
            with self.capture(self.proxy):
                self.fail('Must not capture')
        self.assertEqual(self.snapshot(),self.before)

    def test_isolation_schema_requires_boolean_and_explicit_target(self):
        for extra in ({'isolate':True},{'isolate':'true','selection_index':0}):
            with self.assertRaises(ValueError):
                validate_call('fusion_capture_viewport',{'document_id':'doc',**extra})
        validate_call('fusion_capture_viewport',{'document_id':'doc','entity_token':'part','isolate':True})
