"""Session-only registration of the delivered add-on; no user preferences changed."""
from pathlib import Path
import sys
import bpy
root=Path(__file__).resolve().parent
# Load code from ZIP through Python's zip importer; the module is registered only
# in this process. The scene contains no auto-executing scripts.
sys.path.insert(0,str(root/'blendgen_prototype.zip'))
import blendgen_prototype
blendgen_prototype.register()
bpy.ops.wm.open_mainfile(filepath=str(root/'BlendGen_Kitchen_Prototype.blend'))
