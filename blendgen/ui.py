# =============================================================================
# BlendGen - 3D Viewport sidebar UI and operators (BO-1, BO-6, BO-7, BO-9)
# =============================================================================
# The "BlendGen" tab lives in View3D > Sidebar (N). Nested panels group scene
# setup, dataset, placement, randomization, and presets. Operators implement
# dataset generation (modal + wm.progress_*), placement preview, and JSON
# preset save/load against Blender's user preset directory.
# =============================================================================

import bpy

from .exporter import (
    BlendGenPipeline,
    is_cancel_requested,
    preview_placement,
    request_cancel,
    validate_settings,
)
from .preset import PresetManager, list_presets, sanitize_preset_name


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------
class BLENDGEN_OT_generate_dataset(bpy.types.Operator):
    """Generate a synthetic object-detection dataset with progress reporting."""

    bl_idname = "blendgen.generate_dataset"
    bl_label = "Generate Dataset"
    bl_description = (
        "Scatter assets, randomize the domain, render each viewpoint, and "
        "export YOLO/COCO annotations"
    )
    bl_options = {"REGISTER"}

    _timer = None
    pipeline = None

    def invoke(self, context, event):
        """Start a modal generation loop so ESC can cancel and the UI can redraw."""
        error = validate_settings(context, require_output=True)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        self.pipeline = BlendGenPipeline(context)
        try:
            total = self.pipeline.setup()
        except Exception as exc:
            try:
                self.pipeline.cleanup()
            except Exception:
                pass
            self.report({"ERROR"}, "BlendGen: setup failed – %s" % exc)
            return {"CANCELLED"}

        window_manager = context.window_manager
        window_manager.progress_begin(0, max(int(total), 1))
        self._timer = window_manager.event_timer_add(0.01, window=context.window)
        window_manager.modal_handler_add(self)
        self.report({"INFO"}, "BlendGen: generating %d images..." % total)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        """Advance one image on TIMER; honour ESC and the Stop operator flag."""
        if event.type == "ESC" and event.value == "PRESS":
            request_cancel()
            self._shutdown(context, cancelled=True)
            self.report({"WARNING"}, "BlendGen: generation cancelled.")
            return {"CANCELLED"}

        if event.type == "TIMER":
            if is_cancel_requested():
                self._shutdown(context, cancelled=True)
                self.report({"WARNING"}, "BlendGen: generation stopped.")
                return {"CANCELLED"}
            try:
                more = self.pipeline.step()
            except Exception as exc:
                self._shutdown(context, cancelled=True)
                self.report({"ERROR"}, "BlendGen: generation failed – %s" % exc)
                return {"CANCELLED"}

            context.window_manager.progress_update(self.pipeline.completed)
            if not more:
                produced = self.pipeline.produced
                out_dir = self.pipeline.out_dir
                cancelled = is_cancel_requested()
                self._shutdown(context, cancelled=cancelled)
                if cancelled:
                    self.report(
                        {"WARNING"},
                        "BlendGen: stopped after %d images in %s" % (produced, out_dir),
                    )
                    return {"CANCELLED"}
                self.report(
                    {"INFO"},
                    "BlendGen: finished. %d images written to %s" % (produced, out_dir),
                )
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def execute(self, context):
        """Blocking path used by scripts and ``bpy.ops`` without INVOKE_DEFAULT."""
        error = validate_settings(context, require_output=True)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        pipeline = BlendGenPipeline(context)
        window_manager = context.window_manager
        try:
            total = pipeline.setup()
            window_manager.progress_begin(0, max(int(total), 1))
            while pipeline.step():
                window_manager.progress_update(pipeline.completed)
            pipeline.finalize()
        except Exception as exc:
            try:
                pipeline.cleanup()
            except Exception:
                pass
            window_manager.progress_end()
            self.report({"ERROR"}, "BlendGen: generation failed – %s" % exc)
            return {"CANCELLED"}

        produced = pipeline.produced
        out_dir = pipeline.out_dir
        pipeline.cleanup()
        window_manager.progress_end()
        self.report(
            {"INFO"},
            "BlendGen: finished. %d images written to %s" % (produced, out_dir),
        )
        return {"FINISHED"}

    def _shutdown(self, context, cancelled):
        """Write whatever annotations were produced, restore the scene, end progress."""
        pipeline = self.pipeline
        if pipeline is not None:
            try:
                pipeline.finalize()
            except Exception:
                pass
            try:
                pipeline.cleanup()
            except Exception:
                pass
        window_manager = context.window_manager
        if self._timer is not None:
            try:
                window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        try:
            window_manager.progress_end()
        except Exception:
            pass
        self.pipeline = None


class BLENDGEN_OT_stop_generation(bpy.types.Operator):
    """Request cancellation of a running BlendGen generation loop."""

    bl_idname = "blendgen.stop_generation"
    bl_label = "Stop Generation"
    bl_description = "Stop the current BlendGen dataset generation after the current image"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        request_cancel()
        self.report({"INFO"}, "BlendGen: stop requested.")
        return {"FINISHED"}


class BLENDGEN_OT_preview_placement(bpy.types.Operator):
    """Scatter assets onto the target surface without rendering."""

    bl_idname = "blendgen.preview_placement"
    bl_label = "Preview Placement"
    bl_description = (
        "Place a single batch of assets on the target surface so you can inspect "
        "alignment and collisions in the viewport"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            placed = preview_placement(context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "BlendGen: preview placed %d instance(s)." % len(placed))
        return {"FINISHED"}


class BLENDGEN_OT_save_preset(bpy.types.Operator):
    """Serialize every BlendGen UI property to a JSON file in the preset directory."""

    bl_idname = "blendgen.save_preset"
    bl_label = "Save Preset"
    bl_description = "Save the current BlendGen settings as a reusable JSON preset"
    bl_options = {"REGISTER"}

    preset_name: bpy.props.StringProperty(
        name="Preset Name",
        description="File name written under Blender's presets/blendgen directory",
        default="default",
    )

    def invoke(self, context, event):
        settings = context.scene.blendgen
        if settings.preset_name:
            self.preset_name = settings.preset_name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = sanitize_preset_name(self.preset_name)
        context.scene.blendgen.preset_name = name
        try:
            path = PresetManager().save(name, context)
        except Exception as exc:
            self.report({"ERROR"}, "BlendGen: could not save preset – %s" % exc)
            return {"CANCELLED"}
        self.report({"INFO"}, "BlendGen: saved preset '%s' to %s" % (name, path))
        return {"FINISHED"}


def _preset_enum_items(self, context):
    """Build an EnumProperty item list from JSON files in the preset directory."""
    names = list_presets()
    if not names:
        return [("NONE", "(no presets saved)", "Use Save Preset first", 0)]
    return [
        (name, name, "Load preset '%s'" % name, index)
        for index, name in enumerate(names)
    ]


class BLENDGEN_OT_load_preset(bpy.types.Operator):
    """Deserialize a JSON preset from Blender's preset directory onto the Scene."""

    bl_idname = "blendgen.load_preset"
    bl_label = "Load Preset"
    bl_description = "Load a previously saved BlendGen JSON preset"
    bl_options = {"REGISTER"}

    preset_name: bpy.props.EnumProperty(
        name="Preset",
        description="Preset file to load from Blender's presets/blendgen directory",
        items=_preset_enum_items,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = self.preset_name
        if not name or name == "NONE":
            self.report({"ERROR"}, "BlendGen: no preset available to load.")
            return {"CANCELLED"}
        try:
            path = PresetManager().load(name, context)
        except Exception as exc:
            self.report({"ERROR"}, "BlendGen: could not load preset – %s" % exc)
            return {"CANCELLED"}
        context.scene.blendgen.preset_name = name
        self.report({"INFO"}, "BlendGen: loaded preset '%s' from %s" % (name, path))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panels – View3D > Sidebar > BlendGen
# ---------------------------------------------------------------------------
class BLENDGEN_PT_main(bpy.types.Panel):
    """Root panel that hosts the generate / preview / stop actions."""

    bl_label = "BlendGen"
    bl_idname = "BLENDGEN_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendGen"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Synthetic Dataset Generator", icon="RENDER_STILL")
        row = layout.row()
        row.scale_y = 1.7
        row.operator("blendgen.generate_dataset", icon="RENDER_STILL")
        split = layout.split(factor=0.5, align=True)
        split.operator("blendgen.preview_placement", icon="OBJECT_HIDDEN")
        split.operator("blendgen.stop_generation", icon="CANCEL")


class BLENDGEN_PT_scene(bpy.types.Panel):
    """Target mesh, asset collection, and output path."""

    bl_label = "Scene Setup"
    bl_idname = "BLENDGEN_PT_scene"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendGen"
    bl_parent_id = "BLENDGEN_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blendgen
        col = layout.column(align=True)
        col.prop_search(
            settings, "target_object_name", bpy.data, "objects", text="Target Object"
        )
        col.prop_search(
            settings,
            "asset_collection_name",
            bpy.data,
            "collections",
            text="Asset Collection",
        )
        col.separator()
        col.prop(settings, "output_directory")


class BLENDGEN_PT_dataset(bpy.types.Panel):
    """Batch size, format, and multi-camera settings."""

    bl_label = "Dataset"
    bl_idname = "BLENDGEN_PT_dataset"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendGen"
    bl_parent_id = "BLENDGEN_PT_main"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blendgen
        col = layout.column(align=True)
        col.prop(settings, "dataset_format")
        col.prop(settings, "image_format")
        col.separator()
        col.prop(settings, "num_samples")
        col.prop(settings, "instances_per_sample")
        col.prop(settings, "camera_count")
        col.prop(settings, "random_seed")
        total = int(settings.num_samples) * int(settings.camera_count)
        layout.label(text="Total images: %d" % total, icon="INFO")


class BLENDGEN_PT_placement(bpy.types.Panel):
    """Surface snapping, collision retries, scale, and rotation limits."""

    bl_label = "Placement"
    bl_idname = "BLENDGEN_PT_placement"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendGen"
    bl_parent_id = "BLENDGEN_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blendgen
        col = layout.column(align=True)
        col.prop(settings, "align_to_normal")
        col.prop(settings, "lift_by_origin")
        col.prop(settings, "surface_offset")
        col.prop(settings, "max_placement_retries")
        col.prop(settings, "min_separation")

        col.separator()
        col.label(text="Scale Range")
        row = col.row(align=True)
        row.prop(settings, "scale_min", text="Min")
        row.prop(settings, "scale_max", text="Max")

        col.separator()
        col.label(text="Rotation Limits (degrees)")
        row = col.row(align=True)
        row.prop(settings, "rot_x_min", text="X min")
        row.prop(settings, "rot_x_max", text="X max")
        row = col.row(align=True)
        row.prop(settings, "rot_y_min", text="Y min")
        row.prop(settings, "rot_y_max", text="Y max")
        row = col.row(align=True)
        row.prop(settings, "rot_z_min", text="Z min")
        row.prop(settings, "rot_z_max", text="Z max")


class BLENDGEN_PT_randomization(bpy.types.Panel):
    """Domain-randomization toggles plus camera and lighting ranges."""

    bl_label = "Domain Randomization"
    bl_idname = "BLENDGEN_PT_randomization"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendGen"
    bl_parent_id = "BLENDGEN_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blendgen
        col = layout.column(align=True)
        col.prop(settings, "randomize_lighting")
        col.prop(settings, "randomize_transforms")
        col.prop(settings, "randomize_materials")
        col.prop(settings, "randomize_camera")

        col.separator()
        col.label(text="Camera Orbit")
        row = col.row(align=True)
        row.prop(settings, "cam_radius_min", text="R min")
        row.prop(settings, "cam_radius_max", text="R max")
        row = col.row(align=True)
        row.prop(settings, "cam_elevation_min", text="El min")
        row.prop(settings, "cam_elevation_max", text="El max")
        row = col.row(align=True)
        row.prop(settings, "cam_azimuth_min", text="Az min")
        row.prop(settings, "cam_azimuth_max", text="Az max")
        row = col.row(align=True)
        row.prop(settings, "cam_focal_min", text="mm min")
        row.prop(settings, "cam_focal_max", text="mm max")

        col.separator()
        col.label(text="Lighting")
        row = col.row(align=True)
        row.prop(settings, "light_energy_min", text="E min")
        row.prop(settings, "light_energy_max", text="E max")
        col.prop(settings, "light_color_jitter")
        col.prop(settings, "light_position_offset")
        row = col.row(align=True)
        row.prop(settings, "world_intensity_min", text="W min")
        row.prop(settings, "world_intensity_max", text="W max")

        col.separator()
        col.label(text="Annotation Filters")
        col.prop(settings, "min_visibility")
        col.prop(settings, "occlusion_threshold")
        col.prop(settings, "min_bbox_norm")


class BLENDGEN_PT_presets(bpy.types.Panel):
    """Save and load JSON presets from Blender's user preset directory."""

    bl_label = "Presets"
    bl_idname = "BLENDGEN_PT_presets"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendGen"
    bl_parent_id = "BLENDGEN_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blendgen
        layout.prop(settings, "preset_name")
        row = layout.row(align=True)
        row.operator("blendgen.save_preset", icon="FILE_TICK")
        row.operator("blendgen.load_preset", icon="FILE_FOLDER")
        names = list_presets()
        if names:
            box = layout.box()
            box.label(text="Saved presets:")
            for name in names[:12]:
                box.label(text=name, icon="DOT")
            if len(names) > 12:
                box.label(text="… and %d more" % (len(names) - 12))
        else:
            layout.label(text="No presets saved yet.", icon="INFO")


CLASSES = (
    BLENDGEN_OT_generate_dataset,
    BLENDGEN_OT_stop_generation,
    BLENDGEN_OT_preview_placement,
    BLENDGEN_OT_save_preset,
    BLENDGEN_OT_load_preset,
    BLENDGEN_PT_main,
    BLENDGEN_PT_scene,
    BLENDGEN_PT_dataset,
    BLENDGEN_PT_placement,
    BLENDGEN_PT_randomization,
    BLENDGEN_PT_presets,
)
