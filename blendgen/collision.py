# =============================================================================
# BlendGen - BVH collision detection and overlap avoidance (BO-3)
# =============================================================================
# Incoming instances are tested against already-placed objects using:
#   1. A cheap world-space AABB reject.
#   2. A precise BVH overlap test built with BVHTree.FromObject.
# The caller must apply the candidate world matrix and update the view layer
# before calling CollisionDetector.collides(), because FromObject reads the
# evaluated (depsgraph) mesh in world space.
# =============================================================================

from mathutils import Vector
from mathutils.bvhtree import BVHTree


def world_aabb(obj, padding=0.0):
    """Return ``(min_corner, max_corner)`` of ``obj`` in world space.

    ``obj.bound_box`` is in object space; multiplying by ``matrix_world``
    yields an oriented box whose AABB is the conservative envelope used for
    the broad-phase overlap test.
    """
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
    if padding:
        pad = Vector((padding, padding, padding))
        min_c = min_c - pad
        max_c = max_c + pad
    return min_c, max_c


def aabb_overlap(a, b):
    """Return True when two world-space AABBs overlap (inclusive)."""
    min_a, max_a = a
    min_b, max_b = b
    return (
        min_a.x <= max_b.x
        and max_a.x >= min_b.x
        and min_a.y <= max_b.y
        and max_a.y >= min_b.y
        and min_a.z <= max_b.z
        and max_a.z >= min_b.z
    )


def compose_world_matrix(location, rotation_quat, scale):
    """Build a 4x4 world matrix from location, quaternion, and scale.

    Uses ``Matrix.LocRotScale`` on Blender 3.2+ / 4.x and falls back to an
    explicit TRS product for older interpreters so the addon stays portable.
    """
    from mathutils import Matrix

    if hasattr(Matrix, "LocRotScale"):
        return Matrix.LocRotScale(location, rotation_quat, scale)

    translation = Matrix.Translation(location)
    rotation = rotation_quat.to_matrix().to_4x4()
    sx, sy, sz = _as_xyz(scale)
    scale_mat = Matrix.Diagonal((sx, sy, sz, 1.0))
    return translation @ rotation @ scale_mat


def _as_xyz(scale):
    """Normalize a scale value to an ``(x, y, z)`` tuple."""
    if hasattr(scale, "x"):
        return scale.x, scale.y, scale.z
    if isinstance(scale, (int, float)):
        return float(scale), float(scale), float(scale)
    return float(scale[0]), float(scale[1]), float(scale[2])


def bvh_from_object(obj, depsgraph, epsilon=1e-6):
    """Build a world-space BVH tree for ``obj`` using ``BVHTree.FromObject``.

    ``FromObject`` consumes the evaluated mesh (modifiers applied) and the
    object's current world matrix. Returns None when the object cannot produce
    a valid mesh BVH (empty geometry, non-mesh data, etc.).
    """
    if obj is None or obj.type != "MESH":
        return None
    try:
        tree = BVHTree.FromObject(obj, depsgraph, epsilon=epsilon)
    except (TypeError, ValueError, RuntimeError):
        tree = _bvh_from_polygons(obj)
    if tree is None:
        return None
    # An empty tree can still be constructed for degenerate meshes.
    return tree


def _bvh_from_polygons(obj):
    """Fallback BVH construction from the base mesh and current world matrix."""
    mesh = obj.data
    if mesh is None or len(mesh.vertices) == 0 or len(mesh.polygons) == 0:
        return None
    matrix = obj.matrix_world
    vertices = [matrix @ vert.co.copy() for vert in mesh.vertices]
    polygons = [tuple(poly.vertices) for poly in mesh.polygons]
    if not polygons:
        return None
    return BVHTree.FromPolygons(vertices, polygons)


class CollisionDetector:
    """Stateful overlap tester with optional BVH caching for committed objects.

    Candidate objects (still being placed) are *not* cached because their
    transform changes on every retry. Committed objects are cached after the
    first successful query so subsequent placements do not rebuild their trees.
    """

    def __init__(self, padding=0.0, epsilon=1e-6):
        self.padding = float(padding)
        self.epsilon = float(epsilon)
        self._committed_bvh = {}
        self._committed_aabb = {}

    def clear(self):
        """Drop all cached trees. Call this when spawned objects are deleted."""
        self._committed_bvh.clear()
        self._committed_aabb.clear()

    def remember(self, obj, depsgraph):
        """Cache BVH/AABB for an object that has been accepted into the scene."""
        if obj is None:
            return
        self._committed_aabb[obj.name] = world_aabb(obj, self.padding)
        tree = bvh_from_object(obj, depsgraph, epsilon=self.epsilon)
        if tree is not None:
            self._committed_bvh[obj.name] = tree

    def forget(self, obj):
        """Remove a previously committed object from the cache."""
        if obj is None:
            return
        self._committed_bvh.pop(obj.name, None)
        self._committed_aabb.pop(obj.name, None)

    def collides(self, candidate, others, depsgraph):
        """Return True if ``candidate`` overlaps any object in ``others``.

        Broad-phase AABB tests avoid BVH construction when objects are clearly
        separated. Narrow-phase uses ``BVHTree.overlap``.
        """
        if candidate is None or not others:
            return False

        candidate_aabb = world_aabb(candidate, self.padding)
        candidate_bvh = None

        for other in others:
            if other is None or other == candidate:
                continue
            other_aabb = self._committed_aabb.get(other.name)
            if other_aabb is None:
                other_aabb = world_aabb(other, self.padding)
            if not aabb_overlap(candidate_aabb, other_aabb):
                continue

            if candidate_bvh is None:
                candidate_bvh = bvh_from_object(
                    candidate, depsgraph, epsilon=self.epsilon
                )
                if candidate_bvh is None:
                    # Without a mesh BVH we cannot prove overlap; treat AABB
                    # intersection as a collision so we never accept a guess.
                    return True

            other_bvh = self._committed_bvh.get(other.name)
            if other_bvh is None:
                other_bvh = bvh_from_object(other, depsgraph, epsilon=self.epsilon)
                if other_bvh is None:
                    return True

            overlaps = candidate_bvh.overlap(other_bvh)
            if overlaps:
                return True

        return False
