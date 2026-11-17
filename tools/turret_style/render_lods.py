"""Превью трёх уровней Колбы рядом (Cycles на CPU):

    python tools/turret_style/render_lods.py out.png

Строит модели тем же colba_lods.build (акцент в превью — тёплый, как будто залит элемент),
столбцы — L0, L1, L2, строки — 3/4 спереди, 3/4 сзади, игровая камера (сверху издалека,
маленькая картинка, растянутая без сглаживания — столько пикселей турель занимает в игре).
"""
import math
import os
import sys
import tempfile

import bpy
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import colba_lods as cl  # noqa: E402

CELL = 600
GAME_PX = 150  # примерно столько пикселей по ширине занимает турель на экране 1080p с обычного отдаления
VIEWS = [  # (подпись, азимут от переда, высота, отдаление, разрешение, точка взгляда)
    ("3/4 спереди", -48, 22, 1.7, CELL, (0.0, 0.0, 1.8)),
    ("3/4 сзади", 135, 26, 1.7, CELL, (0.0, 0.0, 1.8)),
    ("крупно: казённик сзади", -150, 28, 0.85, CELL, (-3.0, 0.2, 3.0)),
    ("игровая камера", -25, 55, 2.6, GAME_PX, (0.0, 0.0, 1.6)),
]
LABELS = ["L0: как сейчас", "L1: +1 ступенька", "L2: +2 ступеньки"]


def setup_scene():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 48
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "Standard"
    sc.render.film_transparent = False
    w = bpy.data.worlds.new("W")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.13, 0.14, 0.16, 1)
    bg.inputs[1].default_value = 0.8
    for name, rot, e in (("Key", (50, 0, 35), 3.4), ("Fill", (62, 0, -140), 1.2), ("Rim", (70, 0, 175), 1.4)):
        light = bpy.data.lights.new(name, "SUN")
        light.energy = e
        light.angle = math.radians(5)
        o = bpy.data.objects.new(name, light)
        o.rotation_euler = [math.radians(a) for a in rot]
        sc.collection.objects.link(o)
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -1.6))
    floor = bpy.context.object
    fm = bpy.data.materials.new("floor")
    fm.use_nodes = True
    p = fm.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.09, 0.095, 0.105, 1)
    p.inputs["Roughness"].default_value = 0.9
    floor.data.materials.append(fm)
    cam = bpy.data.cameras.new("C")
    cam.lens = 50
    co = bpy.data.objects.new("C", cam)
    sc.collection.objects.link(co)
    sc.camera = co
    return sc, co


def render_level(n, prefix):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc, co = setup_scene()
    mats = cl.make_materials()
    col = cl.build(n, mats)
    tris = cl.bake(col, n)
    size = 16.0  # длина турели с запасом
    files = []
    for i, (_, az, el, dist, res, look) in enumerate(VIEWS):
        center = Vector(look)
        a, e = math.radians(az), math.radians(el)
        d = Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e)))
        co.location = center + d * size * dist
        co.rotation_euler = (center - co.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.resolution_x = sc.render.resolution_y = res
        sc.cycles.samples = 48 if res > 300 else 64
        sc.render.filepath = f"{prefix}_{i}.png"
        bpy.ops.render.render(write_still=True)
        files.append(sc.render.filepath)
    return files, tris, len(col.objects)


def main():
    out = sys.argv[1]
    tmp = tempfile.mkdtemp()
    cols = []
    for n in range(3):
        files, tris, parts = render_level(n, os.path.join(tmp, f"l{n}"))
        cols.append((f"{LABELS[n]}", f"{tris} треугольников, {parts} деталей", files))
    head, side = 70, 40
    W, H = CELL * 3, head + CELL * len(VIEWS)
    sheet = Image.new("RGB", (W + side, H), (20, 21, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 26)
        small = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        font = small = ImageFont.load_default()
    for c, (label, sub, files) in enumerate(cols):
        x = side + c * CELL
        draw.text((x + 14, 6), label, fill=(235, 237, 240), font=font)
        draw.text((x + 14, 40), sub, fill=(170, 175, 182), font=small)
        for r, f in enumerate(files):
            im = Image.open(f).convert("RGB")
            if im.size[0] != CELL:
                im = im.resize((CELL, CELL), Image.NEAREST)
            sheet.paste(im, (x, head + r * CELL))
    for r, (name, *_rest) in enumerate(VIEWS):
        tmp_img = Image.new("RGB", (CELL, side), (20, 21, 24))
        ImageDraw.Draw(tmp_img).text((14, 8), name, fill=(170, 175, 182), font=small)
        sheet.paste(tmp_img.rotate(90, expand=True), (0, head + r * CELL))
    sheet.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
