# BlendGen

Blender addon for **synthetic object-detection dataset generation** (GIKI FYP).

It places assets on a 3D surface, avoids collisions, randomizes lighting/camera/materials, renders images, and writes **YOLO** and/or **COCO** bounding-box labels.

## Install in Blender 4.x / 5.x

1. Download this repository as a ZIP (GitHub → **Code** → **Download ZIP**), or clone it.
2. In Blender: **Edit → Preferences → Add-ons → Install from Disk**.
3. Select the `blendgen` folder inside this repo (the folder that contains `__init__.py`).
4. Enable **BlendGen - Synthetic Dataset Generator**.
5. In the 3D Viewport, press **N** and open the **BlendGen** tab.

If an older single-file BlendGen addon is already enabled, disable or remove it first so the two do not clash.

## Usage

1. Set **Target Object** (the mesh surface).
2. Set **Asset Collection** (meshes to spawn; each object name is a class).
3. Set **Output Directory**, format (YOLO / COCO / Both), sample count, and camera count.
4. Click **Preview Placement**, then **Generate Dataset**.
5. Optional: save/load JSON presets from the Presets panel.

Output:

- `images/` — rendered frames
- `labels/*.txt` — YOLO (`class_id x_center y_center width height`)
- `annotations/instances_default.json` — COCO

Esc or **Stop Generation** cancels a run after the current image.
