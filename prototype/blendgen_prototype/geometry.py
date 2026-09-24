"""Evaluated world-space geometry and conservative collision policy."""
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def world_geometry(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertices = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        faces = [tuple(t.vertices) for t in mesh.loop_triangles]
        return vertices, faces
    finally:
        evaluated.to_mesh_clear()


def bounds(vertices):
    return (Vector(tuple(min(v[i] for v in vertices) for i in range(3))),
            Vector(tuple(max(v[i] for v in vertices) for i in range(3))))


def overlaps(a, b, gap=0):
    # AABB rejection is intentionally conservative: containment also counts.
    return all(a[1][i] + gap > b[0][i] + 1e-6 and
               b[1][i] + gap > a[0][i] + 1e-6 for i in range(3))


def in_bounds(point, limits):
    return limits is None or all(lo <= v <= hi for v,lo,hi in zip(point,*limits))


class Obstacles:
    """Snapshot visible mesh obstacles once per run; never mutates scene objects."""
    def __init__(self, context, subject):
        self.items = []
        all_vertices, all_faces = [], []
        depsgraph = context.evaluated_depsgraph_get()
        for obj in context.scene.objects:
            if obj.type != 'MESH' or obj == subject or obj.hide_render:
                continue
            vertices, faces = world_geometry(obj, depsgraph)
            if vertices and faces:
                self.items.append((obj, bounds(vertices), BVHTree.FromPolygons(vertices, faces, all_triangles=True)))
                offset=len(all_vertices)
                all_vertices.extend(vertices)
                all_faces.extend(tuple(i+offset for i in face) for face in faces)
        self.tree=BVHTree.FromPolygons(all_vertices,all_faces,all_triangles=True) if all_faces else None

    def collides(self, vertices, gap):
        candidate = bounds(vertices)
        return any(overlaps(candidate, box, gap) for _,box,_ in self.items)

    def clear_view(self, camera_position, vertices):
        # Include every vertex and every surface-triangle probe supplied by caller.
        # Conservative segment checks also test camera inside closed obstacle boxes.
        for _, box, tree in self.items:
            if all(box[0][i] < camera_position[i] < box[1][i] for i in range(3)):
                return False
        for point in vertices:
            delta = point - camera_position
            if delta.length < 1e-6:
                return False
            if self.tree and self.tree.ray_cast(camera_position, delta.normalized(), max(0,delta.length-1e-4))[0] is not None:
                return False
        return True

    def silhouette_visible(self, scene, camera, vertices, faces):
        """Check every subject silhouette pixel center at the current render size.

        Opaque mesh geometry contract; no transparency, volumes, DOF or compositor
        effects. Vertex/triangle probes additionally protect subpixel boundaries.
        """
        from bpy_extras.object_utils import world_to_camera_view
        from math import floor, ceil
        if self.tree is None: return True
        subject=BVHTree.FromPolygons(vertices,faces,all_triangles=True)
        projected=[world_to_camera_view(scene,camera,v) for v in vertices]
        width=max(1,int(scene.render.resolution_x*scene.render.resolution_percentage/100))
        height=max(1,int(scene.render.resolution_y*scene.render.resolution_percentage/100))
        left=max(0,floor(min(p.x for p in projected)*width));right=min(width,ceil(max(p.x for p in projected)*width))
        bottom=max(0,floor(min(p.y for p in projected)*height));top=min(height,ceil(max(p.y for p in projected)*height))
        frame=camera.data.view_frame(scene=scene)
        xmin=min(v.x for v in frame);xmax=max(v.x for v in frame)
        ymin=min(v.y for v in frame);ymax=max(v.y for v in frame);z=frame[0].z
        origin=camera.matrix_world.translation;rotation=camera.matrix_world.to_3x3()
        for y in range(bottom,top):
            for x in range(left,right):
                direction=(rotation @ Vector((xmin+(x+.5)/width*(xmax-xmin),ymin+(y+.5)/height*(ymax-ymin),z))).normalized()
                hit=subject.ray_cast(origin,direction)
                if hit[0] is not None and self.tree.ray_cast(origin,direction,max(0,hit[3]-1e-5))[0] is not None:
                    return False
        return True
