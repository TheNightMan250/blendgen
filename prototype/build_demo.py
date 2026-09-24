"""Create a self-contained procedural kitchen; run in factory-startup Blender."""
import bpy, math, sys, json
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import blendgen_prototype
from blendgen_prototype.surfaces import ATTRIBUTE
blendgen_prototype.register()
for obj in list(bpy.data.objects): bpy.data.objects.remove(obj,do_unlink=True)
scene=bpy.context.scene
scene.unit_settings.system='METRIC'
OUT=ROOT/'deliverables'; OUT.mkdir(exist_ok=True)

def material(name,color,rough=.5,metal=0,texture=None):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
    nodes=m.node_tree.nodes; links=m.node_tree.links; bsdf=nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=rough; bsdf.inputs['Metallic'].default_value=metal
    if texture:
        tex=nodes.new('ShaderNodeTexNoise'); tex.inputs['Scale'].default_value=5 if texture=='wood' else 35
        tex.inputs['Detail'].default_value=3
        coord=nodes.new('ShaderNodeTexCoord'); mapping=nodes.new('ShaderNodeVectorMath'); mapping.operation='MULTIPLY'
        mapping.inputs[1].default_value=(2,35,3) if texture=='wood' else (1,1,1)
        links.new(coord.outputs['Generated'],mapping.inputs[0]); links.new(mapping.outputs[0],tex.inputs['Vector'])
        ramp=nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position=.15; ramp.color_ramp.elements[0].color=tuple(c*.55 for c in color)+(1,)
        ramp.color_ramp.elements[1].position=.85; ramp.color_ramp.elements[1].color=tuple(min(1,c*1.25) for c in color)+(1,)
        links.new(tex.outputs['Fac'],ramp.inputs[0]); links.new(ramp.outputs[0],bsdf.inputs['Base Color'])
        bump=nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value=.12; bump.inputs['Distance'].default_value=.025
        links.new(tex.outputs['Fac'],bump.inputs['Height']); links.new(bump.outputs[0],bsdf.inputs['Normal'])
    return m

wood=material('Honey oak | procedural grain',(.47,.24,.095),texture='wood')
stone=material('Warm terrazzo | procedural stone',(.68,.65,.57),texture='stone')
sage=material('Sage enamel',(.19,.29,.23),.38)
wallmat=material('Warm plaster',(.79,.75,.65),texture='stone')
white=material('Porcelain',(.87,.89,.83),.22)
teal=material('Mug | deep teal glaze',(.018,.25,.27),.19)
steel=material('Brushed steel',(.45,.49,.5),.27,.85)
black=material('Stove glass',(.025,.032,.038),.22,.3)
floor=material('Sandstone flooring',(.40,.39,.35),texture='stone')
orange=material('Orange peel',(.85,.21,.025),texture='stone')
green=material('Leaf green',(.07,.24,.065),.7)

def cube(name,loc,size,mat,bevel=0):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc); o=bpy.context.object; o.name=name; o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    o.data.materials.append(mat)
    if bevel:
        mod=o.modifiers.new('Soft manufactured edges','BEVEL'); mod.width=bevel; mod.segments=3
        bpy.context.view_layer.objects.active=o; bpy.ops.object.modifier_apply(modifier=mod.name)
        o.data.use_auto_smooth=True
        o.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
    return o

def cylinder(name,loc,radius,depth,mat,vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=radius,depth=depth,location=loc)
    o=bpy.context.object; o.name=name; o.data.materials.append(mat)
    for p in o.data.polygons: p.use_smooth= len(p.vertices)==4
    return o

def torus(name,loc,major,minor,mat,rotation=(0,0,0)):
    bpy.ops.mesh.primitive_torus_add(major_segments=48,minor_segments=12,location=loc,rotation=rotation,major_radius=major,minor_radius=minor)
    o=bpy.context.object; o.name=name; o.data.materials.append(mat)
    for p in o.data.polygons:p.use_smooth=True
    return o

def sphere(name,loc,scale,mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=12,location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; o.data.materials.append(mat)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    for p in o.data.polygons:p.use_smooth=True
    return o

def mark_top(o):
    attr=o.data.attributes.new(ATTRIBUTE,'INT','FACE')
    for p in o.data.polygons:attr.data[p.index].value=int(p.normal.z>.99)
    o['spawn_area_note']='Top face marked. Edit Mode > face select > Show marks.'

# Architectural shell: open front for presentation, three enclosing walls.
cube('Room floor',(0,0,-.08),(6.2,6.2,.16),floor)
cube('Back wall',(0,3.05,1.5),(6.2,.15,3.1),wallmat)
cube('Left wall',(-3.05,0,1.5),(.15,6,3.1),wallmat)
cube('Right wall',(3.05,0,1.5),(.15,6,3.1),wallmat)
for x in range(-3,4):cube('Floor grout X',(x,0,.002),(.009,6,.003),stone)
for y in range(-3,4):cube('Floor grout Y',(0,y,.003),(6,.009,.003),stone)

# Back cabinetry and wall-connected peninsula counter.
for x in (-2.4,-1.6,-.8,0,.8,1.6,2.4):
    cube('Base cabinet',(x,2.55,.45),(.77,.82,.9),sage,.02)
    cube('Cabinet handle',(x,2.12,.73),(.25,.028,.025),steel,.009)
back=cube('Back countertop',(0,2.53,.96),(5.75,.98,.12),stone)
counter=cube('COUNTER | marked top',(-2.02,1.12,.96),(1.05,2.8,.12),stone)
mark_top(counter)
cube('Peninsula base',(-2.02,1.15,.45),(.93,2.65,.9),sage,.015)
for x in (-2.1,-1.1,0,1.1,2.1):
    cube('Upper cabinet',(x,2.82,2.25),(.94,.40,.72),sage,.015)
    cube('Upper handle',(x,2.60,2.15),(.20,.02,.022),steel,.005)
for x in range(12):
    for z in range(3):cube('Backsplash tile',(-2.75+x*.5,2.956,1.15+z*.19),(.48,.02,.17),white,.005)

# Central oak table with a single selectable top face.
table=cube('TABLE | marked top',(.55,-.65,.79),(2.05,1.45,.12),wood); mark_top(table)
for x in (-.28,1.38):
    for y in (-1.20,-.10):cube('Table leg',(x,y,.37),(.085,.085,.74),wood,.01)

# Stove / oven with burners, controls, and handle.
cube('Stovetop',(1.55,2.48,1.035),(.86,.75,.055),black,.02)
for x in (1.32,1.78):
    for y in (2.25,2.68):
        cylinder('Burner',(x,y,1.068),.13,.018,steel)
        torus('Burner ring',(x,y,1.08),.10,.008,black)
cube('Oven door',(1.6,2.112,.43),(.66,.035,.43),black,.025)
cube('Oven handle',(1.6,2.073,.70),(.47,.045,.03),steel,.01)
for x in (1.35,1.52,1.69,1.86):
    knob=cylinder('Oven knob',(x,2.075,.81),.027,.035,steel); knob.rotation_euler.x=math.pi/2

# Sink basin visually recessed into a dark steel surround.
cube('Sink rim',(-.2,2.49,1.033),(.85,.61,.025),steel,.04)
cube('Sink bowl',(-.2,2.49,1.049),(.70,.47,.014),black,.06)
faucet=torus('Faucet arch',(-.2,2.75,1.25),.16,.019,steel,(math.pi/2,0,0))
cylinder('Faucet stem',(-.36,2.75,1.12),.022,.20,steel)

# Plates, utensils, cutting board, fruit and countertop jars.
for z in (.86,.88,.90):
    cylinder('Plate stack',(-.12,-.72,z),.18,.018,white)
    torus('Plate lip',(-.12,-.72,z+.012),.165,.012,white)
for x in (.12,.20):
    cube('Utensil handle',(x,-.76,.866),(.019,.22,.012),steel,.004)
sphere('Spoon bowl',(.12,-.59,.87),(.036,.055,.012),steel)
for x in (.185,.195,.205,.215):cube('Fork tine',(x,-.59,.87),(.006,.07,.007),steel)
cube('Chopping board',(-2.02,1.88,1.045),(.58,.36,.045),wood,.025)
cube('Knife blade',(-2.02,1.89,1.074),(.25,.045,.008),steel,.003)
cube('Knife grip',(-2.22,1.89,1.083),(.16,.05,.027),black,.01)
for x,y in ((-.78,2.45),(-1.02,2.60),(-.98,2.32)):
    sphere('Orange',(x,y,1.12),(.09,.09,.09),orange)
for x in (2.38,2.65):
    cylinder('Storage jar',(x,2.50,1.16),.10,.26,white)
    cylinder('Jar oak lid',(x,2.50,1.30),.11,.028,wood)
pot=cylinder('Herb pot',(-2.58,2.61,1.16),.13,.28,wood)
for i in range(9):
    a=i*2.4
    sphere('Herb leaf',(-2.58+.11*math.cos(a),2.61+.11*math.sin(a),1.36+.02*(i%3)),(.055,.025,.12),green)

# Stool and wall artwork add room context while leaving spawn regions usable.
for x,y in ((.5,-1.85),(1.95,-.65)):
    cylinder('Stool seat',(x,y,.48),.24,.07,wood)
    for dx,dy in ((-.13,-.13),(.13,-.13),(-.13,.13),(.13,.13)):
        cube('Stool leg',(x+dx,y+dy,.23),(.04,.04,.46),steel,.005)
cube('Wall picture frame',(2.962,.35,1.95),(.04,.85,.65),wood,.015)
cube('Wall picture',(2.932,.35,1.95),(.012,.74,.54),sage)

# Hollow ceramic mug, closed revolved profile with integral-looking handle.
profile=[(0,0),(.115,0),(.126,.025),(.137,.28),(.135,.30),(.117,.30),(.115,.28),(.105,.035),(0,.035)]
verts=[]; faces=[]; n=64
for radius,z in profile:
    verts.extend((radius*math.cos(2*math.pi*i/n),radius*math.sin(2*math.pi*i/n),z) for i in range(n))
for j in range(len(profile)-1):
    for i in range(n):faces.append((j*n+i,j*n+(i+1)%n,(j+1)*n+(i+1)%n,(j+1)*n+i))
mesh=bpy.data.meshes.new('Mug solid-wall geometry'); mesh.from_pydata(verts,[],faces); mesh.update()
mug=bpy.data.objects.new('MUG | test subject',mesh); scene.collection.objects.link(mug); mug.data.materials.append(teal)
curve=bpy.data.curves.new('Ceramic C handle','CURVE');curve.dimensions='3D';curve.bevel_depth=.022;curve.bevel_resolution=4;curve.use_fill_caps=True
spline=curve.splines.new('POLY');spline.points.add(40)
for i,p in enumerate(spline.points):
    angle=-math.pi/2+math.pi*i/40
    p.co=(.123+.10*math.cos(angle),0,.16+.10*math.sin(angle),1)
handle=bpy.data.objects.new('Mug handle',curve);scene.collection.objects.link(handle);curve.materials.append(teal)
bpy.ops.object.select_all(action='DESELECT');handle.select_set(True);bpy.context.view_layer.objects.active=handle;bpy.ops.object.convert(target='MESH')
handle=bpy.context.object
bpy.ops.object.select_all(action='DESELECT'); mug.select_set(True); handle.select_set(True); bpy.context.view_layer.objects.active=mug; bpy.ops.object.join()
for p in mug.data.polygons:p.use_smooth=True
mug.location=(.85,-.6,.86); mug['blendgen_base_scale']=(1.,1.,1.)

light_coll=bpy.data.collections.new('Prototype lights'); scene.collection.children.link(light_coll)
def area(name,loc,power,size,target):
    data=bpy.data.lights.new(name,'AREA'); data.energy=power; data.shape='DISK'; data.size=size
    obj=bpy.data.objects.new(name,data); light_coll.objects.link(obj); obj.location=loc
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler(); return obj
area('Key | warm window',(-1,-1,2.8),350,3,(0,0,.8))
area('Fill | soft daylight',(2,-.3,2.65),250,2,(0,1,.8))
area('Counter wash',(0,2.2,2.8),220,2,(-1,1,.9))
scene.world.use_nodes=True; scene.world.node_tree.nodes.get('Background').inputs['Color'].default_value=(.65,.76,1,1)
scene.world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.25

def camera(name,location,target,lens):
    data=bpy.data.cameras.new(name); data.lens=lens; data.clip_start=.03; data.clip_end=100
    obj=bpy.data.objects.new(name,data); scene.collection.objects.link(obj); obj.location=location
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler();return obj
overview=camera('Kitchen Overview',(5,-8,5.1),(-.2,.5,1),43)
trial=camera('Prototype Camera',(.7,-2,1.5),mug.location,48)
s=scene.blendgen_proto; s.subject=mug; s.camera=trial; s.lights=light_coll
scene.render.engine='BLENDER_EEVEE'; scene.eevee.use_gtao=True; scene.eevee.gtao_distance=3; scene.eevee.gtao_factor=1.3
scene.eevee.taa_render_samples=64
scene.render.resolution_x=1200; scene.render.resolution_y=900; scene.render.resolution_percentage=100
scene.view_settings.view_transform='AgX'
scene.camera=overview
# Front and right walls must not hide presentation view; keep right wall in trial scene.
# Overview taken through open front from x=2.6 to stay on interior side of right wall.
overview.location=(2.65,-6.8,4.0); overview.rotation_euler=(Vector((-.25,.55,1.0))-overview.location).to_track_quat('-Z','Y').to_euler()
scene.render.image_settings.file_format='PNG'; scene.render.filepath=str(OUT/'kitchen_overview.png')
scene['prototype_notes']='Table and peninsula top faces are premarked. Enable BlendGen Prototype, open N sidebar > BlendGen Proto. Randomize Valid Trial, Numpad 0, F12.'
for screen in bpy.data.screens:
    for area_ui in screen.areas:
        if area_ui.type=='VIEW_3D':
            area_ui.spaces.active.region_3d.view_perspective='CAMERA'
            area_ui.spaces.active.shading.type='MATERIAL'
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'BlendGen_Kitchen_Prototype.blend'))
bpy.ops.render.render(write_still=True)
print('DEMO_BUILT',flush=True)
