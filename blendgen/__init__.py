# =============================================================================
# BlendGen: Blender Based Synthetic Dataset Generation for Object Detection
# =============================================================================
# Final Year Project – Ghulam Ishaq Khan Institute (GIKI)
#   Abdul Hakeem              2023007
#   Syed Muhammad Faseeh      2023689
#   Zouhair Azam Khan         2023789
# Supervisor: Muhammad Huzaifa Shah
#
# Install (Blender 4.x):
#   Edit > Preferences > Add-ons > Install...  and select this `blendgen`
#   folder (or a zip of it). Enable "BlendGen". Open the 3D Viewport sidebar
#   (N) and select the BlendGen tab.
#
# Pipeline:
#   BO-2  Surface-constrained placement via area sampling + ray casting
#   BO-3  BVHTree.FromObject collision avoidance
#   BO-4  Domain randomization (light, camera, materials, transforms)
#   BO-5  YOLO + COCO bounding-box export from projected 3D box corners
#   BO-6  Batch generation with wm.progress_begin / wm.progress_update
#   BO-7  JSON presets in Blender's user preset directory
# =============================================================================

bl_info = {
    "name": "BlendGen - Synthetic Dataset Generator",
    "author": "Abdul Hakeem, Syed Muhammad Faseeh, Zouhair Azam Khan",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > BlendGen",
    "description": (
        "Generate labelled synthetic datasets for object detection with "
        "surface-constrained placement, BVH collision avoidance, domain "
        "randomization, and YOLO/COCO export."
    ),
    "warning": "",
    "doc_url": "",
    "tracker_url": "",
    "support": "COMMUNITY",
    "category": "Render",
}


# Reload submodules when Blender re-enables the add-on so file changes are
# picked up without restarting the application. ``bpy`` is already in the
# module dict on reload, which is what this guard detects.
if "bpy" in locals():
    import importlib

    from . import collision
    from . import exporter
    from . import placement
    from . import preset
    from . import properties
    from . import randomization
    from . import ui

    importlib.reload(collision)
    importlib.reload(properties)
    importlib.reload(placement)
    importlib.reload(randomization)
    importlib.reload(exporter)
    importlib.reload(preset)
    importlib.reload(ui)
else:
    from . import collision
    from . import exporter
    from . import placement
    from . import preset
    from . import properties
    from . import randomization
    from . import ui

import bpy


def register():
    """Register property group, operators, and sidebar panels with Blender."""
    properties.register_properties()
    for cls in ui.CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister all BlendGen classes and detach Scene properties."""
    for cls in reversed(ui.CLASSES):
        bpy.utils.unregister_class(cls)
    properties.unregister_properties()


if __name__ == "__main__":
    register()
