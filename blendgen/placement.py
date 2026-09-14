# =============================================================================
# BlendGen - Surface-constrained object placement (BO-2)
# =============================================================================
# Assets are scattered onto an arbitrary target mesh by:
#   1. Area-weighted sampling of the target's triangles (world space).
#   2. A confirming ray cast along the triangle normal so the origin sits on
#      the real evaluated surface rather than the tessellated sample point.
#   3. Aligning the instance's local Z axis to the hit normal (quaternion).
#   4. Applying uniform scale and limited Euler rotation.
#   5. Rejecting candidates that collide with already-placed instances.
# =============================================================================

import math
import random

import bpy
from mathutils import Euler, Quaternion, Vector

from .collision import CollisionDetector, compose_world_matrix


def world_bounds(obj):
    """Return ``(min_corner, max_corner, center, radius)`` of ``obj`` in world space."""
    matrix = obj.matrix_world
    corners = [matrix @ Vector(corner) for corner in obj.bound_box]
    min_c = Vector((
        min(c.x for c in corners),
        min(c.y for c in corners),
        min(c.z for c in corners),
    ))
    max_c = Vector((
        max(c.x for c in corners),
        max(c.y for c in corners),
        max(c.z for c in corners),
    ))
    center = (min_c + max_c) * 0.5
    radius = (max_c - center).length
    return min_c, max_c, center, max(radius, 1e-6)


def _triangle_area(v0, v1, v2):
    """Return the area of the triangle defined by three world-space vertices."""
    return (v1 - v0).cross(v2 - v0).length * 0.5


def _random_barycentric(rng):
    """Uniform sample inside a triangle using barycentric coordinates."""
    u = rng.random()
    v = rng.random()
    if u + v > 1.0:
        u = 1.0 - u
        v = 1.0 - v
    w = 1.0 - u - v
    return u, v, w


class SurfaceSampler:
    """Area-weighted sampler over the evaluated (or base) triangles of a mesh.

    Works for arbitrary topology: concave meshes, thin leaves, curved terrain.
    Degenerate zero-area faces are skipped so sampling never lands on slivers.
    """

    def __init__(self, target, depsgraph=None):
        self.target = target
        self.triangles = []
        self.cumulative = []
        self.total_area = 0.0
        self._build(depsgraph)

    def _iter_world_triangles(self, depsgraph):
        """Yield ``(v0, v1, v2)`` world-space triangles from the target mesh."""
        obj = self.target
        mesh = None
        eval_obj = None
        try:
            if depsgraph is not None:
                eval_obj = obj.evaluated_get(depsgraph)
                mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
            if mesh is None:
                mesh = obj.data
                eval_obj = None
            matrix = (eval_obj.matrix_world if eval_obj is not None else obj.matrix_world)
            vertices = mesh.vertices
            for poly in mesh.polygons:
                indices = poly.vertices
                if len(indices) < 3:
                    continue
                # Fan-triangulate n-gons around the first vertex.
                origin = matrix @ vertices[indices[0]].co
                prev = matrix @ vertices[indices[1]].co
                for idx in indices[2:]:
                    curr = matrix @ vertices[idx].co
                    yield origin, prev, curr
                    prev = curr
        finally:
            if eval_obj is not None and mesh is not None and mesh != obj.data:
                eval_obj.to_mesh_clear()

    def _build(self, depsgraph):
        """Precompute triangle list and a cumulative area table for sampling."""
        running = 0.0
        for v0, v1, v2 in self._iter_world_triangles(depsgraph):
            area = _triangle_area(v0, v1, v2)
            if area <= 1e-12:
                continue
            normal = (v1 - v0).cross(v2 - v0)
            if normal.length <= 1e-12:
                continue
            normal.normalize()
            running += area
            self.triangles.append((v0, v1, v2, normal, area))
            self.cumulative.append(running)
        self.total_area = running

    def is_valid(self):
        """Return True when the target has at least one sampleable triangle."""
        return self.total_area > 0.0 and bool(self.triangles)

    def sample_point(self, rng):
        """Return ``(point, normal)`` drawn uniformly with respect to surface area."""
        if not self.is_valid():
            return None, None
        choice = rng.random() * self.total_area
        index = _lower_bound(self.cumulative, choice)
        v0, v1, v2, normal, _area = self.triangles[index]
        u, v, w = _random_barycentric(rng)
        point = v0 * w + v1 * u + v2 * v
        return point, normal.copy()


def _lower_bound(values, needle):
    """Binary search returning the first index where ``values[i] >= needle``."""
    lo = 0
    hi = len(values) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if values[mid] < needle:
            lo = mid + 1
        else:
            hi = mid
    return lo


def snap_to_surface(target, point, normal, scene, depsgraph):
    """Ray-cast from just above ``point`` back onto ``target`` to refine the hit.

    Object-space ``Object.ray_cast`` is used first (exact, ignores other meshes).
    Scene-space ``Scene.ray_cast`` is the fallback so modifier-heavy targets still
    produce a hit. Returns ``(location, normal)`` in world space, or
    ``(None, None)`` on a miss.
    """
    if normal.length <= 1e-8:
        return None, None
    unit = normal.normalized()
    # Offset scales with object size so thin meshes and large terrains both work.
    span = max(target.dimensions.length, 1e-3)
    epsilon = max(span * 0.002, 1e-4)
    origin = point + unit * epsilon
    direction = -unit

    hit_loc, hit_nrm = _object_ray_cast(target, origin, direction)
    if hit_loc is None:
        hit_loc, hit_nrm = _scene_ray_cast_target(
            scene, depsgraph, origin, direction, target
        )
    if hit_loc is None:
        # The barycentric sample is still a valid surface point if the ray misses
        # (common on extremely thin leaves). Keep the analytic sample.
        return point.copy(), unit
    return hit_loc, hit_nrm


def _object_ray_cast(obj, origin_world, direction_world):
    """Cast a ray against ``obj`` in object space and return world hit data."""
    try:
        inverse = obj.matrix_world.inverted()
    except ValueError:
        return None, None
    origin_local = inverse @ origin_world
    direction_local = (inverse.to_3x3() @ direction_world)
    if direction_local.length <= 1e-12:
        return None, None
    direction_local.normalize()
    success, location, normal, _index = obj.ray_cast(origin_local, direction_local)
    if not success:
        return None, None
    location_world = obj.matrix_world @ location
    normal_world = obj.matrix_world.to_3x3() @ normal
    if normal_world.length <= 1e-12:
        normal_world = direction_world * -1.0
    normal_world.normalize()
    return location_world, normal_world


def _scene_ray_cast_target(scene, depsgraph, origin, direction, target):
    """Scene ray cast that only accepts hits on ``target`` (or its evaluated original)."""
    if depsgraph is None:
        return None, None
    hit, location, normal, _index, hit_obj, _matrix = scene.ray_cast(
        depsgraph, origin, direction
    )
    if not hit or hit_obj is None:
        return None, None
    original = getattr(hit_obj, "original", hit_obj)
    if hit_obj != target and original != target:
        return None, None
    if normal.length <= 1e-12:
        normal = -direction
    normal.normalize()
    return location.copy(), normal.copy()


def origin_lift_distance(obj, surface_offset, lift_by_origin):
    """Distance to push the origin along the surface normal so the mesh sits on it.

    Object origins are frequently at the bounding-box centre. Using the local-Z
    minimum of ``bound_box`` (scaled) raises the instance so its underside
    touches the surface rather than intersecting it. ``surface_offset`` is then
    added as a user-configurable gap.
    """
    lift = float(surface_offset)
    if lift_by_origin and obj.bound_box:
        z_min = min(corner[2] for corner in obj.bound_box)
        # bound_box is in object space; scale.z maps it to world along local Z
        # after we have aligned local Z with the surface normal.
        lift += max(0.0, -z_min) * abs(obj.scale.z)
    return lift


def build_surface_rotation(normal, rng, settings):
    """Quaternion that aligns local Z to ``normal`` then applies limited Euler jitter.

    The extra Euler rotation is expressed in local space so Z is a twist around
    the surface normal and X/Y are tilts. When transform randomization is
    disabled the extra rotation is identity (optionally still aligned).
    """
    if settings.align_to_normal and normal.length > 1e-8:
        base = normal.normalized().to_track_quat("Z", "Y")
    else:
        base = Quaternion()

    if settings.randomize_transforms:
        rx = math.radians(rng.uniform(settings.rot_x_min, settings.rot_x_max))
        ry = math.radians(rng.uniform(settings.rot_y_min, settings.rot_y_max))
        rz = math.radians(rng.uniform(settings.rot_z_min, settings.rot_z_max))
        extra = Euler((rx, ry, rz), "XYZ").to_quaternion()
        return base @ extra
    return base


def random_uniform_scale(source, rng, settings):
    """Return a world scale vector: source scale times a uniform random factor."""
    if settings.randomize_transforms:
        lo = min(settings.scale_min, settings.scale_max)
        hi = max(settings.scale_min, settings.scale_max)
        factor = rng.uniform(lo, hi)
    else:
        factor = 1.0
    return Vector((
        source.scale.x * factor,
        source.scale.y * factor,
        source.scale.z * factor,
    ))


class PlacementEngine:
    """Scatter collision-free instances of asset meshes onto a target surface."""

    SPAWN_COLLECTION_NAME = "BlendGen_Spawned"

    def __init__(self, context, settings, rng=None):
        self.context = context
        self.scene = context.scene
        self.settings = settings
        self.rng = rng if rng is not None else random.Random()
        self.spawn_collection = None
        self.spawned = []
        self.collision = CollisionDetector(padding=settings.min_separation)
        self.sampler = None
        self._owned_materials = []

    def ensure_spawn_collection(self):
        """Create (or reuse) the dedicated collection that holds spawned instances."""
        coll = bpy.data.collections.get(self.SPAWN_COLLECTION_NAME)
        if coll is None:
            coll = bpy.data.collections.new(self.SPAWN_COLLECTION_NAME)
        linked = False
        scene_root = self.scene.collection
        if coll == scene_root:
            linked = True
        elif coll.name in scene_root.children:
            linked = True
        else:
            nested = []
            try:
                nested = list(scene_root.children_recursive)
            except AttributeError:
                nested = [child for child in scene_root.children]
            for child in nested:
                if child == coll:
                    linked = True
                    break
        if not linked:
            scene_root.children.link(coll)
        self.spawn_collection = coll
        return coll

    def scatter(self, target, assets, count, depsgraph):
        """Place up to ``count`` non-overlapping instances on ``target``.

        Returns the list of spawned objects that were successfully committed.
        Instances that cannot be placed after ``max_placement_retries`` are
        discarded so the dataset never contains intersecting geometry.
        """
        self.ensure_spawn_collection()
        self.sampler = SurfaceSampler(target, depsgraph)
        if not self.sampler.is_valid():
            raise RuntimeError(
                "BlendGen: target mesh '%s' has no sampleable surface area."
                % target.name
            )
        if not assets:
            raise RuntimeError("BlendGen: no mesh assets available to spawn.")

        placed = []
        retries = max(1, int(self.settings.max_placement_retries))
        for _index in range(count):
            source = self.rng.choice(assets)
            instance = self._new_instance(source)
            accepted = False
            for _attempt in range(retries):
                if self._try_place(instance, target, placed, depsgraph):
                    accepted = True
                    break
            if accepted:
                placed.append(instance)
                self.spawned.append(instance)
                # Refresh depsgraph so the committed BVH matches the final matrix.
                depsgraph = self._refresh_depsgraph()
                self.collision.remember(instance, depsgraph)
            else:
                self._delete_object(instance)
        self.spawned = list(placed)
        return placed

    def clear(self):
        """Delete every spawned instance and drop collision caches."""
        for obj in list(self.spawned):
            self._delete_object(obj)
        self.spawned = []
        self.collision.clear()
        self._purge_owned_materials()
        if self.spawn_collection is not None:
            for obj in list(self.spawn_collection.objects):
                self._delete_object(obj)

    def _try_place(self, instance, target, placed, depsgraph):
        """Sample a surface pose, apply it, and accept it only if collision-free."""
        point, normal = self.sampler.sample_point(self.rng)
        if point is None or normal is None:
            return False
        hit, hit_normal = snap_to_surface(
            target, point, normal, self.scene, depsgraph
        )
        if hit is None or hit_normal is None:
            return False

        rotation = build_surface_rotation(hit_normal, self.rng, self.settings)
        scale = random_uniform_scale(instance, self.rng, self.settings)

        # Temporary scale is required so origin lift uses the randomized size.
        instance.scale = scale
        lift = origin_lift_distance(
            instance,
            self.settings.surface_offset,
            self.settings.lift_by_origin,
        )
        location = hit + hit_normal.normalized() * lift
        matrix = compose_world_matrix(location, rotation, scale)
        instance.rotation_mode = "QUATERNION"
        instance.matrix_world = matrix

        depsgraph = self._refresh_depsgraph()
        if self.collision.collides(instance, placed, depsgraph):
            return False
        return True

    def _new_instance(self, source):
        """Linked duplicate that shares mesh data but owns its own transform."""
        instance = source.copy()
        instance.data = source.data
        instance.animation_data_clear()
        instance.name = "%s_bg" % source.name
        instance["blendgen_source_name"] = source.name
        instance.hide_render = False
        instance.hide_viewport = False
        instance.hide_set(False)
        self.spawn_collection.objects.link(instance)
        self._object_link_material_copies(instance)
        return instance

    def _object_link_material_copies(self, obj):
        """Give ``obj`` private material copies so color jitter cannot mutate assets."""
        if not obj.material_slots:
            return
        for slot in obj.material_slots:
            # Capture the data-block material *before* switching the slot to
            # OBJECT linkage, which otherwise starts empty and would skip copies.
            material = slot.material
            slot.link = "OBJECT"
            if material is None:
                continue
            clone = material.copy()
            clone.name = "%s_bg" % material.name
            orig = None
            if clone.use_nodes and clone.node_tree is not None:
                for node in clone.node_tree.nodes:
                    if node.type == "BSDF_PRINCIPLED" and "Base Color" in node.inputs:
                        orig = list(node.inputs["Base Color"].default_value)
                        break
            if orig is not None:
                clone["blendgen_orig_color"] = orig
            slot.material = clone
            self._owned_materials.append(clone)

    def _refresh_depsgraph(self):
        """Force evaluated transforms to match ``matrix_world`` before BVH queries."""
        self.context.view_layer.update()
        return self.context.evaluated_depsgraph_get()

    def _delete_object(self, obj):
        """Unlink and remove a spawned object. Shared mesh data is left intact."""
        if obj is None:
            return
        self.collision.forget(obj)
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except ReferenceError:
            pass

    def _purge_owned_materials(self):
        """Remove material copies that are no longer used by any object."""
        for material in self._owned_materials:
            try:
                if material is not None and material.users == 0:
                    bpy.data.materials.remove(material)
            except (ReferenceError, RuntimeError):
                pass
        self._owned_materials = []


