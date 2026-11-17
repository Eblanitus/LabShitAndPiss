"""Путь 1: доводка сгенерированного FBX дрона-носильщика (Hunyuan3D) под стиль игры. Blender как модуль:

    pip install bpy          # (в отдельном venv; Blender 5.x)
    python tools/carrier/clean_fbx.py "Модели/носилщик.fbx" Модели/Carrier

Что делает: чистит (склейка вершин, мусорные островки, запечённые цвета сегментации),
декимирует каждую деталь до своего бюджета треугольников (всего ~2.4k при лимите Roblox 20k),
режет корпус на Body/Chassis и мачты на Mast/MastTip, даёт латинские имена (раскраска по именам,
см. palette.py), плоские грани, цвета палитрой. Перед модели — -Z (как у CarrierRig), пол — y = 0,
1 единица = 1 стад, длина ~2.4 стада. Пишет carrier_clean.glb и carrier_clean.fbx.
"""
import os
import sys

import bpy
import bmesh
import mathutils

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import palette  # noqa: E402

SRC, OUT = sys.argv[-2], sys.argv[-1]
LENGTH = 2.4  # длина дрона в стадах

# исходная деталь -> (имя, бюджет треугольников). Исходник смотрит в -Y Blender, правый борт — -X.
PARTS = {
    "part_1": ("Body", 900),
    "part_3": ("Track_R", 520),
    "part_5": ("Track_L", 380),
    "part_6": ("Bogie_L", 160),
    "part_9": ("Sprocket_L", 110),
    "part_0": ("Rake", 320),
    "part_2": ("Mast_L", 70),
    "part_4": ("Mast_R", 70),
    "part_7": ("Lid", 40),
    "part_8": ("SidePanel_R", 24),
}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=SRC)


def apply_all(o):
    o.data.transform(o.matrix_world)
    o.matrix_world = mathutils.Matrix.Identity(4)


def clean(o, min_island=40):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.verts.ensure_lookup_table()
    seen, drop = set(), []
    for v in bm.verts:
        if v in seen:
            continue
        isl, st = [], [v]
        seen.add(v)
        while st:
            x = st.pop()
            isl.append(x)
            for e in x.link_edges:
                y = e.other_vert(x)
                if y not in seen:
                    seen.add(y)
                    st.append(y)
        if len(isl) < min_island:
            drop += isl
    bmesh.ops.delete(bm, geom=drop, context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    for a in list(o.data.color_attributes):
        o.data.color_attributes.remove(a)


def decimate(o, target):
    n = len(o.data.polygons)
    if n <= target:
        return
    m = o.modifiers.new("dec", "DECIMATE")
    m.decimate_type = "COLLAPSE"
    m.ratio = target / n
    m.use_collapse_triangulate = True
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=m.name)


def split(o, name, pred):
    """Отделить грани, центр которых проходит pred(center), в новый объект name."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    picked = [f for f in bm.faces if pred(f.calc_center_median())]
    if not picked:
        bm.free()
        return None
    new = o.copy()
    new.data = o.data.copy()
    new.name = new.data.name = name
    bpy.context.scene.collection.objects.link(new)
    keep = set(f.index for f in picked)
    bmesh.ops.delete(bm, geom=picked, context="FACES")
    bm.to_mesh(o.data)
    bm.free()
    bm = bmesh.new()
    bm.from_mesh(new.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in keep], context="FACES")
    bm.to_mesh(new.data)
    bm.free()
    return new


objs = {}
for o in list(bpy.data.objects):
    if o.type != "MESH" or o.name not in PARTS:
        continue
    name, budget = PARTS[o.name]
    apply_all(o)
    clean(o)
    decimate(o, budget)
    o.name = o.data.name = name
    objs[name] = o

# корпус: низ (шасси под кабиной) — отдельная чёрная деталь
split(objs["Body"], "Chassis", lambda c: c.z < 0.165)
# кончики мачт — неон
for s in ("L", "R"):
    split(objs["Mast_" + s], "MastTip_" + s, lambda c: c.z > 0.69)

# разворот: перед в +Y Blender (= -Z в Roblox/glTF/FBX), масштаб в стады
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
ys = [(o.matrix_world @ v.co).y for o in meshes for v in o.data.vertices]
k = LENGTH / (max(ys) - min(ys))
M = mathutils.Matrix.Rotation(3.14159265, 4, "Z") @ mathutils.Matrix.Scale(k, 4)
mats = {}
tris = 0
for o in meshes:
    o.data.transform(M)
    for p in o.data.polygons:
        p.use_smooth = False
    role = palette.role_of(o.name)
    if role not in mats:
        rgb, rough, metal = palette.COLORS[role]
        m = bpy.data.materials.new(role)
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*palette.linear(rgb), 1)
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
        if role == "glow":
            b.inputs["Emission Color"].default_value = (*palette.linear(rgb), 1)
            b.inputs["Emission Strength"].default_value = 2.0
        mats[role] = m
    o.data.materials.clear()
    o.data.materials.append(mats[role])
    tris += sum(len(p.vertices) - 2 for p in o.data.polygons)
    print(f"{o.name:14s} {sum(len(p.vertices) - 2 for p in o.data.polygons):5d} tris  {role}")
print("TOTAL", tris, "tris")

os.makedirs(OUT, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "carrier_clean.glb"), export_format="GLB",
                          export_yup=True, export_apply=True)
bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, "carrier_clean.fbx"), axis_forward="-Z", axis_up="Y",
                         apply_unit_scale=True, apply_scale_options="FBX_SCALE_ALL", mesh_smooth_type="FACE",
                         use_mesh_modifiers=True, add_leaf_bones=False, bake_space_transform=True)
