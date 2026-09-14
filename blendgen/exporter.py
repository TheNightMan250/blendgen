# =============================================================================
# BlendGen - Rendering, bounding-box annotation, and dataset export (BO-5, BO-6)
# =============================================================================
# For every rendered viewpoint the eight world-space corners of each spawned
# object's bounding box are projected with ``world_to_camera_view``. Tight 2D
# boxes are clamped to the image, objects that are off-frame or heavily
# occluded are dropped, and annotations are written in YOLO and/or COCO.
# The BlendGenPipeline class orchestrates placement, randomization, render,
# and export as a step-able loop so the operator can drive ``wm.progress_*``.
# =============================================================================

from __future__ import annotations

import datetime
import json
import os
import random

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from .placement import PlacementEngine
from .randomization import DomainRandomizer


# Module-level cancel flag observed by BlendGenPipeline.step().
_cancel_requested = False


def request_cancel():
    """Ask the running pipeline to stop after the current image."""
    global _cancel_requested
    _cancel_requested = True


def clear_cancel():
    """Reset the cancel flag at the start of a new run."""
    global _cancel_requested
    _cancel_requested = False


def is_cancel_requested():
    """Return True when the user asked the current run to stop."""
    return _cancel_requested


def render_size(scene):
    """Return ``(width, height)`` in pixels, honouring resolution percentage."""
    scale = scene.render.resolution_percentage / 100.0
    width = max(1, int(round(scene.render.resolution_x * scale)))
    height = max(1, int(round(scene.render.resolution_y * scale)))
    return width, height


def validate_settings(context, require_output=True):
    """Return an error string if the current scene cannot run BlendGen, else None."""
    settings = context.scene.blendgen
    target = settings.get_target_object()
    if target is None:
        return "Please set Target Object to a valid mesh in the current file."

    collection = settings.get_asset_collection()
    if collection is None:
        return "Please set Asset Collection to a valid collection."

    assets = settings.get_asset_meshes()
    if not assets:
        return (
            "The Asset Collection contains no mesh objects to spawn "
            "(the target mesh is excluded if it lives in that collection)."
        )

    if settings.scale_max < settings.scale_min:
        return "Scale Max must be greater than or equal to Scale Min."
    if settings.light_energy_max < settings.light_energy_min:
        return "Light Energy Max must be greater than or equal to Light Energy Min."
    if settings.cam_radius_max < settings.cam_radius_min:
        return "Camera Radius Max must be greater than or equal to Radius Min."

    if require_output:
        raw = (settings.output_directory or "").strip()
        if not raw:
            return "Please set an Output Directory."
        out_dir = bpy.path.abspath(raw)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return "Cannot create output directory '%s' (%s)." % (out_dir, exc)
        if not os.access(out_dir, os.W_OK):
            return "Output directory '%s' is not writable." % out_dir
    return None


def resolve_output_directory(settings):
    """Return an absolute, created output directory for the current settings."""
    out_dir = bpy.path.abspath((settings.output_directory or "").strip())
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def ensure_dataset_tree(out_dir, dataset_format):
    """Create the images / labels / annotations folders used by BlendGen."""
    os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)
    if dataset_format in {"YOLO", "BOTH"}:
        os.makedirs(os.path.join(out_dir, "labels"), exist_ok=True)
    if dataset_format in {"COCO", "BOTH"}:
        os.makedirs(os.path.join(out_dir, "annotations"), exist_ok=True)


def project_corners(scene, camera, obj):
    """Project the 8 world-space AABB corners of ``obj`` into normalized image space.

    ``world_to_camera_view`` returns coordinates with origin at the *bottom-left*
    of the frame. YOLO and COCO use a *top-left* origin, so Y is flipped.
    Corners behind the camera (z <= 0) are discarded because their NDC is
    unstable. Returns ``(xs, ys)`` lists in [possibly outside 0..1] top-left
    normalized coordinates, or ``(None, None)`` when the object is not visible.
    """
    matrix = obj.matrix_world
    xs = []
    ys = []
    for corner in obj.bound_box:
        world = matrix @ Vector(corner)
        ndc = world_to_camera_view(scene, camera, world)
        if ndc.z <= 0.0:
            continue
        xs.append(ndc.x)
        ys.append(1.0 - ndc.y)
    if len(xs) < 2:
        return None, None
    return xs, ys


def tight_bbox(xs, ys, min_bbox_norm, min_visibility):
    """Clamp a projected box to [0, 1] and return YOLO-normalized values.

    Returns a dict with ``x_center, y_center, width, height`` (YOLO) and
    ``x_min, y_min, box_w, box_h`` (normalized top-left box), or None when the
    object is off-frame, degenerate, or below the visibility threshold.
    """
    x_min_u = min(xs)
    x_max_u = max(xs)
    y_min_u = min(ys)
    y_max_u = max(ys)
    unclamped_w = x_max_u - x_min_u
    unclamped_h = y_max_u - y_min_u
    unclamped_area = max(unclamped_w, 0.0) * max(unclamped_h, 0.0)

    x_min = max(0.0, min(1.0, x_min_u))
    x_max = max(0.0, min(1.0, x_max_u))
    y_min = max(0.0, min(1.0, y_min_u))
    y_max = max(0.0, min(1.0, y_max_u))
    width = x_max - x_min
    height = y_max - y_min
    if width <= min_bbox_norm or height <= min_bbox_norm:
        return None

    clamped_area = width * height
    if unclamped_area <= 1e-12:
        return None
    # Objects that fill the frame (camera is close) have a huge unclamped box;
    # keep them when the on-screen area itself is substantial.
    visible = clamped_area / unclamped_area
    if visible < min_visibility and clamped_area < min_visibility:
        return None

    return {
        "x_min": x_min,
        "y_min": y_min,
        "width": width,
        "height": height,
        "x_center": x_min + width * 0.5,
        "y_center": y_min + height * 0.5,
        "visibility": clamped_area / unclamped_area if unclamped_area > 0.0 else 0.0,
    }


def occlusion_visibility(scene, depsgraph, camera, obj):
    """Estimate unoccluded fraction by ray-casting from the camera to bbox probes.

    Nine probes are used: the 8 world-space box corners plus the box centre.
    A probe counts as visible when the first hit is ``obj`` itself, or when the
    ray reaches the probe without hitting anything (thin geometry / miss).
    """
    cam_loc = camera.matrix_world.translation
    matrix = obj.matrix_world
    corners = [matrix @ Vector(corner) for corner in obj.bound_box]
    center = sum(corners, Vector((0.0, 0.0, 0.0))) / float(len(corners))
    probes = [center] + corners

    visible = 0
    tested = 0
    for point in probes:
        vec = point - cam_loc
        distance = vec.length
        if distance <= 1e-6:
            continue
        direction = vec / distance
        origin = cam_loc + direction * 1e-4
        hit, _loc, _nrm, _idx, hit_obj, _mat = scene.ray_cast(
            depsgraph, origin, direction, distance=distance * 0.999
        )
        tested += 1
        if not hit or hit_obj is None:
            visible += 1
            continue
        original = getattr(hit_obj, "original", hit_obj)
        if original == obj or hit_obj == obj:
            visible += 1
    if tested == 0:
        return 1.0
    return visible / float(tested)


class AnnotationExporter:
    """Accumulate per-image records and write YOLO files + a COCO JSON document."""

    def __init__(self, settings, class_names, out_dir, image_width, image_height):
        self.settings = settings
        self.class_names = list(class_names)
        self.class_to_yolo = {name: index for index, name in enumerate(self.class_names)}
        self.out_dir = out_dir
        self.image_width = image_width
        self.image_height = image_height
        self.dataset_format = settings.dataset_format

        self.coco_images = []
        self.coco_annotations = []
        self._ann_id = 1
        self._image_id = 1

    def annotate(self, scene, camera, spawned, image_stem, image_filename, depsgraph):
        """Project every spawned object and write/accumulate annotations.

        Returns the list of YOLO lines produced for this image (may be empty).
        """
        records = []
        for obj in spawned:
            box = self._box_for_object(scene, camera, obj, depsgraph)
            if box is None:
                continue
            source = obj.get("blendgen_source_name", obj.name)
            yolo_id = self.class_to_yolo.get(source, 0)
            records.append((yolo_id, source, box))

        yolo_lines = []
        for yolo_id, _source, box in records:
            yolo_lines.append(
                "%d %.6f %.6f %.6f %.6f"
                % (yolo_id, box["x_center"], box["y_center"], box["width"], box["height"])
            )

        if self.dataset_format in {"YOLO", "BOTH"}:
            label_path = os.path.join(self.out_dir, "labels", image_stem + ".txt")
            with open(label_path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(yolo_lines))
                if yolo_lines:
                    handle.write("\n")

        if self.dataset_format in {"COCO", "BOTH"}:
            self._append_coco(image_filename, records)

        return yolo_lines

    def _box_for_object(self, scene, camera, obj, depsgraph):
        """Return a tight, filtered 2D box dict or None if the object is dropped."""
        xs, ys = project_corners(scene, camera, obj)
        if xs is None:
            return None
        box = tight_bbox(
            xs, ys, self.settings.min_bbox_norm, self.settings.min_visibility
        )
        if box is None:
            return None
        if self.settings.occlusion_threshold > 0.0:
            visibility = occlusion_visibility(scene, depsgraph, camera, obj)
            if visibility < self.settings.occlusion_threshold:
                return None
            box["occlusion_visibility"] = visibility
        return box

    def _append_coco(self, image_filename, records):
        """Append one COCO image record and its instance annotations."""
        image_id = self._image_id
        self.coco_images.append({
            "id": image_id,
            "file_name": image_filename,
            "width": self.image_width,
            "height": self.image_height,
        })
        for yolo_id, source, box in records:
            pixel_x = box["x_min"] * self.image_width
            pixel_y = box["y_min"] * self.image_height
            pixel_w = box["width"] * self.image_width
            pixel_h = box["height"] * self.image_height
            self.coco_annotations.append({
                "id": self._ann_id,
                "image_id": image_id,
                "category_id": yolo_id + 1,
                "bbox": [pixel_x, pixel_y, pixel_w, pixel_h],
                "area": pixel_w * pixel_h,
                "iscrowd": 0,
                "ignore": 0,
                "segmentation": [],
            })
            self._ann_id += 1
        self._image_id += 1

    def write_coco(self):
        """Serialize ``instances_default.json`` in COCO instances format."""
        if self.dataset_format not in {"COCO", "BOTH"}:
            return None
        payload = {
            "info": {
                "description": "BlendGen synthetic object-detection dataset",
                "version": "1.0",
                "year": datetime.datetime.now().year,
                "contributor": "BlendGen",
                "date_created": datetime.datetime.now().isoformat(timespec="seconds"),
            },
            "licenses": [{
                "id": 1,
                "name": "Unknown",
                "url": "",
            }],
            "images": self.coco_images,
            "annotations": self.coco_annotations,
            "categories": [
                {"id": index + 1, "name": name, "supercategory": "object"}
                for index, name in enumerate(self.class_names)
            ],
        }
        path = os.path.join(self.out_dir, "annotations", "instances_default.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return path

    def write_class_files(self):
        """Write ``classes.txt`` and a YOLO ``data.yaml`` next to the images."""
        classes_path = os.path.join(self.out_dir, "classes.txt")
        with open(classes_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(self.class_names))
            if self.class_names:
                handle.write("\n")

        names_block = "\n".join(
            "  %d: %s" % (index, name) for index, name in enumerate(self.class_names)
        )
        yaml_path = os.path.join(self.out_dir, "data.yaml")
        with open(yaml_path, "w", encoding="utf-8") as handle:
            handle.write("path: %s\n" % self.out_dir.replace("\\", "/"))
            handle.write("train: images\n")
            handle.write("val: images\n")
            handle.write("names:\n")
            handle.write(names_block)
            handle.write("\n")
        return classes_path, yaml_path


class BlendGenPipeline:
    """Step-able generation loop: one image per ``step()`` call.

    The operator drives this with a modal TIMER and ``wm.progress_begin`` /
    ``wm.progress_update`` so the Blender UI stays responsive and ESC cancels.
    """

    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.settings = context.scene.blendgen
        self.rng = random.Random()

        self.target = None
        self.assets = []
        self.out_dir = ""
        self.placement = None
        self.randomizer = None
        self.exporter = None

        self.sample_index = 0
        self.camera_index = 0
        self.completed = 0
        self.total_steps = 0
        self.produced = 0
        self._hidden_render = []
        self._saved_filepath = ""
        self._saved_file_format = ""
        self._saved_extension = True
        self._finished = False

    def setup(self):
        """Validate, prepare folders, hide source assets, and construct helpers."""
        clear_cancel()
        error = validate_settings(self.context, require_output=True)
        if error:
            raise RuntimeError(error)

        self.target = self.settings.get_target_object()
        self.assets = self.settings.get_asset_meshes()
        self.out_dir = resolve_output_directory(self.settings)
        ensure_dataset_tree(self.out_dir, self.settings.dataset_format)

        seed = int(self.settings.random_seed)
        if seed == 0:
            seed = random.SystemRandom().randint(1, 2**31 - 1)
        self.rng.seed(seed)

        self.total_steps = int(self.settings.num_samples) * int(self.settings.camera_count)
        self.sample_index = 0
        self.camera_index = 0
        self.completed = 0
        self.produced = 0
        self._finished = False

        self.placement = PlacementEngine(self.context, self.settings, self.rng)
        self.placement.ensure_spawn_collection()
        self.placement.clear()

        self.randomizer = DomainRandomizer(self.context, self.settings, self.rng)
        self.randomizer.setup(self.target)

        width, height = render_size(self.scene)
        class_names = [obj.name for obj in self.assets]
        self.exporter = AnnotationExporter(
            self.settings, class_names, self.out_dir, width, height
        )
        self.exporter.write_class_files()

        self._saved_filepath = self.scene.render.filepath
        self._saved_file_format = self.scene.render.image_settings.file_format
        self._saved_extension = self.scene.render.use_file_extension
        self.scene.render.image_settings.file_format = self.settings.image_format
        self.scene.render.use_file_extension = True

        self._hide_source_assets()
        return self.total_steps

    def step(self):
        """Generate a single image. Return True while more images remain."""
        if self._finished or is_cancel_requested():
            return False
        if self.sample_index >= self.settings.num_samples:
            return False

        if self.camera_index == 0:
            self.placement.clear()
            depsgraph = self.context.evaluated_depsgraph_get()
            self.placement.scatter(
                self.target,
                self.assets,
                int(self.settings.instances_per_sample),
                depsgraph,
            )

        spawned = self.placement.spawned
        self.randomizer.randomize_frame(self.target, spawned)
        self.context.view_layer.update()

        image_index = self.sample_index * int(self.settings.camera_count) + self.camera_index
        stem = "%06d" % image_index
        extension = ".png" if self.settings.image_format == "PNG" else ".jpg"
        rel_name = stem + extension
        abs_no_ext = os.path.join(self.out_dir, "images", stem)
        self.scene.camera = self.randomizer.camera
        self.scene.render.filepath = abs_no_ext
        bpy.ops.render.render(write_still=True)

        depsgraph = self.context.evaluated_depsgraph_get()
        self.exporter.annotate(
            self.scene,
            self.randomizer.camera,
            spawned,
            stem,
            "images/" + rel_name,
            depsgraph,
        )
        self.produced += 1
        self.completed += 1

        self.camera_index += 1
        if self.camera_index >= int(self.settings.camera_count):
            self.camera_index = 0
            self.sample_index += 1

        if self.sample_index >= int(self.settings.num_samples):
            self._finished = True
            return False
        return not is_cancel_requested()

    def finalize(self):
        """Write the COCO JSON (if requested) after the last image."""
        if self.exporter is not None:
            self.exporter.write_coco()

    def cleanup(self):
        """Restore the user's scene: unhide assets, delete spawns, restore render."""
        try:
            if self.placement is not None:
                self.placement.clear()
        except Exception:
            pass
        try:
            if self.randomizer is not None:
                self.randomizer.restore_persistent()
        except Exception:
            pass
        self._restore_source_assets()
        try:
            self.scene.render.filepath = self._saved_filepath
            self.scene.render.image_settings.file_format = self._saved_file_format
            self.scene.render.use_file_extension = self._saved_extension
        except Exception:
            pass
        clear_cancel()

    def status_message(self):
        """Short progress string suitable for operator reports."""
        return "BlendGen: %d / %d images" % (self.completed, self.total_steps)

    def _hide_source_assets(self):
        """Prevent original assets from appearing in renders (instances stay visible)."""
        self._hidden_render = []
        for obj in self.assets:
            self._hidden_render.append((obj, bool(obj.hide_render)))
            obj.hide_render = True

    def _restore_source_assets(self):
        """Restore ``hide_render`` flags captured at setup."""
        for obj, hidden in self._hidden_render:
            try:
                obj.hide_render = hidden
            except ReferenceError:
                pass
        self._hidden_render = []


def preview_placement(context):
    """Scatter instances once without rendering, leaving them in the viewport."""
    error = validate_settings(context, require_output=False)
    if error:
        raise RuntimeError(error)
    settings = context.scene.blendgen
    rng = random.Random()
    if settings.random_seed:
        rng.seed(int(settings.random_seed))
    engine = PlacementEngine(context, settings, rng)
    engine.ensure_spawn_collection()
    engine.clear()
    depsgraph = context.evaluated_depsgraph_get()
    placed = engine.scatter(
        settings.get_target_object(),
        settings.get_asset_meshes(),
        int(settings.instances_per_sample),
        depsgraph,
    )
    return placed
