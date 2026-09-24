"""Blender adapter: face marking, prototype settings and one-shot generation."""
import bpy
import bmesh
import json
from .config import Range, RunConfig
from .engine import randomize
from .surfaces import ATTRIBUTE
from .dataset import default_output_directory


class Settings(bpy.types.PropertyGroup):
    subject: bpy.props.PointerProperty(name='Subject',type=bpy.types.Object,poll=lambda s,o:o.type=='MESH')
    camera: bpy.props.PointerProperty(name='Camera',type=bpy.types.Object,poll=lambda s,o:o.type=='CAMERA')
    lights: bpy.props.PointerProperty(name='Lights',type=bpy.types.Collection)
    seed: bpy.props.IntProperty(name='Seed',default=12,min=0)
    next_seed: bpy.props.BoolProperty(name='Advance seed after success',default=True)
    scale_min: bpy.props.FloatProperty(name='Scale min',default=.8,min=.05)
    scale_max: bpy.props.FloatProperty(name='Scale max',default=1.2,min=.05)
    yaw_min: bpy.props.FloatProperty(name='Yaw min',default=0)
    yaw_max: bpy.props.FloatProperty(name='Yaw max',default=360)
    light_min: bpy.props.FloatProperty(name='Power min (W)',default=180,min=.01)
    light_max: bpy.props.FloatProperty(name='Power max (W)',default=450,min=.01)
    distance_min: bpy.props.FloatProperty(name='Distance min (m)',default=1.2,min=.1)
    distance_max: bpy.props.FloatProperty(name='Distance max (m)',default=2.2,min=.1)
    elevation_min: bpy.props.FloatProperty(name='Elevation min',default=15,min=1,max=85)
    elevation_max: bpy.props.FloatProperty(name='Elevation max',default=45,min=1,max=85)
    azimuth_min: bpy.props.FloatProperty(name='Azimuth min',default=-180)
    azimuth_max: bpy.props.FloatProperty(name='Azimuth max',default=180)
    focal_length: bpy.props.FloatProperty(name='Lens (mm)',default=48,min=10,max=150)
    margin: bpy.props.FloatProperty(name='Frame margin',default=.12,min=0,max=.4,subtype='FACTOR')
    clearance: bpy.props.FloatProperty(name='Clearance (m)',default=.008,min=0,max=.1)
    attempts: bpy.props.IntProperty(name='Placement attempts',default=160,min=1,max=1000)
    bound_location: bpy.props.BoolProperty(name='Limit subject location',default=False)
    location_min: bpy.props.FloatVectorProperty(name='Location minimum',default=(-3,-3,0))
    location_max: bpy.props.FloatVectorProperty(name='Location maximum',default=(3,3,2))
    bound_camera: bpy.props.BoolProperty(name='Limit camera location',default=True)
    camera_min: bpy.props.FloatVectorProperty(name='Camera minimum',default=(-2.8,-2.8,.4))
    camera_max: bpy.props.FloatVectorProperty(name='Camera maximum',default=(2.8,2.8,2.65))
    status: bpy.props.StringProperty(default='Mark faces, then randomize a trial.')
    output_directory: bpy.props.StringProperty(name='Output Folder',subtype='DIR_PATH',default=default_output_directory(),
        description='Base folder; each export creates a unique run subfolder. Default: prototype/datasets for supplied scenes')
    render_count: bpy.props.IntProperty(name='Number of Renders',default=10,min=1,max=10000)
    class_name: bpy.props.StringProperty(name='Subject Class',default='mug',description='Class 0 in every YOLO label')
    last_output_directory: bpy.props.StringProperty(name='Last Saved Run',subtype='DIR_PATH')


def config(s):
    return RunConfig(scale=Range(s.scale_min,s.scale_max),yaw=Range(s.yaw_min,s.yaw_max),
        light=Range(s.light_min,s.light_max),distance=Range(s.distance_min,s.distance_max),
        elevation=Range(s.elevation_min,s.elevation_max),azimuth=Range(s.azimuth_min,s.azimuth_max),
        seed=s.seed,attempts=s.attempts,margin=s.margin,clearance=s.clearance,focal_length=s.focal_length,
        location_bounds=(tuple(s.location_min),tuple(s.location_max)) if s.bound_location else None,
        camera_bounds=(tuple(s.camera_min),tuple(s.camera_max)) if s.bound_camera else None)


class MarkFaces(bpy.types.Operator):
    bl_idname='blendgen_proto.mark_faces'
    bl_label='Mark Selected Faces'
    bl_options={'REGISTER','UNDO'}
    remove: bpy.props.BoolProperty(default=False)

    @classmethod
    def poll(cls,context):
        return context.mode=='EDIT_MESH' and not context.window_manager.blendgen_exporting

    def execute(self,context):
        count=0
        for obj in context.objects_in_mode_unique_data:
            mesh=bmesh.from_edit_mesh(obj.data)
            layer=mesh.faces.layers.int.get(ATTRIBUTE) or mesh.faces.layers.int.new(ATTRIBUTE)
            for face in mesh.faces:
                if face.select:
                    face[layer]=0 if self.remove else 1
                    count+=1
            bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'},f'{count} face(s) '+('unmarked' if self.remove else 'marked'))
        return {'FINISHED'}


class SelectMarked(bpy.types.Operator):
    bl_idname='blendgen_proto.select_marked'
    bl_label='Select Marked Faces'
    bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context): return context.mode=='EDIT_MESH' and not context.window_manager.blendgen_exporting
    def execute(self,context):
        bpy.context.tool_settings.mesh_select_mode=(False,False,True)
        for obj in context.objects_in_mode_unique_data:
            bm=bmesh.from_edit_mesh(obj.data); layer=bm.faces.layers.int.get(ATTRIBUTE)
            for face in bm.faces: face.select_set(bool(layer and face[layer]))
            bm.select_flush_mode(); bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


class Trial(bpy.types.Operator):
    bl_idname='blendgen_proto.randomize'
    bl_label='Randomize Valid Trial'
    bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context): return context.mode=='OBJECT' and not context.window_manager.blendgen_exporting
    def execute(self,context):
        s=context.scene.blendgen_proto
        lights=[o for o in s.lights.all_objects if o.type=='LIGHT'] if s.lights else []
        if any(o.data.type not in {'AREA','POINT','SPOT'} for o in lights):
            self.report({'ERROR'},'Use area/point/spot lights; sun energy uses different units')
            return {'CANCELLED'}
        try:
            result=randomize(context,s.subject,s.camera,lights,config(s))
        except (ValueError,RuntimeError) as exc:
            s.status=str(exc); self.report({'ERROR'},str(exc)); return {'CANCELLED'}
        context.scene['blendgen_last_trial']=json.dumps(result)
        s.status=f"Valid trial / seed {s.seed} / {result['attempts']} placement attempt(s)"
        if s.next_seed: s.seed+=1
        self.report({'INFO'},s.status)
        return {'FINISHED'}


class Panel(bpy.types.Panel):
    bl_label='BlendGen Prototype 0.3.1'
    bl_idname='BLENDGEN_PROTO_PT_main'
    bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='BlendGen Proto'
    def draw(self,context):
        layout=self.layout; s=context.scene.blendgen_proto
        if context.window_manager.blendgen_exporting:
            layout.label(text=s.status[:65])
            layout.operator('blendgen_proto.stop_export')
            layout.label(text='Esc also stops between images.')
            return
        box=layout.box();box.label(text='Dataset Export',icon='OUTPUT')
        box.prop(s,'output_directory');box.prop(s,'render_count');box.prop(s,'class_name')
        box.label(text='Each image uses seed + image index.')
        box.operator('blendgen_proto.export_dataset',icon='RENDER_STILL')
        box.operator('blendgen_proto.open_output',icon='FILE_FOLDER')
        if s.last_output_directory:
            row=box.row();row.enabled=False;row.prop(s,'last_output_directory')
        box.label(text='Clean PNG + YOLO TXT + box preview')
        layout.label(text='1. Edit Mode: select top faces')
        layout.operator('blendgen_proto.mark_faces')
        row=layout.row(); row.operator('blendgen_proto.mark_faces',text='Unmark').remove=True
        row.operator('blendgen_proto.select_marked',text='Show marks')
        layout.separator(); layout.label(text='2. Object Mode: configure trial')
        for name in ('subject','camera','lights','seed','next_seed'): layout.prop(s,name)
        for label,lo,hi in [('Scale','scale_min','scale_max'),('Yaw (degrees)','yaw_min','yaw_max'),
                ('Light power','light_min','light_max'),('Camera distance','distance_min','distance_max'),
                ('Elevation','elevation_min','elevation_max'),('Azimuth','azimuth_min','azimuth_max')]:
            layout.label(text=label); row=layout.row(align=True); row.prop(s,lo,text='Min'); row.prop(s,hi,text='Max')
        for name in ('focal_length','margin','clearance','attempts'): layout.prop(s,name)
        for toggle,lo,hi in [('bound_location','location_min','location_max'),('bound_camera','camera_min','camera_max')]:
            layout.prop(s,toggle)
            if getattr(s,toggle): layout.prop(s,lo); layout.prop(s,hi)
        layout.separator(); layout.operator('blendgen_proto.randomize',icon='FILE_REFRESH')
        layout.label(text='Numpad 0: camera / F12: render')
        layout.label(text=s.status[:65])

from .batch_ui import CLASSES as BATCH_CLASSES
CLASSES=(Settings,MarkFaces,SelectMarked,Trial,Panel)+BATCH_CLASSES
