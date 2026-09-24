bl_info = {'name':'BlendGen Prototype','author':'BlendGen team', 'version':(0,3,1),
           'blender':(4,0,0),'location':'View3D > Sidebar > BlendGen Proto',
           'description':'Marked face placement and bounded kitchen trials','category':'Object'}
# Blender reloads the package during an in-session ZIP update, but Python does
# not automatically reload its children. Refresh them in dependency order so
# registration cannot reuse the previous release's panel and property classes.
if 'bpy' in locals():
    import importlib
    from . import config, geometry, surfaces, engine, png_preview, dataset, batch_ui, ui
    for module in (config, geometry, surfaces, engine, png_preview, dataset, batch_ui, ui):
        importlib.reload(module)

import bpy
from .ui import CLASSES,Settings

def register():
    for cls in CLASSES: bpy.utils.register_class(cls)
    bpy.types.Scene.blendgen_proto=bpy.props.PointerProperty(type=Settings)
    bpy.types.WindowManager.blendgen_exporting=bpy.props.BoolProperty(default=False,options={'SKIP_SAVE'})
    bpy.types.WindowManager.blendgen_stop_export=bpy.props.BoolProperty(default=False,options={'SKIP_SAVE'})

def unregister():
    if hasattr(bpy.types.Scene,'blendgen_proto'): del bpy.types.Scene.blendgen_proto
    for name in ('blendgen_exporting','blendgen_stop_export'):
        if hasattr(bpy.types.WindowManager,name):delattr(bpy.types.WindowManager,name)
    for cls in reversed(CLASSES): bpy.utils.unregister_class(cls)
