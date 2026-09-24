"""Explicit face marks; prototype contract: planar horizontal support surfaces."""
import bisect
from mathutils import Vector

ATTRIBUTE = 'blendgen_spawn'


def marked_triangles(context):
    triangles = []
    for obj in context.scene.objects:
        if obj.type != 'MESH' or obj.hide_render:
            continue
        attr = obj.data.attributes.get(ATTRIBUTE)
        if attr is None:
            continue
        if obj.modifiers:
            raise ValueError(f'{obj.name}: apply modifiers before marking spawn faces')
        obj.data.calc_loop_triangles()
        for tri in obj.data.loop_triangles:
            if not attr.data[tri.polygon_index].value:
                continue
            a,b,c = [obj.matrix_world @ obj.data.vertices[i].co for i in tri.vertices]
            normal = (b-a).cross(c-a)
            if normal.length < 1e-9:
                continue
            if normal.normalized().z < .9999:
                raise ValueError(f'{obj.name}: spawn faces must be horizontal and face upward')
            triangles.append((a,b,c))
    if not triangles:
        raise ValueError('Mark at least one top face as a valid spawn area')
    return triangles


class SurfaceSampler:
    def __init__(self, triangles):
        self.triangles = triangles
        self.weights = []
        total = 0
        for a,b,c in triangles:
            total += (b-a).cross(c-a).length / 2
            self.weights.append(total)

    def sample(self, rng):
        index = min(bisect.bisect_left(self.weights, rng.random()*self.weights[-1]),len(self.triangles)-1)
        a,b,c = self.triangles[index]
        u,v = rng.random(),rng.random()
        if u+v > 1: u,v = 1-u,1-v
        return a + u*(b-a) + v*(c-a)

    def supports(self, vertices, height, clearance):
        # Require the entire rectangular footprint to fit within one marked triangle
        # or marked coplanar rectangle. Grid alone would miss narrow holes, so use
        # exact area coverage of the footprint by non-overlapping mesh triangles.
        xmin=min(v.x for v in vertices)-clearance; xmax=max(v.x for v in vertices)+clearance
        ymin=min(v.y for v in vertices)-clearance; ymax=max(v.y for v in vertices)+clearance
        area=0
        for triangle in self.triangles:
            if any(abs(v.z-height)>1e-5 for v in triangle): continue
            polygon=[(v.x,v.y) for v in triangle]
            for axis,limit,keep_greater in ((0,xmin,True),(0,xmax,False),(1,ymin,True),(1,ymax,False)):
                polygon=clip(polygon,axis,limit,keep_greater)
            area += polygon_area(polygon)
        required=(xmax-xmin)*(ymax-ymin)
        return abs(area-required) <= max(1e-8,required*1e-6)


def clip(polygon, axis, limit, greater):
    if not polygon: return []
    output=[]
    for start,end in zip(polygon,polygon[1:]+polygon[:1]):
        si=start[axis]>=limit if greater else start[axis]<=limit
        ei=end[axis]>=limit if greater else end[axis]<=limit
        if si: output.append(start)
        if si != ei:
            t=(limit-start[axis])/(end[axis]-start[axis])
            output.append(tuple(start[i]+t*(end[i]-start[i]) for i in range(2)))
    return output


def polygon_area(poly):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1])))/2 if poly else 0
