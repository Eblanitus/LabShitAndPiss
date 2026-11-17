"""Превью моделей дрона-носильщика (Blender как модуль, Cycles на CPU):

    python tools/carrier/render_preview.py out.png "Подпись=путь.glb" ["Подпись=путь.fbx" ...]

Каждая модель — строка из трёх ракурсов (3/4 спереди, 3/4 сзади, сбоку), подпись и число треугольников.
Модели ставятся в один масштаб по длине. FBX без материалов красится серым (исходник Hunyuan3D).
"""
import math
import os
import sys
import tempfile

import bpy
import mathutils
from PIL import Image, ImageDraw, ImageFont

VIEWS = [(-35, 22), (145, 22), (90, 4)]  # (азимут от переда, высота), градусы
SIZE = 640


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 32
    sc.cycles.use_denoising = False
    sc.view_settings.view_transform = "Standard"
    w = bpy.data.worlds.new("W")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.16, 0.17, 0.19, 1)
    bg.inputs[1].default_value = 0.9
    for name, rot, e in (("Key", (48, 0, 30), 3.2), ("Fill", (65, 0, -150), 1.3), ("Rim", (70, 0, 180), 1.0)):
        light = bpy.data.lights.new(name, "SUN")
        light.energy = e
        light.angle = math.radians(6)
        o = bpy.data.objects.new(name, light)
        o.rotation_euler = [math.radians(a) for a in rot]
        sc.collection.objects.link(o)


def load(path):
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    grey = None
    for o in meshes:
        if not o.data.materials or o.data.materials[0] is None:
            if grey is None:
                grey = bpy.data.materials.new("grey")
                grey.use_nodes = True
                grey.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.35, 0.36, 0.38, 1)
            o.data.materials.clear()
            o.data.materials.append(grey)
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ mathutils.Vector(c) for o in meshes for c in o.bound_box]
    mn = mathutils.Vector([min(p[i] for p in pts) for i in range(3)])
    mx = mathutils.Vector([max(p[i] for p in pts) for i in range(3)])
    tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)
    return mn, mx, tris, len(meshes)


def front_sign(path):
    # исходник Hunyuan смотрит в -Y Blender, наши выходы (перед -Z в Roblox) — в +Y Blender
    return -1 if path.lower().endswith(".fbx") and "clean" not in os.path.basename(path) else 1


def render(path, prefix):
    reset()
    mn, mx, tris, nparts = load(path)
    sc = bpy.context.scene
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, mn.z))
    floor = bpy.context.object
    fm = bpy.data.materials.new("floor")
    fm.use_nodes = True
    fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.28, 0.29, 0.31, 1)
    fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    floor.data.materials.append(fm)
    c = (mn + mx) / 2
    length = mx.y - mn.y
    cam = bpy.data.cameras.new("C")
    cam.lens = 60
    co = bpy.data.objects.new("C", cam)
    sc.collection.objects.link(co)
    sc.camera = co
    sc.render.resolution_x = sc.render.resolution_y = SIZE
    f = front_sign(path)
    files = []
    for i, (az, el) in enumerate(VIEWS):
        a, e = math.radians(az), math.radians(el)
        d = length * 2.55
        direction = mathutils.Vector((math.sin(a) * math.cos(e), f * math.cos(a) * math.cos(e), math.sin(e)))
        co.location = c + direction * d
        co.rotation_euler = (c - co.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = f"{prefix}_{i}.png"
        bpy.ops.render.render(write_still=True)
        files.append(sc.render.filepath)
    return files, tris, nparts


def main():
    out, items = sys.argv[1], sys.argv[2:]
    tmp = tempfile.mkdtemp()
    rows = []
    for k, item in enumerate(items):
        label, path = item.split("=", 1)
        files, tris, nparts = render(path, os.path.join(tmp, str(k)))
        rows.append((f"{label}: {tris} треугольников, деталей {nparts}", files))
    head = 44
    sheet = Image.new("RGB", (SIZE * len(VIEWS), (SIZE + head) * len(rows)), (24, 25, 28))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    for r, (label, files) in enumerate(rows):
        y = r * (SIZE + head)
        draw.text((14, y + 8), label, fill=(230, 232, 236), font=font)
        for i, fpath in enumerate(files):
            sheet.paste(Image.open(fpath).convert("RGB"), (i * SIZE, y + head))
    sheet.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
