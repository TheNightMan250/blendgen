"""Dataset acceptance tests, using actual Blender renders and injected failures."""
import sys,json,traceback
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
import blendgen_prototype
blendgen_prototype.register()
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'deliverables/BlendGen_Kitchen_Prototype.blend'))
from blendgen_prototype.dataset import ExportSession, default_output_directory
from blendgen_prototype.png_preview import read_png
from blendgen_prototype.ui import config

scene=bpy.context.scene;s=scene.blendgen_proto
scene.render.resolution_x=320;scene.render.resolution_y=240;scene.eevee.taa_render_samples=8
s.render_count=3;s.output_directory=str(ROOT/'datasets'/'acceptance_tests');s.class_name='mug'
results=[]
def check(name,fn):
    try: detail=fn();state='PASS'
    except Exception: detail=traceback.format_exc();state='FAIL'
    results.append(dict(name=name,status=state,detail=detail));print(json.dumps(results[-1]),flush=True)

def state():
    return dict(subject=[list(r) for r in s.subject.matrix_world],camera=[list(r) for r in s.camera.matrix_world],
                lens=s.camera.data.lens,active=scene.camera.name,filepath=scene.render.filepath,
                format=scene.render.image_settings.file_format,color=scene.render.image_settings.color_mode,
                lights=[o.data.energy for o in s.lights.objects])

def rendered_export():
    before=state();session=ExportSession(bpy.context,s,config(s))
    try:
        while session.step():pass
        session.finish('complete')
    finally:session.restore()
    after=state()
    for key in ('active','filepath','format','color','lens','lights'):assert before[key]==after[key],key
    for key in ('subject','camera'):
        assert max(abs(a-b) for ra,rb in zip(before[key],after[key]) for a,b in zip(ra,rb))<1e-6
    root=session.output
    assert len(list((root/'images').glob('*.png')))==3
    assert len(list((root/'labels').glob('*.txt')))==3
    assert len(list((root/'previews').glob('*.png')))==3
    for clean in (root/'images').glob('*.png'):
        label=(root/'labels'/f'{clean.stem}.txt').read_text().split()
        assert len(label)==5 and label[0]=='0'
        x,y,w,h=map(float,label[1:]);assert all(0<v<1 for v in (x,y,w,h))
        assert 0<=x-w/2<x+w/2<=1 and 0<=y-h/2<y+h/2<=1
        width,height,pixels,_=read_png(clean);pw,ph,preview,_=read_png(root/'previews'/clean.name)
        assert (width,height)==(320,240)==(pw,ph)
        assert pixels!=preview
        record=json.loads((root/'metadata'/f'{clean.stem}.json').read_text())
        assert record['yolo']==label and record['width']==width and record['height']==height
        # Preview border must be on the exact box decoded from the saved label.
        left=max(0,int((x-w/2)*width));top=max(0,int((y-h/2)*height))
        i=(top*width+left)*3
        assert preview[i:i+3]==bytes((30,235,100))
    manifest=json.loads((root/'run.json').read_text());assert manifest['status']=='complete' and manifest['completed']==3
    (ROOT/'deliverables/export_sample_path.txt').write_text(str(root))
    return str(root)

def cancellation_and_unique_runs():
    first=ExportSession(bpy.context,s,config(s));second=None
    try:
        first.finish('cancelled')
        second=ExportSession(bpy.context,s,config(s));second.finish('cancelled')
        assert first.output!=second.output
        assert json.loads((first.output/'run.json').read_text())['completed']==0
    finally:
        if second:second.restore()
        first.restore()
    return 'Cancellation produces an explicit zero-image manifest; existing runs are preserved'

def render_failure():
    def fail(_scene,_path):raise RuntimeError('Injected render failure')
    before=state();session=ExportSession(bpy.context,s,config(s),renderer=fail)
    try:
        try:session.step()
        except RuntimeError as exc:session.finish('failed',str(exc))
        else:raise AssertionError('Failure was swallowed')
    finally:session.restore()
    assert not list((session.output/'images').glob('*'))
    assert not list((session.output/'labels').glob('*'))
    assert not list((session.output/'previews').glob('*'))
    assert json.loads((session.output/'run.json').read_text())['status']=='failed'
    assert before['filepath']==state()['filepath']
    return 'No incomplete image/label/preview sets; failure remains visible'

def defaults():
    assert Path(bpy.path.abspath(default_output_directory())).resolve()==ROOT/'datasets'
    assert hasattr(s,'render_count') and hasattr(s,'output_directory')
    return 'Default is prototype/datasets for supplied scene; UI fields are registered'

def operator_export():
    s.render_count=2
    assert bpy.ops.blendgen_proto.export_dataset()=={'FINISHED'}
    root=Path(s.last_output_directory)
    assert json.loads((root/'run.json').read_text())['completed']==2
    assert not bpy.context.window_manager.blendgen_exporting
    return 'Actual Blender export operator saved two complete image sets and released its run lock'

def finalization_error():
    original=ExportSession.finish
    def fail(self,*args,**kwargs):raise OSError('Injected manifest write failure')
    ExportSession.finish=fail;s.render_count=1
    try:
        try:outcome=bpy.ops.blendgen_proto.export_dataset()
        except RuntimeError:outcome={'CANCELLED'}
        assert outcome=={'CANCELLED'}
        assert 'Failed' in s.status and 'Injected manifest write failure' in s.status
        assert not bpy.context.window_manager.blendgen_exporting
    finally:ExportSession.finish=original
    return 'Finalization errors are reported, never successful; run lock is released'

def partial_run_failure():
    from blendgen_prototype.dataset import render_png
    calls=0
    def fail_second(scene,path):
        nonlocal calls
        calls+=1
        if calls==2:raise RuntimeError('Injected second-render failure')
        render_png(scene,path)
    s.render_count=3;session=ExportSession(bpy.context,s,config(s),renderer=fail_second)
    try:
        assert session.step()
        try:session.step()
        except RuntimeError as exc:session.finish('failed',str(exc))
        else:raise AssertionError('Second render should fail')
    finally:session.restore()
    for folder in ('images','labels','previews','metadata'):
        assert len(list((session.output/folder).iterdir()))==1
    manifest=json.loads((session.output/'run.json').read_text())
    assert manifest['completed']==1 and manifest['status']=='failed'
    return 'A later failure preserves the first complete sample and leaves no second partial set'

check('three real annotated renders',rendered_export)
check('cancel and unique directories',cancellation_and_unique_runs)
check('render failure cleanup',render_failure)
check('default folder and settings',defaults)
check('batch export operator',operator_export)
check('finalization failure visible',finalization_error)
check('partial run preserves completed samples',partial_run_failure)
(ROOT/'deliverables/export_test_results.json').write_text(json.dumps(results,indent=2))
if any(r['status']=='FAIL' for r in results):raise RuntimeError('Export acceptance tests failed')
