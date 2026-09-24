"""One atomic prototype trial: placement, camera search, then light commit."""
import math
import random
from mathutils import Matrix, Vector, Euler
from bpy_extras.object_utils import world_to_camera_view
from .geometry import Obstacles, bounds, in_bounds, world_geometry
from .surfaces import SurfaceSampler, marked_triangles


def frame_visible(scene, camera, vertices, margin):
    for vertex in vertices:
        p=world_to_camera_view(scene,camera,vertex)
        if not (camera.data.clip_start < p.z < camera.data.clip_end and
                margin <= p.x <= 1-margin and margin <= p.y <= 1-margin):
            return False
    return True


def camera_pose(camera, center, cfg, rng):
    distance=cfg.distance.sample(rng)
    elevation=math.radians(cfg.elevation.sample(rng))
    azimuth=math.radians(cfg.azimuth.sample(rng))
    location=center+Vector((distance*math.cos(elevation)*math.cos(azimuth),
                            distance*math.cos(elevation)*math.sin(azimuth),distance*math.sin(elevation)))
    camera.matrix_world=Matrix.LocRotScale(location,(center-location).to_track_quat('-Z','Y'),Vector((1,1,1)))
    return location


def randomize(context, subject, camera, lights, cfg):
    cfg.validate()
    if subject is None or subject.type != 'MESH': raise ValueError('Select a mesh as the subject')
    if camera is None or camera.type != 'CAMERA' or camera.data.type != 'PERSP':
        raise ValueError('Select a perspective camera')
    if subject.parent or subject.constraints or subject.animation_data:
        raise ValueError('Subject must have no parent, constraints or animation')
    if camera.parent or camera.constraints or camera.animation_data:
        raise ValueError('Camera must have no parent, constraints or animation')
    if camera.data.dof.use_dof:
        raise ValueError('Disable camera depth of field for visibility-checked trials')
    if subject.data.attributes.get('blendgen_spawn'):
        raise ValueError('Subject cannot also be a marked spawn surface')
    if not lights: raise ValueError('Choose a collection containing at least one light')
    if context.scene.render.use_border: raise ValueError('Disable Render Region before running')
    sampler=SurfaceSampler(marked_triangles(context))
    context.view_layer.update()
    obstacles=Obstacles(context,subject)
    original=(subject.matrix_world.copy(),camera.matrix_world.copy(),camera.data.lens,context.scene.camera)
    energies=[(light,light.data.energy) for light in lights]
    # Explicit base scale persists across trials; new attempts never compound scale.
    base=Vector(subject.get('blendgen_base_scale',tuple(subject.scale)))
    rng=random.Random(cfg.seed)
    try:
        camera.data.lens=cfg.focal_length
        for attempt in range(cfg.attempts):
            point=sampler.sample(rng)
            factor=cfg.scale.sample(rng)
            rotation=Euler((0,0,math.radians(cfg.yaw.sample(rng)))).to_quaternion()
            subject.matrix_world=Matrix.LocRotScale(Vector((point.x,point.y,0)),rotation,base*factor)
            context.view_layer.update()
            vertices,_=world_geometry(subject,context.evaluated_depsgraph_get())
            if not vertices: raise ValueError('Subject mesh is empty')
            subject.location.z=point.z-min(v.z for v in vertices)+cfg.clearance+2e-5
            context.view_layer.update()
            vertices,faces=world_geometry(subject,context.evaluated_depsgraph_get())
            if not in_bounds(subject.matrix_world.translation,cfg.location_bounds): continue
            if not sampler.supports(vertices,point.z,cfg.clearance): continue
            if obstacles.collides(vertices,cfg.clearance): continue
            low,high=bounds(vertices); center=(low+high)/2
            # Surface centroids supplement all vertices for occlusion sampling.
            probes=vertices+[sum((vertices[i] for i in face),Vector())/3 for face in faces]
            for _ in range(32):
                location=camera_pose(camera,center,cfg,rng)
                context.view_layer.update()
                if not in_bounds(location,cfg.camera_bounds): continue
                if not frame_visible(context.scene,camera,vertices,cfg.margin): continue
                if not obstacles.clear_view(location,probes): continue
                if not obstacles.silhouette_visible(context.scene,camera,vertices,faces): continue
                for light in lights: light.data.energy=cfg.light.sample(rng)
                context.scene.camera=camera
                subject['blendgen_base_scale']=tuple(base)
                return {'seed':cfg.seed,'attempts':attempt+1,'scale_factor':factor,
                        'location':list(subject.location),'camera':list(location),
                        'vertices_checked':len(vertices),'visibility_probes':len(probes)}
        raise ValueError('No valid placement and camera found. Widen ranges or clear the marked areas.')
    except Exception:
        subject.matrix_world,camera.matrix_world,camera.data.lens,context.scene.camera=original
        for light,energy in energies: light.data.energy=energy
        context.view_layer.update()
        raise
