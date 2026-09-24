"""Independent analytic fixtures for native DFM measurement adapters."""
import math
from types import SimpleNamespace as Obj
import unittest

from test_fusion_bridge import Collection
from steve.dfm_geometry import DfmGeometry


def vector(x, y, z):
    return Obj(x=x, y=y, z=z)


class Point:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def copy(self):
        return Point(self.x, self.y, self.z)

    def transformBy(self, matrix):
        self.x, self.y, self.z = matrix.point(self.x, self.y, self.z)
        return True


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.core = Obj(Vector3D=Obj(create=vector),
                        Plane=Obj(cast=lambda geo: geo if getattr(geo, 'kind', '') == 'plane' else None),
                        Cylinder=Obj(cast=lambda geo: geo if getattr(geo, 'kind', '') == 'cylinder' else None),
                        Circle3D=Obj(cast=lambda geo: geo if getattr(geo, 'kind', '') == 'circle' else None))
        self.body = Obj(revisionId='r1', faces=Collection(), isSolid=True)
        root = Obj()
        root.parentDesign = Obj(rootComponent=root)
        self.body.parentComponent = root
        self.cam = Obj()
        self.app = Obj(measureManager=Obj(getOrientedBoundingBox=lambda body, x, y: Obj(length=6, width=4, height=.8, centerPoint=vector(3,2,.4))))
        self.app.pointTolerance = 1e-6
        self.geo = DfmGeometry(self.body, self.app, self.core, self.cam)

    def test_rotational_surface_checks_trimming_and_axis_not_only_cylinder_type(self):
        self.app.pointTolerance=1e-6
        self.app.vectorAngleTolerance=1e-6
        circle=Obj(kind='circle',center=vector(0,0,0),normal=vector(0,0,1))
        surface=Obj(kind='cylinder',origin=vector(0,0,0),axis=vector(0,0,-1))
        valid=Obj(geometry=surface,edges=Collection(Obj(geometry=circle)),entityToken='valid')
        trimmed=Obj(geometry=surface,edges=Collection(Obj(geometry=Obj(kind='arc'))),entityToken='trimmed')
        off_axis=Obj(geometry=Obj(kind='cylinder',origin=vector(1,0,0),axis=vector(0,0,1)),entityToken='offset')
        nurbs=Obj(geometry=Obj(kind='nurbs'),entityToken='unsupported')
        self.body.faces=Collection(valid,trimmed,off_axis,nurbs)
        first=self.geo.rotational_surfaces([0,0,0],[0,0,1],limit=2)
        self.assertEqual([i['status'] for i in first['items']],['compatible','unknown'])
        self.assertEqual(first['nextOffset'],2)
        second=self.geo.rotational_surfaces([0,0,0],[0,0,1],offset=first['nextOffset'])
        self.assertEqual([i['status'] for i in second['items']],['nonrotational','unknown'])
        self.assertIsNone(second['nextOffset'])
        self.assertAlmostEqual(first['modelingTolerance_mm'],1e-5)

    def test_face_distance_uses_actual_faces_and_returns_native_endpoints_in_mm(self):
        first, second = Obj(name='trimmed first'), Obj(name='trimmed second')
        self.body.faces = Collection(first, second)
        received = []
        def measure(a, b):
            received.append((a, b))
            return Obj(value=.04, positionOne=Point(.2, .5, .3), positionTwo=Point(.24, .5, .3))
        self.app.measureManager.measureMinimumDistance = measure
        result = self.geo.face_distance(0, 1)
        self.assertEqual(received, [(first, second)])
        self.assertEqual(result['status'], 'measured')
        self.assertAlmostEqual(result['distance_mm'], .4)
        self.assertEqual(result['closestPoints_mm'], [[2, 5, 3], [2.4, 5, 3]])
        self.assertEqual(result['faceIndices'], [0, 1])
        self.assertEqual(result['revision'], 'r1')
        self.assertAlmostEqual(result['modelingTolerance_mm'], 1e-5)
        self.assertNotIn('thickness_mm', result)
        self.app.measureManager.measureMinimumDistance = lambda a, b: Obj(value=0, positionOne=Point(0,0,0), positionTwo=Point(0,0,0))
        self.assertEqual(self.geo.face_distance(0, 1)['distance_mm'], 0)

    def test_face_distance_failure_does_not_become_zero_or_an_infinite_plane_measurement(self):
        self.body.faces = Collection(Obj(), Obj())
        for result in (None, Obj(value=float('nan')), Obj(value=-1), Obj(value=True),
                       Obj(value=.1, positionOne=None, positionTwo=vector(0,0,0))):
            self.app.measureManager.measureMinimumDistance = lambda a, b: result
            measured = self.geo.face_distance(0, 1)
            self.assertEqual(measured['status'], 'unknown')
            self.assertNotIn('distance_mm', measured)
        def unsupported(a, b):
            raise RuntimeError('Unsupported native faces')
        self.app.measureManager.measureMinimumDistance = unsupported
        self.assertIn('Unsupported native faces', self.geo.face_distance(0, 1)['reason'])

    def test_component_face_distance_uses_proxy_and_inverse_rigid_placement(self):
        root = self.body.parentComponent
        component = Obj(parentDesign=root.parentDesign)
        self.body.parentComponent = component
        inverse = Obj(invert=lambda: True, point=lambda x,y,z: (y+3, 7-x, z-2))
        placement = Obj(getAsCoordinateSystem=lambda: (Point(7,-3,2), vector(0,1,0), vector(-1,0,0), vector(0,0,1)),
                        copy=lambda: inverse, isEqualTo=lambda other: other is placement)
        occurrence = Obj(isValid=True, transform2=placement)
        root.allOccurrencesByComponent = lambda selected: Collection(occurrence) if selected is component else Collection()
        proxies = [Obj(name='first proxy'), Obj(name='second proxy')]
        self.body.faces = Collection(*(Obj(createForAssemblyContext=lambda o, p=p: p if o is occurrence else None) for p in proxies))
        calls = []
        def measure(a,b):
            calls.append((a,b))
            return Obj(value=.04, positionOne=Point(6.5,-2.8,2.3), positionTwo=Point(6.5,-2.76,2.3))
        self.app.measureManager.measureMinimumDistance = measure
        result = self.geo.face_distance(0,1)
        self.assertEqual(calls, [tuple(proxies)])
        self.assertEqual(result['status'], 'measured')
        for actual, expected in zip(result['closestPoints_mm'][0], (2,5,3)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(result['closestPoints_mm'][1], (2.4,5,3)):
            self.assertAlmostEqual(actual, expected)
        placement.isEqualTo = lambda other: False
        self.assertIn('placement changed', self.geo.face_distance(0,1)['reason'])
        placement.getAsCoordinateSystem = lambda: (Point(0,0,0),vector(2,0,0),vector(0,1,0),vector(0,0,1))
        self.assertIn('rigid', self.geo.face_distance(0,1)['reason'])
        self.assertEqual(len(calls), 2)
        root.allOccurrencesByComponent = lambda selected: Collection()
        self.assertIn('No root-context occurrence', self.geo.face_distance(0,1)['reason'])

    def test_face_distance_rejects_bad_indices_and_changed_or_cancelled_measurements(self):
        self.body.faces = Collection(Obj(), Obj())
        for pair in ((0, 0), (-1, 1), (0, 2), (True, 1), (0, 1.0)):
            with self.assertRaisesRegex(ValueError, 'two distinct'):
                self.geo.face_distance(*pair)
        def change(a, b):
            self.body.revisionId = 'r2'
            return Obj(value=.1, positionOne=Point(0,0,0), positionTwo=Point(.1,0,0))
        self.app.measureManager.measureMinimumDistance = change
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.geo.face_distance(0, 1)
        self.body.revisionId = 'r1'
        def cancel(a, b):
            self.geo.cancelled = lambda: True
            raise RuntimeError('Native failure after cancellation')
        self.app.measureManager.measureMinimumDistance = cancel
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.geo.face_distance(0, 1)

    def test_sheet_rule_is_metadata_and_imported_solids_are_not_assumed_foldable(self):
        rule=Obj(name='Fixture',thickness=Obj(value=.2),gap=Obj(value=.02),kFactor=.4)
        self.body.parentComponent=Obj(activeSheetMetalRule=rule,flatPattern=None)
        self.body.isSheetMetal=True
        result=self.geo.sheet_metal()
        self.assertEqual(result['rule']['thickness_mm'],2)
        self.assertEqual(result['rule']['gap_mm'],.2)
        self.assertFalse(result['componentFlatPatternPresent'])
        self.body.isSheetMetal=False
        result=self.geo.sheet_metal()
        self.assertEqual(result['status'],'unknown')
        self.assertNotIn('rule',result)

    def test_existing_bend_lines_use_native_angles_and_preserve_failed_pages(self):
        first, second = Obj(length=2), Obj(length=3)
        pattern = Obj(foldedBody=Obj(nativeObject=self.body), bendLinesBody=Obj(edges=Collection(first, second)),
                      getBendInfo=lambda edge: (True, True, math.pi/2) if edge is first else (False, None, None))
        self.body.isSheetMetal = True
        self.body.parentComponent = Obj(flatPattern=pattern)
        page1 = self.geo.sheet_bends(limit=1)
        self.assertEqual(page1['items'][0]['angle_deg'], 90)
        self.assertEqual(page1['items'][0]['lineLength_mm'], 20)
        self.assertTrue(page1['items'][0]['isBendUp'])
        self.assertEqual(page1['nextOffset'], 1)
        page2 = self.geo.sheet_bends(offset=page1['nextOffset'], limit=1)
        self.assertEqual(page2['items'][0]['status'], 'unknown')
        self.assertIsNone(page2['nextOffset'])
        self.assertEqual(page2['totalLines'], 2)
        pattern.getBendInfo = lambda edge: (True, None, math.pi/2)
        self.assertEqual(self.geo.sheet_bends()['items'][0]['status'], 'unknown')

    def test_missing_foreign_or_non_sheet_patterns_are_not_created_or_assumed_valid(self):
        self.body.isSheetMetal = False
        self.assertEqual(self.geo.sheet_bends()['status'], 'unknown')
        self.body.isSheetMetal = True
        self.body.parentComponent = Obj(flatPattern=None)
        self.assertIn('No existing flat pattern', self.geo.sheet_bends()['reason'])
        pattern = Obj(foldedBody=Obj(nativeObject=None), bendLinesBody=None)
        self.body.parentComponent.flatPattern = pattern
        self.assertIn('different', self.geo.sheet_bends()['reason'])
        pattern.foldedBody = self.body
        self.assertEqual(self.geo.sheet_bends()['status'], 'unknown')
        pattern.bendLinesBody = Obj(edges=Collection())
        self.assertEqual(self.geo.sheet_bends()['totalLines'], 0)
        self.body.revisionId = 'r2'
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.geo.sheet_bends()

    def test_normal_thickness_measures_material_and_never_substitutes_a_neighbor(self):
        self.app.pointTolerance=1e-6
        self.app.vectorAngleTolerance=1e-10
        self.core.Point3D=Obj(create=vector)
        self.core.ObjectCollection=Obj(create=Collection)
        self.geo.fusion=Obj(PointContainment=Obj(PointInsidePointContainment=1),
            BRepEntityTypes=Obj(BRepFaceEntityType=2), BRepFace=Obj(cast=lambda value:value))
        self.body.isSolid=True
        self.body.pointContainment=lambda point:1
        start=Obj(pointOnFace=vector(0,0,.2),entityToken='start',
                  evaluator=Obj(getNormalAtPoint=lambda point:(True,vector(0,0,1))))
        end=Obj(body=self.body,entityToken='exit',evaluator=Obj(getNormalAtPoint=lambda point:(True,vector(0,0,-1))))
        self.body.faces=Collection(start,end)
        def ray(origin,direction,kind,tolerance,visible,hits):
            self.assertFalse(visible)
            self.assertLess(origin.z,.2)
            hits.values.append(vector(0,0,0))
            return Collection(end)
        self.body.parentComponent=Obj(findBRepUsingRay=ray)
        result=self.geo.normal_thickness(0)
        self.assertEqual(result['thickness_mm'],2)
        self.assertEqual(result['samplePoint_mm'],[0,0,2])
        end.body=Obj(nativeObject=None)
        self.assertEqual(self.geo.normal_thickness(0)['status'],'unknown')
        self.body.pointContainment=lambda point:0
        self.assertIn('not confirmed inside',self.geo.normal_thickness(0)['reason'])

    def test_void_shell_paging_distinguishes_sealed_space_and_open_geometry(self):
        self.body.isSolid=True
        outer=Obj(isClosed=True,isVoid=False,entityToken='outer')
        inner=Obj(isClosed=True,isVoid=True,entityToken='inner',volume=-.125)
        lump=Obj(isClosed=True,shells=Collection(outer,inner))
        self.body.lumps=Collection(lump)
        first=self.geo.enclosed_voids(limit=1)
        self.assertFalse(first['items'][0]['sealedVoid'])
        self.assertEqual(first['nextOffset'],1)
        second=self.geo.enclosed_voids(offset=first['nextOffset'])
        self.assertTrue(second['items'][0]['sealedVoid'])
        self.assertEqual(second['items'][0]['enclosedVolume_mm3'],125)
        self.assertIsNone(second['nextOffset'])
        self.body.isSolid=False
        self.assertEqual(self.geo.enclosed_voids()['status'],'unknown')

    def test_failed_shell_volume_preserves_detected_void_without_claiming_zero(self):
        class Shell:
            isClosed=True
            isVoid=True
            @property
            def volume(self):
                raise RuntimeError('InternalValidationError')
        self.body.isSolid=True
        self.body.lumps=Collection(Obj(isClosed=True,shells=Collection(Shell())))
        result=self.geo.enclosed_voids()['items'][0]
        self.assertTrue(result['sealedVoid'])
        self.assertEqual(result['volumeStatus'],'unknown')
        self.assertNotIn('enclosedVolume_mm3',result)

    def wall(self, radius=.2, length=.5, inward=True):
        edges = [Obj(geometry=Obj(kind='circle', center=vector(0, 0, z), radius=radius)) for z in (0, length)]
        return Obj(geometry=Obj(kind='cylinder', radius=radius, axis=vector(0,0,1), origin=vector(0,0,0)),
                   loops=Collection(*(Obj(edges=Collection(e)) for e in edges)),
                   pointOnFace=vector(radius,0,length/2), evaluator=Obj(getNormalAtPoint=lambda point: (True, vector(-1 if inward else 1,0,0))),
                   area=2*math.pi*radius*length, entityToken='wall')

    def test_full_cylindrical_wall_converts_units_and_distinguishes_outside(self):
        self.body.faces = Collection(self.wall(), self.wall(inward=False))
        report = self.geo.cylindrical_walls()
        self.assertEqual(report['items'][0]['diameter_mm'], 4)
        self.assertEqual(report['items'][0]['axial_span_mm'], 5)
        self.assertEqual([v['side'] for v in report['items']], ['internal', 'external'])
        self.assertIn('not complete holes', report['scope'])

    def test_partial_and_intersected_cylinders_are_unsupported(self):
        a, b = self.wall(), self.wall()
        a.loops = Collection(Obj(edges=Collection(Obj(geometry=Obj(kind='arc')))))
        b.area *= .75
        self.body.faces = Collection(a, b)
        report = self.geo.cylindrical_walls()
        self.assertFalse(report['items'])
        self.assertEqual(len(report['unsupported']), 2)

    def test_partial_cylinder_radius_is_distinct_from_complete_band_recognition(self):
        internal,external=self.wall(radius=.1),self.wall(radius=.3,inward=False)
        internal.loops=Collection(Obj(edges=Collection(Obj(geometry=Obj(kind='arc')))))
        internal.area /= 4
        self.body.faces=Collection(Obj(geometry=Obj(kind='plane')),internal,external)
        first=self.geo.cylindrical_surfaces(limit=1)
        self.assertEqual(first['nextOffset'],2)
        self.assertEqual(first['nonCylindricalFaces'],1)
        self.assertEqual(first['items'][0]['radius_mm'],1)
        self.assertEqual(first['items'][0]['side'],'internal')
        self.assertNotIn('axial_span_mm',first['items'][0])
        second=self.geo.cylindrical_surfaces(offset=first['nextOffset'])
        self.assertEqual(second['items'][0]['side'],'external')
        self.assertIsNone(second['nextOffset'])
        self.assertEqual(len(self.geo.cylindrical_walls()['unsupported']),1)

    def test_open_or_unoriented_cylinders_keep_radius_but_never_claim_internal(self):
        face=self.wall()
        self.body.faces=Collection(face)
        self.body.isSolid=False
        self.assertEqual(self.geo.cylindrical_surfaces()['items'][0]['side'],'unknown')
        self.assertEqual(self.geo.cylindrical_walls()['items'][0]['side'],'unknown')
        self.body.isSolid=True
        face.evaluator=Obj(getNormalAtPoint=lambda point:(False,None))
        item=self.geo.cylindrical_surfaces()['items'][0]
        self.assertEqual(item['radius_mm'],2)
        self.assertEqual(item['side'],'unknown')
        self.assertIn('unavailable',item['sideReason'])

    def test_page_offset_counts_faces_not_only_matches(self):
        self.body.faces = Collection(Obj(geometry=Obj(kind='plane')), self.wall(), self.wall())
        first = self.geo.cylindrical_walls(limit=1)
        self.assertEqual(first['nextOffset'], 2)
        second = self.geo.cylindrical_walls(offset=first['nextOffset'], limit=1)
        self.assertIsNone(second['nextOffset'])

    def test_envelope_uses_requested_axes_and_normalizes(self):
        report = self.geo.envelope([2,0,0], [0,4,0])
        self.assertEqual(report['dimensions_mm'], [60,40,8])
        self.assertEqual(report['axes'], [[1,0,0],[0,1,0],[0,0,1]])
        with self.assertRaises(ValueError):
            self.geo.envelope([1,0,0], [1,0,0])
        with self.assertRaises(ValueError):
            self.geo.envelope([0,0,0], [0,1,0])

    def test_extension_failure_is_unknown_not_empty_success(self):
        def unavailable(*args):
            raise RuntimeError('Requires the Manufacturing Extension to be active.')
        self.cam.RecognizedHolesInput = Obj(create=lambda: Obj())
        self.cam.RecognizedHole = Obj(recognizeHolesWithInput=unavailable)
        report = self.geo.holes()
        self.assertEqual(report['status'], 'unknown')
        self.assertNotIn('items', report)
        self.assertIn('Extension', report['reason'])

    def test_recognized_holes_keep_segments_warnings_and_pagination(self):
        seg = Obj(holeSegmentType=1, height=.5, topDiameter=.4, bottomDiameter=.4)
        hole = Obj(totalLength=.5, topDiameter=.4, bottomDiameter=.4, isThrough=False,
                   hasWarnings=True, hasErrors=False, axis=vector(0,0,-1), top=vector(2,2,0),
                   segmentCount=1, segment=lambda i: seg)
        self.cam.HoleSegmentType = Obj(HoleSegmentTypeCylinder=1, HoleSegmentTypeCone=2, HoleSegmentTypeFlat=3, HoleSegmentTypeTorus=4)
        self.cam.RecognizedHolesInput = Obj(create=lambda: Obj())
        self.cam.RecognizedHole = Obj(recognizeHolesWithInput=lambda *args: [hole, hole])
        report = self.geo.holes(limit=1)
        self.assertEqual(report['nextOffset'], 1)
        self.assertEqual(report['items'][0]['depth_mm'], 5)
        self.assertTrue(report['items'][0]['hasWarnings'])
        self.assertEqual(report['items'][0]['segments'][0]['type'], 'cylinder')

    def test_changed_geometry_refuses_reusing_measurement_context(self):
        self.body.revisionId = 'r2'
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.geo.envelope([1,0,0], [0,1,0])

    def test_planar_overhangs_distinguish_lowest_plane_and_unknown_curves(self):
        def face(normal, z):
            return Obj(geometry=Obj(kind='plane'), pointOnFace=vector(1,1,z),
                       evaluator=Obj(getNormalAtPoint=lambda p: (True, normal)), area=2, entityToken='face')
        self.body.faces = Collection(face(vector(0,0,-1),0), face(vector(0,0,-1),.5),
            face(vector(0,0,1),.8), face(vector(1,0,0),.5), self.wall())
        result = self.geo.planar_overhangs([1,0,0], [0,1,0])
        self.assertEqual(len(result['items']), 2)
        self.assertTrue(result['items'][0]['lowestHorizontalFace'])
        self.assertFalse(result['items'][1]['lowestHorizontalFace'])
        self.assertEqual(result['items'][1]['tilt_from_build_plane_deg'], 0)
        self.assertEqual(result['items'][1]['area_mm2'], 200)
        self.assertEqual(len(result['unsupported']), 1)

    def test_pocket_depth_preserves_attack_vector_and_scope(self):
        self.cam.RecognizedPocket = Obj(recognizePockets=lambda *args: Collection(Obj(depth=.5,isThrough=False,isClosed=True)))
        result = self.geo.pockets([0,0,-2])
        self.assertEqual(result['attackDirection'], [0,0,-1])
        self.assertEqual(result['items'][0]['depth_mm'], 5)
        self.assertIn('No minimum corner radius', result['scope'])

    def test_overhang_query_does_not_classify_open_surface_normals(self):
        self.body.isSolid = False
        self.body.faces = Collection(Obj())  # No normal should be read.
        self.app.measureManager.getOrientedBoundingBox = lambda *args: self.fail('No envelope needed for an unsupported surface')
        result = self.geo.planar_overhangs([1,0,0], [0,1,0])
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['items'], [])
        self.assertIsNone(result['nextOffset'])
        self.assertEqual(result['scannedFaces'], 0)
        self.assertIn('solid body', result['reason'])
        self.assertIn('Do not infer no overhangs', result['recovery'])
        self.body.revisionId = 'r2'
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.geo.planar_overhangs([1,0,0], [0,1,0])

    def test_overhang_normal_failure_is_unknown_and_paging_continues(self):
        self.body.faces = Collection(
            Obj(geometry=Obj(kind='plane'), pointOnFace=vector(0,0,0),
                evaluator=Obj(getNormalAtPoint=lambda p: (False, None))),
            Obj(geometry=Obj(kind='plane'), pointOnFace=vector(0,0,.5),
                evaluator=Obj(getNormalAtPoint=lambda p: (True, vector(0,0,-1))),
                area=1, entityToken='ceiling'))
        first = self.geo.planar_overhangs([1,0,0], [0,1,0], limit=1)
        self.assertEqual(first['items'], [])
        self.assertEqual(first['unsupported'][0]['reason'], 'Face normal unavailable.')
        self.assertEqual(first['nextOffset'], 1)
        second = self.geo.planar_overhangs([1,0,0], [0,1,0], offset=first['nextOffset'], limit=1)
        self.assertEqual(second['items'][0]['faceToken'], 'ceiling')
        self.assertFalse(second['items'][0]['lowestHorizontalFace'])
        self.assertIsNone(second['nextOffset'])


if __name__ == '__main__':
    unittest.main()
