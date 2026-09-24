"""Independent analytic fixtures for native DFM measurement adapters."""
import math
from types import SimpleNamespace as Obj
import unittest

from test_fusion_bridge import Collection
from steve.dfm_geometry import DfmGeometry


def vector(x, y, z):
    return Obj(x=x, y=y, z=z)


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.core = Obj(Vector3D=Obj(create=vector),
                        Plane=Obj(cast=lambda geo: geo if getattr(geo, 'kind', '') == 'plane' else None),
                        Cylinder=Obj(cast=lambda geo: geo if getattr(geo, 'kind', '') == 'cylinder' else None),
                        Circle3D=Obj(cast=lambda geo: geo if getattr(geo, 'kind', '') == 'circle' else None))
        self.body = Obj(revisionId='r1', faces=Collection(), isSolid=True)
        self.cam = Obj()
        self.app = Obj(measureManager=Obj(getOrientedBoundingBox=lambda body, x, y: Obj(length=6, width=4, height=.8, centerPoint=vector(3,2,.4))))
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


if __name__ == '__main__':
    unittest.main()
