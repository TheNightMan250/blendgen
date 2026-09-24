"""Simulate Blender reloading only the package after an in-session upgrade."""
import sys,importlib,json
from pathlib import Path
import bpy
root=Path(__file__).resolve().parent;sys.path.insert(0,str(root))
import blendgen_prototype as addon
from blendgen_prototype import ui
addon.register()
old_panel=ui.Panel
# Sentinel represents the panel implementation retained from an older release.
ui.Panel.bl_label='STALE PANEL'
addon.unregister()
importlib.reload(addon)
addon.register()
assert addon.ui.Panel is not old_panel
assert addon.ui.Panel.bl_label=='BlendGen Prototype 0.3.1'
settings=bpy.context.scene.blendgen_proto
assert hasattr(settings,'render_count') and hasattr(settings,'output_directory')
assert hasattr(bpy.ops.blendgen_proto,'export_dataset')
addon.unregister()
payload={'status':'PASS','checks':['package-only reload refreshes child UI module','new panel class registered','render count and output folder available']}
(root/'deliverables/reload_test.json').write_text(json.dumps(payload,indent=2))
print('RELOAD_TEST_PASS')
