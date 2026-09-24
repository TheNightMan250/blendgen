"""Install/enable ZIP in a workspace-isolated Blender profile."""
import bpy,addon_utils,json
from pathlib import Path
root=Path(__file__).resolve().parent
bpy.ops.preferences.addon_install(filepath=str(root/'deliverables/blendgen_prototype.zip'))
bpy.ops.preferences.addon_enable(module='blendgen_prototype')
assert addon_utils.check('blendgen_prototype')[1]
bpy.ops.wm.open_mainfile(filepath=str(root/'deliverables/BlendGen_Kitchen_Prototype.blend'))
s=bpy.context.scene.blendgen_proto
assert s.subject and s.camera and s.lights
assert bpy.ops.blendgen_proto.randomize()=={'FINISHED'}
s.render_count=1;s.output_directory=str(root/'datasets'/'installation_test')
bpy.context.scene.render.resolution_x=160;bpy.context.scene.render.resolution_y=120
bpy.context.scene.eevee.taa_render_samples=8
assert bpy.ops.blendgen_proto.export_dataset()=={'FINISHED'}
manifest=json.loads((Path(s.last_output_directory)/'run.json').read_text())
assert manifest['status']=='complete' and manifest['completed']==1
bpy.ops.preferences.addon_disable(module='blendgen_prototype')
assert not hasattr(bpy.types.Scene,'blendgen_proto')
(root/'deliverables/install_test.json').write_text(json.dumps({'status':'PASS','blender':bpy.app.version_string,'checks':['ZIP installation','enable','saved scene configuration','UI randomize operator','saved YOLO dataset through export operator','disable']},indent=2))
print('INSTALL_TEST_PASS')
