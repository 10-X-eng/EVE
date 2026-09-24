"""Bounded native Fusion measurements; no universal manufacturing thresholds.

All calls run on Fusion's main thread. Native recognition is one indivisible
calculation; paging bounds returned data, not time spent inside that calculation.
"""
import math

from .dfm import finite, revision, native


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
    def __init__(self, body, app, core, cam, cancelled=lambda: False, fusion=None):
        self.body, self.app, self.core, self.cam = body, app, core, cam
        self.fusion = fusion
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

    def sheet_metal(self):
        """Read rule metadata without flattening or converting the body."""
        self._check()
        try:
            folded = self.body.isSheetMetal
            component = self.body.parentComponent
            rule = component.activeSheetMetalRule
            pattern = component.flatPattern
            result = {'status': 'measured' if folded and rule is not None else 'unknown',
                      'isSheetMetal': bool(folded), 'componentFlatPatternPresent': pattern is not None}
            if folded and rule is not None:
                result['rule'] = {'name': str(rule.name)[:200],
                    'thickness_mm': 10*finite(rule.thickness.value),
                    'gap_mm': 10*finite(rule.gap.value), 'kFactor': finite(rule.kFactor)}
            else:
                result['reason'] = 'The body is not a native folded sheet-metal part with an active rule. No thickness or bend capability was inferred.'
        except (AttributeError, RuntimeError) as error:
            result = {'status': 'unknown', 'reason': str(error)[:400],
                      'recovery': 'Inspect the installed sheet-metal API. Do not convert or flatten the model to make an inspection succeed.'}
        self._check()
        return {**result, 'revision': self._revision,
                'scope': 'Configured component rule, not measured wall thickness or supplier capability. Existing component flat-pattern presence does not prove its currency, bend sequence or tooling clearance. No geometry was created.'}

    def cylindrical_surfaces(self, offset=0, limit=10):
        """Analytic radii, including partial pocket-corner faces; no feature recognition."""
        page(offset, limit)
        self._check()
        faces = self.body.faces
        values, scanned, other = [], 0, 0
        for index in range(offset, min(faces.count, offset+200)):
            self._check()
            face = faces.item(index)
            cylinder = self.core.Cylinder.cast(face.geometry)
            scanned += 1
            if cylinder is None:
                other += 1
                continue
            radius = finite(cylinder.radius)
            if radius <= 0:
                values.append({'faceIndex':index,'status':'unknown','reason':'Cylinder radius is not positive.'})
            else:
                side, reason = self._cylinder_side(face, cylinder)
                item = {'faceIndex':index,'faceToken':face.entityToken,'status':'measured',
                    'radius_mm':10*radius,'axis':unit(xyz(cylinder.axis)),
                    'axisOrigin_mm':[10*v for v in xyz(cylinder.origin)],'side':side}
                if reason:
                    item['sideReason'] = reason
                values.append(item)
            if len(values) >= limit:
                break
        self._check()
        return {'status':'measured','items':values,'scannedFaces':scanned,'nonCylindricalFaces':other,
            'totalFaces':faces.count,'nextOffset':offset+scanned if offset+scanned<faces.count else None,
            'revision':self._revision,
            'scope':'Analytic cylindrical surface radii in native body coordinates, including partial faces. Internal/external uses solid-face normals; open surfaces remain unknown. Sharp edges, non-cylindrical faces, trimming, pocket membership, complete-hole diameter/depth, cutter approach/reach and collision clearance are unassessed. No matches does not prove there are no tight or sharp corners. Confirm that a face is an intended pocket corner before comparing its radius with a cutter; an internal cylinder can instead be a bore. Radius equality alone does not establish a suitable machining strategy.'}

    def normal_thickness(self, face_index):
        """One inward normal ray at Fusion's interior face sample, not a global minimum."""
        self._check()
        if type(face_index) is not int or not 0 <= face_index < self.body.faces.count:
            raise ValueError('Use a current face index from this body.')
        if self.fusion is None:
            raise ValueError('The Fusion ray-query API is unavailable in this measurement context.')
        face = self.body.faces.item(face_index)
        def unknown(reason):
            self._check()
            return {'status': 'unknown', 'faceIndex': face_index, 'reason': reason, 'revision': self._revision}
        if not self.body.isSolid:
            return unknown('A solid body is required to distinguish material from empty space.')
        point = face.pointOnFace
        ok, normal = face.evaluator.getNormalAtPoint(point)
        if not ok:
            return unknown('The start face normal is unavailable.')
        direction = [-v for v in unit(xyz(normal))]
        tolerance = finite(self.app.pointTolerance)
        if tolerance <= 0:
            return unknown('Fusion modeling tolerance is unavailable.')
        # Move past the boundary's numerical uncertainty, then explicitly check
        # material containment. This offset is not a minimum printable wall rule.
        origin = self.core.Point3D.create(*(v+10*tolerance*d for v,d in zip(xyz(point),direction)))
        if self.body.pointContainment(origin) != self.fusion.PointContainment.PointInsidePointContainment:
            return unknown('The inward ray origin is not confirmed inside solid material. Thin, ambiguous or invalid local geometry is unassessed.')
        hits = self.core.ObjectCollection.create()
        entities = self.body.parentComponent.findBRepUsingRay(origin, self.core.Vector3D.create(*direction),
            self.fusion.BRepEntityTypes.BRepFaceEntityType, tolerance, False, hits)
        self._check()
        if entities.count != hits.count or entities.count > 200:
            return unknown('Ray intersections are inconsistent or exceed the 200-hit traversal limit.')
        for index in range(entities.count):
            self._check()
            target = self.fusion.BRepFace.cast(entities.item(index))
            if target is None or native(target.body) != self.body:
                continue
            hit = hits.item(index)
            delta = [h-p for h,p in zip(xyz(hit),xyz(point))]
            distance = dot(delta,direction)
            radial = math.hypot(*(v-distance*d for v,d in zip(delta,direction)))
            ok, exit_normal = target.evaluator.getNormalAtPoint(hit)
            self._check()
            if (distance <= 10*tolerance or radial > tolerance or not ok
                    or dot(unit(xyz(exit_normal)), direction) <= math.sin(finite(self.app.vectorAngleTolerance))):
                return unknown('The nearest same-body intersection is near a boundary, off the ray or not a confirmed outward crossing.')
            return {'status':'measured', 'faceIndex':face_index, 'faceToken':face.entityToken,
                'exitFaceToken':target.entityToken, 'samplePoint_mm':[10*v for v in xyz(point)],
                'exitPoint_mm':[10*v for v in xyz(hit)], 'direction':direction,
                'thickness_mm':10*distance, 'modelingTolerance_mm':10*tolerance, 'revision':self._revision,
                'scope':'Material distance along one inward normal at one interior face point. Not the minimum wall thickness, opposite-face spacing everywhere, feature diameter, or proof of printability. Thin regions elsewhere, drainage, trapped volumes and strength remain unassessed.'}
        return unknown('No outward crossing of this same body was found. Do not use another component as the opposite wall.')

    def enclosed_voids(self, lump_index=0, offset=0, limit=10):
        """Use native shell topology to identify sealed cavities, without inferring drainage."""
        page(offset,limit)
        self._check()
        lumps = self.body.lumps
        if type(lump_index) is not int or not 0 <= lump_index < lumps.count:
            raise ValueError('Use an existing lump index; inspect this body before checking voids.')
        lump = lumps.item(lump_index)
        if not self.body.isSolid or not lump.isClosed:
            return {'status':'unknown', 'reason':'Closed solid topology is required to classify sealed voids.', 'revision':self._revision}
        shells = lump.shells
        result = []
        for index in range(offset, min(shells.count, offset+limit)):
            self._check()
            shell = shells.item(index)
            closed = bool(shell.isClosed)
            void = bool(shell.isVoid)
            # BRepShell.entityToken can raise InternalValidationError on a valid
            # newly evaluated shell. Revision-bound indices suffice for this query.
            entry = {'shellIndex':index, 'isClosed':closed,
                     'isVoid':void, 'sealedVoid':closed and void}
            if entry['sealedVoid']:
                try:
                    entry['enclosedVolume_mm3'] = 1000*abs(finite(shell.volume))
                    entry['volumeStatus'] = 'measured'
                except (AttributeError, RuntimeError) as error:
                    entry.update(volumeStatus='unknown', volumeReason=str(error)[:400],
                                 recovery='The sealed void is detected, but Fusion did not provide its volume. Do not substitute zero or alter geometry to obtain it.')
            result.append(entry)
        self._check()
        return {'status':'measured', 'lumpIndex':lump_index, 'totalLumps':lumps.count,
                'items':result, 'totalShells':shells.count,
                'nextOffset':offset+limit if offset+limit<shells.count else None,
                'revision':self._revision,
                'scope':'Native closed void shells in this solid lump. Inspect all pages and lumps. Sealed voids can retain resin or powder; absence does not prove drain/escape-hole size, orientation, flow, wash access or lack of printing suction cups. FDM and deliberately sealed parts need different process decisions.'}

    def rotational_surfaces(self, axis_origin_mm, axis_direction, offset=0, limit=10):
        """Classify analytic surfaces AND their circular trimming about a chosen axis."""
        page(offset, limit)
        if not isinstance(axis_origin_mm, (list, tuple)) or len(axis_origin_mm) != 3:
            raise ValueError('Supply the turning-axis origin in millimeters, in native body coordinates.')
        origin = [finite(v)/10 for v in axis_origin_mm]
        axis = unit(axis_direction)
        self._check()
        distance_tolerance = finite(self.app.pointTolerance)
        angle_tolerance = finite(self.app.vectorAngleTolerance)
        if distance_tolerance <= 0 or angle_tolerance <= 0:
            raise ValueError('Fusion modeling tolerances are unavailable. Do not invent a manufacturing tolerance.')

        def on_axis(point):
            delta = [v-o for v,o in zip(xyz(point), origin)]
            projection = dot(delta, axis)
            return math.hypot(*(v-projection*a for v,a in zip(delta,axis))) <= distance_tolerance

        def parallel(direction):
            v = unit(xyz(direction))
            cross = [v[1]*axis[2]-v[2]*axis[1], v[2]*axis[0]-v[0]*axis[2], v[0]*axis[1]-v[1]*axis[0]]
            return math.atan2(math.hypot(*cross), abs(dot(v,axis))) <= angle_tolerance

        result = []
        faces = self.body.faces
        for index in range(offset, min(faces.count, offset+limit)):
            self._check()
            face = faces.item(index)
            surface = face.geometry
            kind, analytic, aligned = None, None, False
            for name in ('Plane','Cylinder','Cone','Torus','Sphere'):
                cast = getattr(self.core, name, None)
                analytic = cast.cast(surface) if cast else None
                if analytic is not None:
                    kind = name
                    break
            entry = {'faceIndex': index, 'faceToken': face.entityToken, 'surface': kind or 'unsupported', 'status': 'unknown'}
            if kind == 'Plane':
                aligned = parallel(analytic.normal)
            elif kind == 'Sphere':
                aligned = on_axis(analytic.origin)
            elif kind:
                aligned = parallel(analytic.axis) and on_axis(analytic.origin)
            if kind and not aligned:
                entry.update(status='nonrotational', reason='This analytic surface is not rotationally invariant about the supplied axis. A secondary operation or different axis may be needed.')
            elif kind:
                # A coaxial underlying cylinder alone is insufficient: flats,
                # windows and partial sweeps can trim it into a non-rotational face.
                if face.edges.count > 64:
                    entry['reason'] = 'Face trimming exceeds this bounded check (64 edges).'
                else:
                    circular = True
                    for edge_index in range(face.edges.count):
                        circle = self.core.Circle3D.cast(face.edges.item(edge_index).geometry)
                        if circle is None or not on_axis(circle.center) or not parallel(circle.normal):
                            circular = False
                            break
                    if circular and (face.edges.count or kind in ('Sphere','Torus')):
                        entry.update(status='compatible', reason='Analytic surface and every boundary circle are coaxial with the supplied axis.')
                    else:
                        entry['reason'] = 'Trimming is not verified as full coaxial circles; split, intersected or partial surfaces remain unassessed.'
            else:
                entry['reason'] = 'This surface representation is unsupported; do not treat an unrecognized surface as a turning failure.'
            result.append(entry)
        self._check()
        return {'status': 'measured', 'items': result, 'totalFaces': faces.count,
                'nextOffset': offset+limit if offset+limit < faces.count else None,
                'axisOrigin_mm': list(axis_origin_mm), 'axisDirection': axis,
                'modelingTolerance_mm': 10*distance_tolerance, 'modelingAngleTolerance_rad': angle_tolerance,
                'revision': self._revision,
                'scope': 'Paged surface-and-trim evidence about an explicitly chosen turning axis. Review every page; this is not a whole-part lathe approval. No chucking, tool approach, groove-tool fit, slenderness, deflection or stock allowance is assessed. Modeling tolerances are numerical kernel tolerances, not manufacturing limits.'}

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
        side, reason = self._cylinder_side(face, cylinder)
        return {'diameter_mm': 20*finite(cylinder.radius), 'axial_span_mm': 10*span,
                'area_mm2': 100*finite(face.area), 'axis': axis,
                'side': side, **({'sideReason':reason} if reason else {})}

    def _cylinder_side(self, face, cylinder):
        if not self.body.isSolid:
            return 'unknown', 'The body is not solid; face orientation does not establish inside versus outside.'
        point = face.pointOnFace
        ok, normal = face.evaluator.getNormalAtPoint(point)
        if not ok:
            return 'unknown', 'The solid-face normal is unavailable.'
        axis = unit(xyz(cylinder.axis))
        offset = [p-o for p,o in zip(xyz(point),xyz(cylinder.origin))]
        radial = [v-dot(offset,axis)*a for v,a in zip(offset,axis)]
        side = dot(unit(radial),unit(xyz(normal)))
        if abs(side)<.999999:
            return 'unknown', 'The face normal is not consistent with a radial cylindrical normal.'
        return ('internal' if side<0 else 'external'), None

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
