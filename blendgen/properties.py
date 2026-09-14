# =============================================================================
# BlendGen - Scene-level configuration properties
# =============================================================================
# Every user-facing generation parameter lives on a PropertyGroup attached to
# bpy.types.Scene. Values are stored with the .blend file and are the single
# source of truth for the UI, the generation pipeline, and JSON presets.
# =============================================================================

import bpy


def _clamp_pair_max_to_min(min_attr, max_attr):
    """Return an update callback that keeps a max property >= its min partner."""

    def _update(self, _context):
        min_value = getattr(self, min_attr)
        max_value = getattr(self, max_attr)
        if max_value < min_value:
            setattr(self, max_attr, min_value)

    return _update


class BlendGenProperties(bpy.types.PropertyGroup):
    """Complete BlendGen configuration stored on every Scene.

    Pointer-style pickers are intentionally implemented as name strings so that
    presets remain JSON-serializable and survive object remapping across files
    (the UI exposes them with ``prop_search``).
    """

    # ------------------------------------------------------------------
    # Scene references (BO-1, BO-9)
    # ------------------------------------------------------------------
    target_object_name: bpy.props.StringProperty(
        name="Target Object",
        description=(
            "Name of the mesh whose surface receives spawned assets. "
            "Placement uses ray casting against this object"
        ),
        default="",
    )
    asset_collection_name: bpy.props.StringProperty(
        name="Asset Collection",
        description=(
            "Name of the collection containing source meshes to spawn. "
            "Each unique object name becomes an annotation class"
        ),
        default="",
    )
    output_directory: bpy.props.StringProperty(
        name="Output Directory",
        description=(
            "Folder where rendered images and YOLO/COCO annotations are written. "
            "Blender relative paths starting with // are supported"
        ),
        default="//blendgen_dataset/",
        subtype="DIR_PATH",
    )

    # ------------------------------------------------------------------
    # Dataset / batch settings (BO-5, BO-6)
    # ------------------------------------------------------------------
    dataset_format: bpy.props.EnumProperty(
        name="Dataset Format",
        description="Annotation format written alongside rendered images",
        items=(
            ("YOLO", "YOLO", "Write one normalized YOLO .txt label per image"),
            ("COCO", "COCO", "Write a single instances_default.json COCO file"),
            ("BOTH", "Both", "Write YOLO labels and a COCO JSON file"),
        ),
        default="BOTH",
    )
    image_format: bpy.props.EnumProperty(
        name="Image Format",
        description="Still-image file format used by the renderer",
        items=(
            ("PNG", "PNG", "Lossless PNG (recommended for training)"),
            ("JPEG", "JPEG", "Compressed JPEG"),
        ),
        default="PNG",
    )
    num_samples: bpy.props.IntProperty(
        name="Samples",
        description="Number of independently randomized scenes to generate",
        default=50,
        min=1,
        max=100000,
        soft_max=5000,
    )
    instances_per_sample: bpy.props.IntProperty(
        name="Instances per Sample",
        description="How many assets to scatter onto the target surface per sample",
        default=8,
        min=1,
        max=2000,
        soft_max=200,
    )
    camera_count: bpy.props.IntProperty(
        name="Camera Count",
        description=(
            "Number of randomized orbit viewpoints rendered for each sample. "
            "Total images = Samples x Camera Count"
        ),
        default=1,
        min=1,
        max=64,
        soft_max=12,
    )
    random_seed: bpy.props.IntProperty(
        name="Random Seed",
        description="Seed for reproducible runs. 0 uses a non-deterministic seed",
        default=0,
        min=0,
        max=2**31 - 1,
    )

    # ------------------------------------------------------------------
    # Surface-constrained placement (BO-2, BO-3)
    # ------------------------------------------------------------------
    surface_offset: bpy.props.FloatProperty(
        name="Surface Offset",
        description=(
            "Extra world-space offset along the surface normal after the object "
            "origin is snapped to the hit point"
        ),
        default=0.0,
        min=-10.0,
        max=10.0,
        subtype="DISTANCE",
    )
    align_to_normal: bpy.props.BoolProperty(
        name="Align to Surface Normal",
        description="Rotate spawned assets so their local Z axis follows the hit normal",
        default=True,
    )
    lift_by_origin: bpy.props.BoolProperty(
        name="Lift by Bounding Box",
        description=(
            "Raise the object along the surface normal by the distance from its "
            "origin to the local-Z bottom of its bounding box, so centred origins "
            "rest on the surface instead of intersecting it"
        ),
        default=True,
    )
    max_placement_retries: bpy.props.IntProperty(
        name="Placement Retries",
        description=(
            "Maximum ray-cast / collision retries per instance before the instance "
            "is discarded"
        ),
        default=40,
        min=1,
        max=2000,
        soft_max=200,
    )
    min_separation: bpy.props.FloatProperty(
        name="Minimum Separation",
        description=(
            "Extra world-space padding added to AABB overlap tests. 0 still uses "
            "exact BVH mesh overlap"
        ),
        default=0.0,
        min=0.0,
        max=50.0,
        subtype="DISTANCE",
    )

    # ------------------------------------------------------------------
    # Object scale randomization (BO-4)
    # ------------------------------------------------------------------
    scale_min: bpy.props.FloatProperty(
        name="Scale Min",
        description="Lower bound of the uniform scale multiplier applied to spawned assets",
        default=0.8,
        min=0.01,
        max=100.0,
        update=_clamp_pair_max_to_min("scale_min", "scale_max"),
    )
    scale_max: bpy.props.FloatProperty(
        name="Scale Max",
        description="Upper bound of the uniform scale multiplier applied to spawned assets",
        default=1.2,
        min=0.01,
        max=100.0,
    )

    # ------------------------------------------------------------------
    # Rotation limits in degrees (BO-4)
    # Applied in local space after optional normal alignment.
    # X/Y = tilt, Z = twist around the surface normal.
    # ------------------------------------------------------------------
    rot_x_min: bpy.props.FloatProperty(
        name="Rot X Min",
        description="Minimum additional Euler X rotation in degrees (local tilt)",
        default=0.0,
        min=-180.0,
        max=180.0,
        update=_clamp_pair_max_to_min("rot_x_min", "rot_x_max"),
    )
    rot_x_max: bpy.props.FloatProperty(
        name="Rot X Max",
        description="Maximum additional Euler X rotation in degrees (local tilt)",
        default=0.0,
        min=-180.0,
        max=180.0,
    )
    rot_y_min: bpy.props.FloatProperty(
        name="Rot Y Min",
        description="Minimum additional Euler Y rotation in degrees (local tilt)",
        default=0.0,
        min=-180.0,
        max=180.0,
        update=_clamp_pair_max_to_min("rot_y_min", "rot_y_max"),
    )
    rot_y_max: bpy.props.FloatProperty(
        name="Rot Y Max",
        description="Maximum additional Euler Y rotation in degrees (local tilt)",
        default=0.0,
        min=-180.0,
        max=180.0,
    )
    rot_z_min: bpy.props.FloatProperty(
        name="Rot Z Min",
        description="Minimum additional Euler Z rotation in degrees (spin around normal)",
        default=0.0,
        min=-360.0,
        max=360.0,
        update=_clamp_pair_max_to_min("rot_z_min", "rot_z_max"),
    )
    rot_z_max: bpy.props.FloatProperty(
        name="Rot Z Max",
        description="Maximum additional Euler Z rotation in degrees (spin around normal)",
        default=360.0,
        min=-360.0,
        max=360.0,
    )

    # ------------------------------------------------------------------
    # Domain randomization toggles (BO-4)
    # ------------------------------------------------------------------
    randomize_lighting: bpy.props.BoolProperty(
        name="Randomize Lighting",
        description="Randomize sun/point energy, RGB color, position, and world intensity",
        default=True,
    )
    randomize_transforms: bpy.props.BoolProperty(
        name="Randomize Transforms",
        description="Apply random uniform scale and Euler/Quaternion rotation within limits",
        default=True,
    )
    randomize_materials: bpy.props.BoolProperty(
        name="Randomize Materials",
        description="Jitter Principled BSDF base color on spawned instance materials",
        default=True,
    )
    randomize_camera: bpy.props.BoolProperty(
        name="Randomize Camera",
        description="Orbit the camera around the target centroid with random radius, elevation, azimuth, and focal length",
        default=True,
    )

    # ------------------------------------------------------------------
    # Camera orbit (BO-4, multi-camera rendering)
    # Radius values are multipliers of the target world bounding-sphere radius.
    # ------------------------------------------------------------------
    cam_radius_min: bpy.props.FloatProperty(
        name="Radius Min",
        description="Minimum camera distance as a multiple of the target bounding radius",
        default=1.6,
        min=0.05,
        max=100.0,
        update=_clamp_pair_max_to_min("cam_radius_min", "cam_radius_max"),
    )
    cam_radius_max: bpy.props.FloatProperty(
        name="Radius Max",
        description="Maximum camera distance as a multiple of the target bounding radius",
        default=3.2,
        min=0.05,
        max=100.0,
    )
    cam_elevation_min: bpy.props.FloatProperty(
        name="Elevation Min",
        description="Minimum camera elevation angle in degrees above the horizon",
        default=20.0,
        min=-89.0,
        max=89.0,
        update=_clamp_pair_max_to_min("cam_elevation_min", "cam_elevation_max"),
    )
    cam_elevation_max: bpy.props.FloatProperty(
        name="Elevation Max",
        description="Maximum camera elevation angle in degrees above the horizon",
        default=75.0,
        min=-89.0,
        max=89.0,
    )
    cam_azimuth_min: bpy.props.FloatProperty(
        name="Azimuth Min",
        description="Minimum camera azimuth angle in degrees",
        default=0.0,
        min=-360.0,
        max=360.0,
        update=_clamp_pair_max_to_min("cam_azimuth_min", "cam_azimuth_max"),
    )
    cam_azimuth_max: bpy.props.FloatProperty(
        name="Azimuth Max",
        description="Maximum camera azimuth angle in degrees",
        default=360.0,
        min=-360.0,
        max=360.0,
    )
    cam_focal_min: bpy.props.FloatProperty(
        name="Focal Length Min",
        description="Minimum camera focal length in millimetres",
        default=24.0,
        min=1.0,
        max=500.0,
        subtype="DISTANCE",
        update=_clamp_pair_max_to_min("cam_focal_min", "cam_focal_max"),
    )
    cam_focal_max: bpy.props.FloatProperty(
        name="Focal Length Max",
        description="Maximum camera focal length in millimetres",
        default=70.0,
        min=1.0,
        max=500.0,
        subtype="DISTANCE",
    )

    # ------------------------------------------------------------------
    # Lighting randomization ranges (BO-4)
    # ------------------------------------------------------------------
    light_energy_min: bpy.props.FloatProperty(
        name="Light Energy Min",
        description="Minimum randomized energy for SUN and POINT lights",
        default=2.0,
        min=0.0,
        max=100000.0,
        update=_clamp_pair_max_to_min("light_energy_min", "light_energy_max"),
    )
    light_energy_max: bpy.props.FloatProperty(
        name="Light Energy Max",
        description="Maximum randomized energy for SUN and POINT lights",
        default=8.0,
        min=0.0,
        max=100000.0,
    )
    light_color_jitter: bpy.props.FloatProperty(
        name="Light Color Jitter",
        description="Maximum per-channel RGB offset applied to light color (0 disables color jitter)",
        default=0.15,
        min=0.0,
        max=1.0,
    )
    light_position_offset: bpy.props.FloatProperty(
        name="Light Position Offset",
        description=(
            "Maximum positional offset as a multiple of the target bounding radius. "
            "SUN/POINT lights are moved on a hemisphere around the target"
        ),
        default=1.0,
        min=0.0,
        max=20.0,
    )
    world_intensity_min: bpy.props.FloatProperty(
        name="World Intensity Min",
        description="Minimum world background strength (Environment / Background node)",
        default=0.25,
        min=0.0,
        max=100.0,
        update=_clamp_pair_max_to_min("world_intensity_min", "world_intensity_max"),
    )
    world_intensity_max: bpy.props.FloatProperty(
        name="World Intensity Max",
        description="Maximum world background strength (Environment / Background node)",
        default=1.4,
        min=0.0,
        max=100.0,
    )

    # ------------------------------------------------------------------
    # Annotation filtering (BO-5)
    # ------------------------------------------------------------------
    min_visibility: bpy.props.FloatProperty(
        name="Min Visibility",
        description=(
            "Discard an object when the clamped 2D box area divided by the "
            "unclamped box area is below this fraction (object mostly off-frame)"
        ),
        default=0.15,
        min=0.0,
        max=1.0,
    )
    occlusion_threshold: bpy.props.FloatProperty(
        name="Occlusion Threshold",
        description=(
            "Discard an object when fewer than this fraction of camera-to-object "
            "probe rays hit the object itself (heavily occluded)"
        ),
        default=0.30,
        min=0.0,
        max=1.0,
    )
    min_bbox_norm: bpy.props.FloatProperty(
        name="Min Box Size",
        description="Discard annotations whose normalized width or height is smaller than this",
        default=0.002,
        min=0.0,
        max=1.0,
    )

    # ------------------------------------------------------------------
    # Preset name used by the save/load operators (BO-7)
    # ------------------------------------------------------------------
    preset_name: bpy.props.StringProperty(
        name="Preset Name",
        description="File name (without extension) used when saving or loading a JSON preset",
        default="default",
    )

    # ------------------------------------------------------------------
    # Convenience accessors used by the pipeline
    # ------------------------------------------------------------------
    def get_target_object(self):
        """Resolve and return the target mesh object, or None."""
        name = (self.target_object_name or "").strip()
        if not name:
            return None
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            return None
        return obj

    def get_asset_collection(self):
        """Resolve and return the asset collection, or None."""
        name = (self.asset_collection_name or "").strip()
        if not name:
            return None
        return bpy.data.collections.get(name)

    def get_asset_meshes(self):
        """Return mesh objects inside the asset collection, excluding the target."""
        collection = self.get_asset_collection()
        if collection is None:
            return []
        target = self.get_target_object()
        meshes = []
        for obj in collection.all_objects:
            if obj.type != "MESH":
                continue
            if target is not None and obj == target:
                continue
            if not obj.data or not getattr(obj.data, "polygons", None):
                continue
            meshes.append(obj)
        return meshes


def register_properties():
    """Register the PropertyGroup and attach it to Scene as ``scene.blendgen``."""
    bpy.utils.register_class(BlendGenProperties)
    bpy.types.Scene.blendgen = bpy.props.PointerProperty(
        name="BlendGen Settings",
        type=BlendGenProperties,
        description="BlendGen synthetic dataset generation settings",
    )


def unregister_properties():
    """Detach and unregister BlendGen scene properties."""
    if hasattr(bpy.types.Scene, "blendgen"):
        del bpy.types.Scene.blendgen
    bpy.utils.unregister_class(BlendGenProperties)


# Used only for documentation / static analysis; registration is explicit.
CLASSES = (BlendGenProperties,)
