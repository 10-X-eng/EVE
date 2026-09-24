"""Bounded native Fusion measurements; no universal manufacturing thresholds.

All calls run on Fusion's main thread. Native recognition is one indivisible
calculation; paging bounds returned data, not time spent inside that calculation.
"""
import math

from .dfm import finite, revision


def xyz(value):
    return [finite(value.x), finite(value.y), finite(value.z)]


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def unit(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('Supply three numeric direction components in native body coordinates.')
    values = [finite(v) for v in value]
    length = math.hypot(*values)
    if length < 1e-12:
        raise ValueError('A direction cannot be zero.')
    return [v/length for v in values]


def page(offset, limit):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('Use a nonnegative offset and a limit from 1 to 20.')


class DfmGeometry:
    def __init__(self, body, app, core, cam, cancelled=lambda: False):
        self.body, self.app, self.core, self.cam = body, app, core, cam
        self._revision = revision(body)
        self.cancelled = cancelled

    def _check(self):
        if self.cancelled():
            raise ValueError('DFM measurement cancelled; do not rely on incomplete coverage.')
        if self._revision is None or revision(self.body) != self._revision:
            raise ValueError('Body changed or its revision is unavailable; start a new DFM check.')

    def envelope(self, x_axis, y_axis):
        """Measure a tight oriented envelope in an explicitly supplied build frame."""
        self._check()
        x, y = unit(x_axis), unit(y_axis)
        if abs(dot(x, y)) > 1e-8:
            raise ValueError('Build X and Y directions must be perpendicular.')
        z = [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]
        box = self.app.measureManager.getOrientedBoundingBox(self.body,
            self.core.Vector3D.create(*x), self.core.Vector3D.create(*y))
        self._check()
        return {'status': 'measured', 'dimensions_mm': [10*finite(box.length), 10*finite(box.width), 10*finite(box.height)],
                'axes': [x,y,z], 'revision': self._revision,
                'scope': 'Native body envelope in the supplied frame; excludes supports, brim, raft, fixtures, placement offsets and assembly transforms.'}

    def cylindrical_walls(self, offset=0, limit=10):
        """Full circular bands only: measure walls, never infer complete holes."""
        page(offset, limit)
        self._check()
        faces = self.body.faces
        values, unsupported, scanned = [], [], 0
        for i in range(offset, min(faces.count, offset + 200)):
            self._check()
            face = faces.item(i)
            scanned += 1
            cylinder = self.core.Cylinder.cast(face.geometry)
            if cylinder is None:
                continue
            result = self._wall(face, cylinder)
            if result is None:
                unsupported.append({'faceIndex': i, 'reason': 'Not a verified full circular band; partial, split, intersected or unsupported trimming.'})
            else:
                values.append({'faceIndex': i, 'faceToken': face.entityToken, **result})
            if len(values) + len(unsupported) >= limit:
                break
        self._check()
        return {'status': 'measured', 'items': values, 'unsupported': unsupported,
                'scannedFaces': scanned, 'totalFaces': faces.count,
                'nextOffset': offset + scanned if offset + scanned < faces.count else None,
                'revision': self._revision,
                'scope': 'Full cylindrical wall bands, not complete holes. Axial span is not necessarily drilling depth, tool reach or access. No pocket/counterbore classification.'}

    def planar_overhangs(self, x_axis, y_axis, offset=0, limit=10):
        """Downward planar faces only; slope is measured from the build plane."""
        page(offset, limit)
        frame = self.envelope(x_axis, y_axis)
        x, y, up = frame['axes']
        box = self.app.measureManager.getOrientedBoundingBox(self.body,
            self.core.Vector3D.create(*x), self.core.Vector3D.create(*y))
        bottom = dot(xyz(box.centerPoint), up) - box.height/2
        faces = self.body.faces
        values, unsupported, scanned = [], [], 0
        for i in range(offset, min(faces.count, offset+200)):
            self._check()
            face = faces.item(i)
            scanned += 1
            if self.core.Plane.cast(face.geometry) is None:
                unsupported.append({'faceIndex': i, 'reason': 'Curved face; planar overhang measurement does not assess it.'})
            else:
                point = face.pointOnFace
                ok, normal = face.evaluator.getNormalAtPoint(point)
                if not ok:
                    unsupported.append({'faceIndex': i, 'reason': 'Face normal unavailable.'})
                else:
                    alignment = dot(unit(xyz(normal)), up)
                    if alignment < -1e-9:
                        tilt = math.degrees(math.acos(min(1.0, max(0.0, -alignment))))
                        values.append({'faceIndex': i, 'faceToken': face.entityToken,
                            'tilt_from_build_plane_deg': tilt, 'area_mm2': 100*finite(face.area),
                            'lowestHorizontalFace': abs(alignment+1) < 1e-8 and abs(dot(xyz(point), up)-bottom) < 1e-7})
            if len(values) + len(unsupported) >= limit:
                break
        self._check()
        return {'status': 'measured', 'items': values, 'unsupported': unsupported,
                'scannedFaces': scanned, 'totalFaces': faces.count,
                'nextOffset': offset+scanned if offset+scanned < faces.count else None,
                'axes': frame['axes'], 'revision': self._revision,
                'scope': 'Downward planar faces only. Tilt is 0 degrees for a horizontal underside and 90 for a vertical wall. Lowest horizontal faces are bed-contact candidates only if this placement is chosen. No bridge span, support occlusion, curved-surface, slicer or strength analysis.'}

    def _wall(self, face, cylinder):
        if face.loops.count != 2:
            return None
        circles = []
        for i in range(2):
            loop = face.loops.item(i)
            if loop.edges.count != 1:
                return None
            circle = self.core.Circle3D.cast(loop.edges.item(0).geometry)
            if circle is None or not math.isclose(circle.radius, cylinder.radius, rel_tol=1e-7, abs_tol=1e-9):
                return None
            circles.append(circle)
        axis = unit(xyz(cylinder.axis))
        delta = [b-a for a,b in zip(xyz(circles[0].center), xyz(circles[1].center))]
        span = abs(dot(delta, axis))
        if span <= 1e-9 or not math.isclose(math.hypot(*delta), span, rel_tol=1e-7, abs_tol=1e-9):
            return None
        expected_area = 2*math.pi*cylinder.radius*span
        if not math.isclose(face.area, expected_area, rel_tol=1e-7, abs_tol=1e-9):
            return None
        point = face.pointOnFace
        ok, normal = face.evaluator.getNormalAtPoint(point)
        if not ok:
            return None
        offset = [p-o for p,o in zip(xyz(point), xyz(cylinder.origin))]
        radial = [v-dot(offset,axis)*a for v,a in zip(offset,axis)]
        side = dot(unit(radial), unit(xyz(normal)))
        if abs(side) < .999999:
            return None
        return {'diameter_mm': 20*finite(cylinder.radius), 'axial_span_mm': 10*span,
                'area_mm2': 100*finite(face.area), 'axis': axis,
                'side': 'internal' if side < 0 else 'external'}

    def holes(self, offset=0, limit=10):
        page(offset, limit)
        self._check()
        try:
            settings = self.cam.RecognizedHolesInput.create()
            settings.filterPartialHoles = True
            holes = self.cam.RecognizedHole.recognizeHolesWithInput([self.body], settings)
        except (AttributeError, RuntimeError) as exc:
            return {'status': 'unknown', 'reason': str(exc)[:400],
                    'recovery': 'Native hole recognition is unavailable. Check installed API/extension access. cylindrical_walls can measure supported bands but does not prove complete holes.'}
        self._check()
        result = []
        types = self.cam.HoleSegmentType
        names = {getattr(types, 'HoleSegmentType' + name.title()): name for name in ('cylinder','cone','flat','torus')}
        for index in range(offset, min(len(holes), offset+limit)):
            self._check()
            hole = holes[index]
            segments = []
            for i in range(min(hole.segmentCount, 16)):
                segment = hole.segment(i)
                segments.append({'type': names.get(segment.holeSegmentType, 'unknown'),
                    'height_mm': 10*finite(segment.height), 'top_diameter_mm': 10*finite(segment.topDiameter),
                    'bottom_diameter_mm': 10*finite(segment.bottomDiameter)})
            result.append({'index': index, 'depth_mm': 10*finite(hole.totalLength),
                'top_diameter_mm': 10*finite(hole.topDiameter), 'bottom_diameter_mm': 10*finite(hole.bottomDiameter),
                'axis': xyz(hole.axis), 'top_mm': [10*v for v in xyz(hole.top)], 'isThrough': hole.isThrough,
                'hasWarnings': hole.hasWarnings, 'hasErrors': hole.hasErrors,
                'segments': segments, 'segmentsComplete': hole.segmentCount <= 16})
        return {'status': 'measured', 'items': result, 'total': len(holes),
                'nextOffset': offset+limit if offset+limit < len(holes) else None,
                'revision': self._revision, 'scope': 'Native recognized holes excluding partial holes. Honor warnings/errors and segment completeness. Does not prove tool access or collision clearance.'}

    def pockets(self, attack_direction, offset=0, limit=10):
        page(offset, limit)
        self._check()
        direction = unit(attack_direction)
        try:
            pockets = self.cam.RecognizedPocket.recognizePockets(self.body, self.core.Vector3D.create(*direction))
        except (AttributeError, RuntimeError) as exc:
            return {'status': 'unknown', 'reason': str(exc)[:400],
                    'recovery': 'Check installed pocket recognition API and extension access. Do not report that the body has no pockets.'}
        self._check()
        count = pockets.count
        result = []
        for index in range(offset, min(count, offset+limit)):
            self._check()
            pocket = pockets.item(index)
            result.append({'index': index, 'depth_mm': 10*finite(pocket.depth),
                'isThrough': pocket.isThrough, 'isClosed': pocket.isClosed})
        return {'status': 'measured', 'items': result, 'total': count,
                'nextOffset': offset+limit if offset+limit < count else None,
                'attackDirection': direction, 'revision': self._revision,
                'scope': 'Native pockets for this downward tool direction, excluding bosses. No minimum corner radius, holder clearance, safe toolpath, or feature-face mapping is inferred.'}
