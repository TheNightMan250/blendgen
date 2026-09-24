"""Transactional single-subject YOLO export, separate from placement and UI."""
from dataclasses import asdict,replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import math
import os
import uuid
import bpy
from bpy_extras.object_utils import world_to_camera_view
from .engine import randomize
from .geometry import world_geometry
from .png_preview import draw_preview


def default_output_directory():
    # Supplied scenes live in prototype/deliverables; keep data in prototype.
    return '//../datasets/'


def atomic_json(path,payload):
    temporary=path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temporary,path)


def subject_box(context,subject,camera):
    vertices,_=world_geometry(subject,context.evaluated_depsgraph_get())
    if not vertices:raise ValueError('Cannot annotate an empty mesh')
    points=[world_to_camera_view(context.scene,camera,v) for v in vertices]
    if any(not camera.data.clip_start<p.z<camera.data.clip_end for p in points):
        raise ValueError('Subject crosses a camera clipping plane')
    left=min(p.x for p in points);right=max(p.x for p in points)
    top=1-max(p.y for p in points);bottom=1-min(p.y for p in points)
    if not (0<=left<right<=1 and 0<=top<bottom<=1):
        raise ValueError('Subject is not completely inside the frame')
    values=((left+right)/2,(top+bottom)/2,right-left,bottom-top)
    if not all(math.isfinite(v) for v in values):raise ValueError('Invalid projected box')
    return ['0']+[f'{value:.8f}' for value in values]


def render_png(scene,path):
    scene.render.filepath=str(path)
    result=bpy.ops.render.render(write_still=True)
    if 'FINISHED' not in result or not path.is_file():raise RuntimeError('Render did not produce an image')


class SceneSnapshot:
    """Only restore fields this exporter and the trial engine can change."""
    def __init__(self,scene,subject,camera,lights):
        self.scene,self.subject,self.camera=scene,subject,camera
        self.subject_matrix=subject.matrix_world.copy();self.camera_matrix=camera.matrix_world.copy()
        self.lens=camera.data.lens;self.active_camera=scene.camera
        self.lights=[(light,light.data.energy) for light in lights]
        self.base_scale=subject.get('blendgen_base_scale')
        self.base_scale=tuple(self.base_scale) if self.base_scale is not None else None
        self.render={key:getattr(scene.render,key) for key in ('filepath','use_file_extension','use_compositing','use_sequencer')}
        self.image={key:getattr(scene.render.image_settings,key) for key in ('file_format','color_mode','color_depth')}

    def restore(self):
        self.subject.matrix_world=self.subject_matrix;self.camera.matrix_world=self.camera_matrix
        self.camera.data.lens=self.lens;self.scene.camera=self.active_camera
        for light,energy in self.lights:light.data.energy=energy
        if self.base_scale is None:
            if 'blendgen_base_scale' in self.subject:del self.subject['blendgen_base_scale']
        else:self.subject['blendgen_base_scale']=self.base_scale
        for key,value in self.render.items():setattr(self.scene.render,key,value)
        for key,value in self.image.items():setattr(self.scene.render.image_settings,key,value)


class ExportSession:
    def __init__(self,context,settings,cfg,renderer=render_png):
        cfg.validate()
        self.context=context;self.scene=context.scene;self.cfg=cfg;self.renderer=renderer
        self.subject=settings.subject;self.camera=settings.camera
        if self.subject is None or self.camera is None:raise ValueError('Select a subject and camera')
        self.lights=[o for o in settings.lights.all_objects if o.type=='LIGHT'] if settings.lights else []
        if not self.lights or any(o.data.type not in {'AREA','POINT','SPOT'} for o in self.lights):
            raise ValueError('Choose a collection of area/point/spot lights')
        if self.subject.hide_render or not self.subject.visible_get():raise ValueError('The subject must be visible in viewport and render')
        if self.scene.render.use_border or self.scene.render.use_multiview:
            raise ValueError('Disable Render Region and Stereo/Multiview before exporting')
        for obj in self.scene.objects:
            if obj.type=='MESH' and any(m.show_render!=m.show_viewport for m in obj.modifiers):
                raise ValueError(f'{obj.name}: viewport/render modifier visibility must match')
            if obj.type=='MESH' and any(m.type=='SUBSURF' and m.levels!=m.render_levels for m in obj.modifiers):
                raise ValueError(f'{obj.name}: subdivision viewport/render levels must match')
        self.total=int(settings.render_count)
        if self.total<1:raise ValueError('Render count must be at least one')
        self.class_name=settings.class_name.strip()
        if not self.class_name or any(c in self.class_name for c in '\r\n'):
            raise ValueError('Enter a single-line class name')
        raw=settings.output_directory.strip()
        if not raw:raise ValueError('Choose an output folder')
        if raw.startswith('//') and not bpy.data.filepath:raise ValueError('Save the Blender scene or choose an absolute output folder')
        root=Path(bpy.path.abspath(raw)).resolve();root.mkdir(parents=True,exist_ok=True)
        self.output=root/f"run_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        self.output.mkdir()
        for folder in ('images','labels','previews','metadata'):(self.output/folder).mkdir()
        (self.output/'classes.txt').write_text(self.class_name+'\n',encoding='utf-8')
        self.completed=0;self.records=[]
        self.manifest={'version':1,'blender':bpy.app.version_string,'status':'running',
            'requested':self.total,'completed':0,'class_names':[self.class_name],
            'source_scene':bpy.data.filepath,'subject':self.subject.name,'configuration':asdict(cfg),
            'box_convention':'YOLO normalized center_x center_y width height; class 0',
            'folders':{'clean_images':'images','yolo_labels':'labels','box_previews':'previews','per_image_metadata':'metadata'},
            'records':self.records}
        atomic_json(self.output/'run.json',self.manifest)
        self.snapshot=SceneSnapshot(self.scene,self.subject,self.camera,self.lights)

    def step(self):
        if self.completed>=self.total:return False
        cfg=replace(self.cfg,seed=self.cfg.seed+self.completed)
        trial=randomize(self.context,self.subject,self.camera,self.lights,cfg)
        self.context.view_layer.update()
        yolo=subject_box(self.context,self.subject,self.camera)
        render=self.scene.render
        render.image_settings.file_format='PNG';render.image_settings.color_mode='RGB';render.image_settings.color_depth='8'
        render.use_file_extension=True;render.use_compositing=False;render.use_sequencer=False
        stem=f'{self.completed:06d}'
        record={'stem':stem,'class_id':0,'class_name':self.class_name,'yolo':yolo,'trial':trial}
        committed=[]
        with TemporaryDirectory(prefix='.pending_',dir=self.output) as directory:
            stage=Path(directory);clean=stage/'image.png';preview=stage/'preview.png'
            self.renderer(self.scene,clean)
            width,height=draw_preview(clean,preview,yolo)
            record.update(width=width,height=height)
            label=stage/'label.txt';label.write_text(' '.join(yolo)+'\n',encoding='utf-8')
            meta=stage/'metadata.json';meta.write_text(json.dumps(record,indent=2),encoding='utf-8')
            files=((clean,'images',stem+'.png'),(label,'labels',stem+'.txt'),
                   (preview,'previews',stem+'.png'),(meta,'metadata',stem+'.json'))
            try:
                for source,folder,name in files:
                    destination=self.output/folder/name
                    os.replace(source,destination);committed.append(destination)
                self.records.append(record);self.completed+=1
                self.manifest['completed']=self.completed
                atomic_json(self.output/'run.json',self.manifest)
            except Exception:
                if self.records and self.records[-1] is record:
                    self.records.pop();self.completed-=1;self.manifest['completed']=self.completed
                for path in committed:path.unlink(missing_ok=True)
                raise
        return self.completed<self.total

    def finish(self,status,error=None):
        self.manifest['status']=status
        self.manifest['completed']=self.completed
        if error:self.manifest['error']=error
        atomic_json(self.output/'run.json',self.manifest)

    def restore(self):
        self.snapshot.restore();self.context.view_layer.update()
