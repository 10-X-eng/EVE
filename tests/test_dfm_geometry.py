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
        self.body = Obj(revisionId='r1', faces=Collection())
        self.cam = Obj()
        self.app = Obj(measureManager=Obj(getOrientedBoundingBox=lambda body, x, y: Obj(length=6, width=4, height=.8, centerPoint=vector(3,2,.4))))
        self.geo = DfmGeometry(self.body, self.app, self.core, self.cam)

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
