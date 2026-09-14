# =============================================================================
# BlendGen - Domain randomization (BO-4)
# =============================================================================
# Before every render the following scene attributes are procedurally jittered:
#   * Lighting  - SUN/POINT energy, RGB color, position offset, world intensity
#   * Camera    - spherical orbit around the target centroid + focal length
#   * Materials - Principled BSDF base-color adjustments on spawned instances
#   * Transforms- additional in-plane spin that keeps origins on the surface
# Every randomization call snapshots the original state so the scene can be
# restored after the frame is written (or on abort).
# =============================================================================

import math

import bpy
from mathutils import Quaternion, Vector

from .placement import world_bounds


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _jitter_color(rgb, amount, rng):
    """Return an RGB triple jittered by ``amount`` and clamped to [0, 1]."""
    if amount <= 0.0:
        return tuple(rgb)
    return tuple(
        _clamp(channel + rng.uniform(-amount, amount), 0.0, 1.0)
        for channel in rgb
    )


def _find_world_background(world):
    """Return the first Background or Environment node in ``world``'s node tree."""
    if world is None:
        return None
    if not world.use_nodes or world.node_tree is None:
        return None
    for node in world.node_tree.nodes:
        if node.type in {"BACKGROUND", "BACKGROUND_SHADER"}:
            return node
    for node in world.node_tree.nodes:
        if "Strength" in node.inputs or "Color" in node.inputs:
            if node.type in {"BACKGROUND", "EMISSION"}:
                return node
    return world.node_tree.nodes.get("Background")


def _principled_nodes(material):
    """Yield Principled BSDF nodes from a material's node tree."""
    if material is None or not material.use_nodes or material.node_tree is None:
        return
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            yield node


class DomainRandomizer:
    """Apply and restore per-frame lighting, camera, material, and pose jitter."""

    CAMERA_NAME = "BlendGen_Camera"
    SUN_NAME = "BlendGen_Sun"
    POINT_NAME = "BlendGen_Point"

    def __init__(self, context, settings, rng):
        self.context = context
        self.scene = context.scene
        self.settings = settings
        self.rng = rng

        self.camera = None
        self.lights = []
        self.created_objects = []

        self._saved_camera_matrix = None
        self._saved_camera_lens = None
        self._saved_scene_camera = None
        self._saved_light_states = []
        self._saved_world = None
        self._created_world = False
        self._owned_world = None

    # ------------------------------------------------------------------
    # Setup / teardown of camera and lights that BlendGen owns
    # ------------------------------------------------------------------
    def setup(self, target):
        """Ensure a camera and at least one SUN + POINT light exist."""
        self._saved_scene_camera = self.scene.camera
        self.camera = self._ensure_camera()
        self.scene.camera = self.camera
        self._saved_camera_matrix = self.camera.matrix_world.copy()
        self._saved_camera_lens = getattr(self.camera.data, "lens", None)
        self.lights = self._collect_or_create_lights(target)
        self._snapshot_lights()
        self._ensure_world()
        # A camera we just created sits at the world origin; frame the target
        # immediately so the first render is never a blank shot.
        if self.camera in self.created_objects and not self.settings.randomize_camera:
            self._randomize_camera(target)

    def restore_persistent(self):
        """Restore camera/lights/world created or mutated for the whole run."""
        self.restore_frame()
        if self._saved_scene_camera is not None:
            self.scene.camera = self._saved_scene_camera
        elif self.camera is not None:
            self.scene.camera = self.camera

        if self.camera is not None and self._saved_camera_matrix is not None:
            self.camera.matrix_world = self._saved_camera_matrix
        if self.camera is not None and self._saved_camera_lens is not None:
            self.camera.data.lens = self._saved_camera_lens

        self._restore_lights()
        self._restore_world()
        self._delete_created_objects()

    def restore_frame(self):
        """No-op hook kept for symmetry; per-frame state is re-applied each step."""
        return

    # ------------------------------------------------------------------
    # Per-render randomization entry point
    # ------------------------------------------------------------------
    def randomize_frame(self, target, spawned):
        """Randomize every enabled domain for a single render."""
        if self.settings.randomize_lighting:
            self._randomize_lighting(target)
            self._randomize_world()
        if self.settings.randomize_camera:
            self._randomize_camera(target)
        if self.settings.randomize_materials:
            self._randomize_materials(spawned)
        if self.settings.randomize_transforms:
            self._spin_instances(spawned)

    # ------------------------------------------------------------------
    # Camera orbit
    # ------------------------------------------------------------------
    def _randomize_camera(self, target):
        """Place the camera on a spherical shell around the target centroid."""
        _min_c, _max_c, center, radius = world_bounds(target)
        lo = min(self.settings.cam_radius_min, self.settings.cam_radius_max)
        hi = max(self.settings.cam_radius_min, self.settings.cam_radius_max)
        distance = self.rng.uniform(lo, hi) * radius

        elev_lo = math.radians(min(self.settings.cam_elevation_min, self.settings.cam_elevation_max))
        elev_hi = math.radians(max(self.settings.cam_elevation_min, self.settings.cam_elevation_max))
        az_lo = math.radians(min(self.settings.cam_azimuth_min, self.settings.cam_azimuth_max))
        az_hi = math.radians(max(self.settings.cam_azimuth_min, self.settings.cam_azimuth_max))
        elevation = self.rng.uniform(elev_lo, elev_hi)
        azimuth = self.rng.uniform(az_lo, az_hi)

        x = distance * math.cos(elevation) * math.cos(azimuth)
        y = distance * math.cos(elevation) * math.sin(azimuth)
        z = distance * math.sin(elevation)
        location = center + Vector((x, y, z))

        # Camera looks along local -Z; track_quat('Z', 'Y') aims +Z at the
        # vector (camera - center), which is equivalent to aiming -Z at center.
        direction = location - center
        if direction.length <= 1e-8:
            direction = Vector((0.0, 0.0, 1.0))
        rotation = direction.normalized().to_track_quat("Z", "Y")

        self.camera.location = location
        self.camera.rotation_mode = "QUATERNION"
        self.camera.rotation_quaternion = rotation

        focal_lo = min(self.settings.cam_focal_min, self.settings.cam_focal_max)
        focal_hi = max(self.settings.cam_focal_min, self.settings.cam_focal_max)
        self.camera.data.lens = self.rng.uniform(focal_lo, focal_hi)

    # ------------------------------------------------------------------
    # Lighting
    # ------------------------------------------------------------------
    def _randomize_lighting(self, target):
        """Jitter energy, RGB color, and position of SUN and POINT lights."""
        _min_c, _max_c, center, radius = world_bounds(target)
        energy_lo = min(self.settings.light_energy_min, self.settings.light_energy_max)
        energy_hi = max(self.settings.light_energy_min, self.settings.light_energy_max)
        jitter = self.settings.light_color_jitter
        offset_scale = self.settings.light_position_offset * radius

        for light in self.lights:
            data = light.data
            if hasattr(data, "energy"):
                data.energy = self.rng.uniform(energy_lo, energy_hi)
            if hasattr(data, "color"):
                data.color = _jitter_color(tuple(data.color), jitter, self.rng)

            if offset_scale <= 0.0:
                continue
            # SUN: hemisphere around the target. POINT: spherical offset.
            if data.type == "SUN":
                azimuth = self.rng.uniform(0.0, 2.0 * math.pi)
                elevation = self.rng.uniform(math.radians(25.0), math.radians(85.0))
                dist = radius * self.rng.uniform(1.5, 1.5 + max(offset_scale, 0.1) / max(radius, 1e-6) + 1.5)
                location = center + Vector((
                    dist * math.cos(elevation) * math.cos(azimuth),
                    dist * math.cos(elevation) * math.sin(azimuth),
                    dist * math.sin(elevation),
                ))
                light.location = location
                direction = location - center
                if direction.length > 1e-8:
                    light.rotation_mode = "QUATERNION"
                    light.rotation_quaternion = direction.normalized().to_track_quat("Z", "Y")
            else:
                offset = Vector((
                    self.rng.uniform(-offset_scale, offset_scale),
                    self.rng.uniform(-offset_scale, offset_scale),
                    self.rng.uniform(0.0, offset_scale),
                ))
                # Re-apply from the snapshotted base location when available.
                base = None
                for saved in self._saved_light_states:
                    if saved["name"] == light.name:
                        base = saved["location"]
                        break
                origin = Vector(base) if base is not None else light.location.copy()
                light.location = origin + offset

    def _randomize_world(self):
        """Randomize world background / environment intensity."""
        node = _find_world_background(self.scene.world)
        if node is None:
            return
        strength = node.inputs.get("Strength")
        if strength is None:
            return
        lo = min(self.settings.world_intensity_min, self.settings.world_intensity_max)
        hi = max(self.settings.world_intensity_min, self.settings.world_intensity_max)
        strength.default_value = self.rng.uniform(lo, hi)

    # ------------------------------------------------------------------
    # Materials
    # ------------------------------------------------------------------
    def _randomize_materials(self, spawned):
        """Adjust Principled BSDF base color on each spawned instance's copies."""
        for obj in spawned:
            for slot in obj.material_slots:
                material = slot.material
                if material is None:
                    continue
                for node in _principled_nodes(material):
                    base = node.inputs.get("Base Color")
                    if base is None:
                        continue
                    stored = material.get("blendgen_orig_color")
                    if stored is not None:
                        current = tuple(stored)
                    else:
                        current = tuple(base.default_value)
                    jittered = _jitter_color(current[:3], 0.22, self.rng)
                    alpha = current[3] if len(current) > 3 else 1.0
                    base.default_value = (jittered[0], jittered[1], jittered[2], alpha)

    # ------------------------------------------------------------------
    # Extra in-plane spin (keeps the origin on the surface)
    # ------------------------------------------------------------------
    def _spin_instances(self, spawned):
        """Apply an extra local-Z twist within the configured rotation limits."""
        if self.settings.rot_z_max == self.settings.rot_z_min:
            return
        for obj in spawned:
            obj.rotation_mode = "QUATERNION"
            extra_deg = self.rng.uniform(self.settings.rot_z_min, self.settings.rot_z_max)
            spin = Quaternion(Vector((0.0, 0.0, 1.0)), math.radians(extra_deg * 0.05))
            # A small additional twist only: the main rotation was already
            # sampled at placement time. This keeps objects on the surface
            # while still varying appearance across camera viewpoints.
            obj.rotation_quaternion = obj.rotation_quaternion @ spin

    # ------------------------------------------------------------------
    # Ensure / snapshot helpers
    # ------------------------------------------------------------------
    def _ensure_camera(self):
        """Reuse the scene camera when present, otherwise create BlendGen_Camera."""
        camera = self.scene.camera
        if camera is not None and camera.type == "CAMERA":
            return camera
        camera = bpy.data.objects.get(self.CAMERA_NAME)
        if camera is not None and camera.type == "CAMERA":
            return camera
        data = bpy.data.cameras.new(self.CAMERA_NAME)
        camera = bpy.data.objects.new(self.CAMERA_NAME, data)
        self.scene.collection.objects.link(camera)
        self.created_objects.append(camera)
        return camera

    def _collect_or_create_lights(self, target):
        """Return existing lights, creating a SUN and a POINT if the scene has none."""
        lights = [obj for obj in self.scene.objects if obj.type == "LIGHT"]
        has_sun = any(obj.data.type == "SUN" for obj in lights)
        has_point = any(obj.data.type == "POINT" for obj in lights)
        _min_c, _max_c, center, radius = world_bounds(target)

        if not has_sun:
            data = bpy.data.lights.new(self.SUN_NAME, type="SUN")
            data.energy = self.settings.light_energy_max
            sun = bpy.data.objects.new(self.SUN_NAME, data)
            sun.location = center + Vector((0.0, 0.0, radius * 3.0))
            self.scene.collection.objects.link(sun)
            self.created_objects.append(sun)
            lights.append(sun)
        if not has_point:
            data = bpy.data.lights.new(self.POINT_NAME, type="POINT")
            data.energy = self.settings.light_energy_max
            point = bpy.data.objects.new(self.POINT_NAME, data)
            point.location = center + Vector((radius, radius, radius * 2.0))
            self.scene.collection.objects.link(point)
            self.created_objects.append(point)
            lights.append(point)
        return lights

    def _snapshot_lights(self):
        """Record original light energy, color, and transform for restoration."""
        self._saved_light_states = []
        for light in self.lights:
            self._saved_light_states.append({
                "name": light.name,
                "energy": getattr(light.data, "energy", None),
                "color": tuple(light.data.color) if hasattr(light.data, "color") else None,
                "location": light.location.copy(),
                "matrix": light.matrix_world.copy(),
                "rotation_mode": light.rotation_mode,
            })

    def _restore_lights(self):
        """Write snapshotted light attributes back onto the live objects."""
        lookup = {light.name: light for light in self.lights}
        for saved in self._saved_light_states:
            light = lookup.get(saved["name"])
            if light is None:
                continue
            if saved["energy"] is not None and hasattr(light.data, "energy"):
                light.data.energy = saved["energy"]
            if saved["color"] is not None and hasattr(light.data, "color"):
                light.data.color = saved["color"]
            light.matrix_world = saved["matrix"]
            light.rotation_mode = saved["rotation_mode"]

    def _ensure_world(self):
        """Guarantee a node-based world exists and snapshot its strength."""
        world = self.scene.world
        if world is None:
            world = bpy.data.worlds.new("BlendGenWorld")
            world.use_nodes = True
            self.scene.world = world
            self._created_world = True
            self._owned_world = world
        if not world.use_nodes:
            world.use_nodes = True
        node = _find_world_background(world)
        strength = None
        color = None
        if node is not None:
            if "Strength" in node.inputs:
                strength = node.inputs["Strength"].default_value
            if "Color" in node.inputs:
                color = tuple(node.inputs["Color"].default_value)
        self._saved_world = {"strength": strength, "color": color}

    def _restore_world(self):
        """Restore world background intensity/color, removing a world we created."""
        if self._saved_world is not None:
            node = _find_world_background(self.scene.world)
            if node is not None:
                if self._saved_world["strength"] is not None and "Strength" in node.inputs:
                    node.inputs["Strength"].default_value = self._saved_world["strength"]
                if self._saved_world["color"] is not None and "Color" in node.inputs:
                    node.inputs["Color"].default_value = self._saved_world["color"]
        if self._created_world and self._owned_world is not None:
            try:
                if self.scene.world == self._owned_world:
                    self.scene.world = None
                bpy.data.worlds.remove(self._owned_world)
            except (ReferenceError, RuntimeError):
                pass
            self._owned_world = None
            self._created_world = False

    def _delete_created_objects(self):
        """Remove camera/lights that BlendGen inserted into an empty scene."""
        for obj in list(self.created_objects):
            data = getattr(obj, "data", None)
            obj_type = getattr(obj, "type", "")
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
            if data is not None and getattr(data, "users", 1) == 0:
                try:
                    if obj_type == "CAMERA":
                        bpy.data.cameras.remove(data)
                    elif obj_type == "LIGHT":
                        bpy.data.lights.remove(data)
                except (ReferenceError, RuntimeError, AttributeError):
                    pass
        self.created_objects = []
