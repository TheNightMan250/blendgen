"""Real Blender acceptance tests; run after build_demo.py."""
import sys,json,time,traceback,random
from types import SimpleNamespace
from pathlib import Path
from dataclasses import replace
from mathutils import Vector
import bpy
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
import blendgen_prototype
from blendgen_prototype.config import Range
from blendgen_prototype.engine import randomize,frame_visible
from blendgen_prototype.geometry import Obstacles,world_geometry,bounds,overlaps
from blendgen_prototype.surfaces import SurfaceSampler,marked_triangles
from blendgen_prototype.ui import config
from blendgen_prototype.batch_ui import GenerateDataset, is_timer_event
blendgen_prototype.register()
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'deliverables/BlendGen_Kitchen_Prototype.blend'))
scene=bpy.context.scene;s=scene.blendgen_proto
results=[]
def test(name,fn):
    start=time.time()
    try: detail=fn(); status='PASS'
    except Exception as exc: detail=traceback.format_exc();status='FAIL'
    results.append(dict(name=name,status=status,detail=detail,seconds=round(time.time()-start,3)))
    print(json.dumps(results[-1]),flush=True)

def ranges():
    for r in (Range(2,1),Range(float('nan'),1),Range(-1,2)):
        try:r.validate('test',positive=True)
        except ValueError:continue
        raise AssertionError('Invalid range accepted')
    return 'Invalid and nonfinite ranges rejected'

def timer_event_contract():
    """Regression: Blender Event has a type but no timer handle attribute."""
    timer_event=SimpleNamespace(type='TIMER')
    assert is_timer_event(timer_event)
    assert not is_timer_event(SimpleNamespace(type='MOUSEMOVE'))
    session=SimpleNamespace(completed=0,total=2)
    session.step=lambda: setattr(session,'completed',1) or True
    settings=SimpleNamespace(status='')
    window_manager=SimpleNamespace(
        blendgen_stop_export=False,
        progress_update=lambda value: None,
    )
    context=SimpleNamespace(window_manager=window_manager,area=None)
    operator=SimpleNamespace(session=session,settings=settings)
    assert GenerateDataset.modal(operator,context,timer_event)=={'PASS_THROUGH'}
    assert session.completed==1 and settings.status=='Exporting 1/2'
    return 'Timer ticks use documented Event.type without an Event.timer attribute'

def footprint():
    sampler=SurfaceSampler([(Vector((0,0,0)),Vector((1,0,0)),Vector((1,1,0))),
                            (Vector((0,0,0)),Vector((1,1,0)),Vector((0,1,0)))])
    assert sampler.supports([Vector((.2,.2,0)),Vector((.8,.8,1))],0,0)
    assert not sampler.supports([Vector((.2,.2,0)),Vector((1.1,.8,1))],0,0)
    half=SurfaceSampler(sampler.triangles[:1])
    assert not half.supports([Vector((.1,.1,0)),Vector((.9,.9,1))],0,0)
    assert overlaps((Vector((0,0,0)),Vector((3,3,3))),(Vector((1,1,1)),Vector((2,2,2))))
    return 'Footprint coverage rejects spillover and missing triangle; containment rejected'

def trials():
    log=[]; cfg=config(s);lights=[o for o in s.lights.objects if o.type=='LIGHT']
    for seed in (12,13,14,15,16,17):
        result=randomize(bpy.context,s.subject,s.camera,lights,replace(cfg,seed=seed))
        vertices,_=world_geometry(s.subject,bpy.context.evaluated_depsgraph_get())
        assert not Obstacles(bpy.context,s.subject).collides(vertices,cfg.clearance)
        assert frame_visible(scene,s.camera,vertices,cfg.margin)
        assert cfg.scale.low <= result['scale_factor'] <= cfg.scale.high
        assert all(cfg.light.low <= light.data.energy <= cfg.light.high for light in lights)
        assert abs(s.subject.scale.x-result['scale_factor'])<1e-5
        log.append(result)
    (ROOT/'deliverables/trials.json').write_text(json.dumps(log,indent=2))
    return log

def rollback():
    before=(s.subject.matrix_world.copy(),s.camera.matrix_world.copy(),s.camera.data.lens)
    lights=list(s.lights.objects);energies=[o.data.energy for o in lights]
    cfg=replace(config(s),attempts=3,location_bounds=((100,100,100),(101,101,101)))
    try:randomize(bpy.context,s.subject,s.camera,lights,cfg)
    except ValueError:pass
    else:raise AssertionError('Impossible trial succeeded')
    differences=[max(abs(a-b) for ra,rb in zip(old,new) for a,b in zip(ra,rb)) for old,new in zip(before[:2],(s.subject.matrix_world,s.camera.matrix_world))]
    assert max(differences)<1e-6, differences
    assert before[2]==s.camera.data.lens
    assert energies==[o.data.energy for o in lights]
    return 'Impossible bounds restore pose, camera, lens and lights'

def determinism():
    cfg=replace(config(s),seed=22);lights=list(s.lights.objects)
    a=randomize(bpy.context,s.subject,s.camera,lights,cfg)
    b=randomize(bpy.context,s.subject,s.camera,lights,cfg)
    assert a==b
    return 'Same seed yields same trial across repeated runs'

def marking():
    bpy.ops.object.select_all(action='DESELECT')
    table=bpy.data.objects['TABLE | marked top'];table.select_set(True);bpy.context.view_layer.objects.active=table
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='DESELECT')
    assert bpy.ops.blendgen_proto.select_marked()=={'FINISHED'}
    import bmesh
    bm=bmesh.from_edit_mesh(table.data);assert sum(f.select for f in bm.faces)==1
    bpy.ops.blendgen_proto.mark_faces(remove=True)
    layer=bm.faces.layers.int.get('blendgen_spawn');assert not any(f[layer] for f in bm.faces)
    bpy.ops.blendgen_proto.mark_faces(remove=False);assert sum(bool(f[layer]) for f in bm.faces)==1
    bpy.ops.object.mode_set(mode='OBJECT')
    return 'Actual Edit Mode operators select, unmark and remark the top face'

def occlusion():
    vertices,faces=world_geometry(s.subject,bpy.context.evaluated_depsgraph_get())
    center=sum(vertices,Vector())/len(vertices);loc=(s.camera.location+center)/2
    bpy.ops.mesh.primitive_cube_add(size=.8,location=loc);block=bpy.context.object
    try:
        bpy.context.view_layer.update();obstacles=Obstacles(bpy.context,s.subject)
        assert not obstacles.silhouette_visible(scene,s.camera,vertices,faces)
    finally:bpy.data.objects.remove(block,do_unlink=True)
    return 'Pixel-center silhouette test rejects an intervening mesh blocker'

test('timer event API contract',timer_event_contract);test('range validation',ranges)
test('support and containment',footprint)
test('six kitchen trials',trials);test('failure rollback',rollback);test('seed reproducibility',determinism)
test('Edit Mode marking workflow',marking);test('occlusion rejection',occlusion)
scene.render.filepath=str(ROOT/'deliverables/mug_trial.png')
scene.render.resolution_x=960;scene.render.resolution_y=720
result=randomize(bpy.context,s.subject,s.camera,list(s.lights.objects),replace(config(s),seed=15,yaw=Range(0,0)))
s.seed=16;s.status='Valid presentation trial / seed 15'
scene['blendgen_last_trial']=json.dumps(result)
bpy.ops.object.select_all(action='DESELECT');s.subject.select_set(True);bpy.context.view_layer.objects.active=s.subject
if '--checks-only' not in sys.argv:
    bpy.ops.render.render(write_still=True)
    # Save a separate ready-to-present valid trial, leaving the kitchen overview file intact.
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'deliverables/BlendGen_Valid_Trial.blend'))
(ROOT/'deliverables/test_results.json').write_text(json.dumps(results,indent=2))
if any(r['status']=='FAIL' for r in results): raise RuntimeError('Acceptance tests failed')
