from pathlib import Path
import zipfile, shutil
ROOT=Path(__file__).resolve().parent; out=ROOT/'deliverables'
with zipfile.ZipFile(out/'blendgen_prototype.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted((ROOT/'blendgen_prototype').glob('*.py')):
        z.write(p,p.relative_to(ROOT))
shutil.copyfile(ROOT/'README.md',out/'README.md')
with zipfile.ZipFile(out/'BlendGen_Supervisor_Demo.zip','w',zipfile.ZIP_DEFLATED) as z:
    for name in ('blendgen_prototype.zip','BlendGen_Kitchen_Prototype.blend','BlendGen_Valid_Trial.blend',
                 'kitchen_overview.png','mug_trial.png','README.md','OPEN_DEMO.cmd','open_demo.py','test_results.json','trials.json','install_test.json','export_test_results.json','reload_test.json'):
        p=out/name
        if p.exists():z.write(p,name)
print(out/'BlendGen_Supervisor_Demo.zip')
