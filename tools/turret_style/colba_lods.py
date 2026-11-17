"""Образцы стиля: Колба в трёх уровнях детализации (Blender как модуль, `pip install bpy`).

    python tools/turret_style/colba_lods.py Модели/Turrets

Пишет colba_l0.glb, colba_l1.glb, colba_l2.glb. В игру не подключены — это образцы для выбора
уровня детализации (docs/model_style_guide.md).

  L0 — как в игре: авторская модель Модели/Turrets/source/colba2.blend (копия «КОЛБа 2.blend»)
       без того, чего нет в ServerStorage.ColbaTurretTemplate (воронка FlaskFiller, болты
       DetailBolts_Merged, провода Wire_Struts), цвета деталей — как в шаблоне, плюс жидкость.
  L1 — +1 ступенька поверх неё: цоколь тумбы, решётки и неоновые щели на гранях, неоновое кольцо
       стола и крышки колбы, болты, отверстие ствола, решётка и штуцеры казённика, фаски на острых
       брусках; возвращены авторские болты и провода. Катушки, трубки, провода облегчены вдвое.
  L2 — +2: бронеплиты тумбы, втулки и раскосы клетки колбы, хомуты катушек, рёбра охлаждения,
       гидроцилиндр подъёма, манометр, болты на N-панелях.

Оси как в .blend: пол z = 0, ствол смотрит в -X, 1 единица = 1 стад. Роль цвета — по материалу:
Steel_Dark / Steel_Mid / Steel_Light / Plastic_Black / Panel_Light / Accent (неон, игра красит
в цвет элемента) / Glass / Liquid (тоже красится).
"""
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

# --------------------------------------------------------------------------- палитра
# sRGB 0..255, шероховатость, металличность. Цвета — из шаблона Колбы и вики (art_style_v1).
PALETTE = {
    "Steel_Dark": ((45, 48, 55), 0.55, 0.65),
    "Steel_Mid": ((65, 70, 78), 0.5, 0.65),
    "Steel_Light": ((95, 100, 110), 0.45, 0.65),
    "Plastic_Black": ((24, 25, 28), 0.85, 0.0),
    "Panel_Light": ((176, 182, 192), 0.8, 0.0),
    "Accent": ((255, 255, 255), 0.4, 0.0),  # в превью красится ACCENT_PREVIEW
    "Glass": ((225, 240, 245), 0.05, 0.0),
    "Liquid": ((255, 255, 255), 0.3, 0.0),
}
ACCENT_PREVIEW = (255, 140, 40)  # как будто залит элемент (тёплый, чтобы было видно на сером)


def lin(c):
    return tuple((x / 255) / 12.92 if x / 255 <= 0.04045 else ((x / 255 + 0.055) / 1.055) ** 2.4 for x in c)


def make_materials(accent=ACCENT_PREVIEW):
    mats = {}
    for name, (col, rough, metal) in PALETTE.items():
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        p = m.node_tree.nodes["Principled BSDF"]
        c = accent if name in ("Accent", "Liquid") else col
        p.inputs["Base Color"].default_value = (*lin(c), 1)
        p.inputs["Roughness"].default_value = rough
        p.inputs["Metallic"].default_value = metal
        if name == "Accent":
            p.inputs["Emission Color"].default_value = (*lin(c), 1)
            p.inputs["Emission Strength"].default_value = 4.0
        if name == "Liquid":
            p.inputs["Emission Color"].default_value = (*lin(c), 1)
            p.inputs["Emission Strength"].default_value = 0.6
        if name == "Glass":
            p.inputs["Transmission Weight"].default_value = 1.0
            p.inputs["IOR"].default_value = 1.2
            p.inputs["Alpha"].default_value = 0.35
            m.surface_render_method = "BLENDED"
        mats[name] = m
    return mats


# --------------------------------------------------------------------------- уровень
class Lv:
    """Ручки уровня детализации. Всё, что отличает L0/L1/L2, — здесь или в `if lv.n >= k`."""

    def __init__(self, n):
        self.n = n
        self.edge = (0.9, 0.55, 0.38)[n]  # длина грани по окружности, стад: число граней — от размера
        self.seg_min = (6, 8, 8)[n]
        self.seg_max = (16, 32, 40)[n]
        self.seg_small = (6, 8, 10)[n]    # шланги и трубки
        self.bevel = (0.0, 0.07, 0.1)[n]  # фаска, стад
        self.bevel_seg = (0, 1, 2)[n]     # 1 = скос, 2 = скруглённый скос (только на крупном)

    def segs(self, r):
        n = round(2 * math.pi * r / self.edge / 4) * 4  # кратно 4: ровные оси симметрии
        return max(self.seg_min, min(self.seg_max, n))


# --------------------------------------------------------------------------- построение
class Builder:
    def __init__(self, lv, mats):
        self.lv = lv
        self.mats = mats
        self.col = bpy.data.collections.new(f"Colba_L{lv.n}")
        bpy.context.scene.collection.children.link(self.col)
        self.count = {}

    def _name(self, name):
        k = self.count.get(name, 0)
        self.count[name] = k + 1
        return name if k == 0 else f"{name}_{k}"

    def obj(self, name, verts, faces, mat, bevel=None, bevel_seg=None):
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in verts], [], faces)
        me.validate()
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(self._name(name), me)
        me.name = o.name
        o.data.materials.append(self.mats[mat])
        self.col.objects.link(o)
        b = self.lv.bevel if bevel is None else bevel
        dims = [max(v[i] for v in verts) - min(v[i] for v in verts) for i in range(3)]
        if mat in NO_BEVEL or sorted(dims)[1] <= 0.6:
            b = 0  # на неоне, стекле, чёрном пластике и мелочи фаска не видна — только треугольники
        if b > 0 and self.lv.bevel_seg > 0:
            w = min(b, 0.22 * min(d for d in dims if d > 1e-6))
            if w > 0.015:
                mod = o.modifiers.new("Bevel", "BEVEL")
                mod.width = w
                big = sorted(dims)[1] >= 1.0  # мелочь — простой скос, скругление не видно
                mod.segments = (self.lv.bevel_seg if big else 1) if bevel_seg is None else bevel_seg
                mod.limit_method = "ANGLE"
                mod.angle_limit = math.radians(35)
                mod.miter_outer = "MITER_ARC"
        return o

    # ---- примитивы (все строятся в местных осях, потом матрица)
    def prism(self, name, poly, h, mat, m=Matrix(), **kw):
        """Многоугольник poly (x, y) выдавлен по местной Z от 0 до h."""
        n = len(poly)
        verts = [m @ Vector((x, y, 0)) for x, y in poly] + [m @ Vector((x, y, h)) for x, y in poly]
        faces = [list(range(n))[::-1], list(range(n, 2 * n))]
        faces += [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
        return self.obj(name, verts, faces, mat, **kw)

    def box(self, name, size, loc, mat, rot=None, **kw):
        sx, sy, sz = size
        m = Matrix.Translation(Vector(loc))
        if rot:
            m = m @ rot
        m = m @ Matrix.Translation((0, 0, -sz / 2))
        poly = [(-sx / 2, -sy / 2), (sx / 2, -sy / 2), (sx / 2, sy / 2), (-sx / 2, sy / 2)]
        return self.prism(name, poly, sz, mat, m, **kw)

    def ngon(self, n, r, phase=0.0):
        return [(r * math.cos(phase + 2 * math.pi * i / n), r * math.sin(phase + 2 * math.pi * i / n)) for i in range(n)]

    def cyl(self, name, r, h, loc, mat, axis="Z", seg=None, phase=None, **kw):
        """Цилиндр: центр loc, ось axis."""
        seg = seg or self.lv.segs(r)
        phase = math.pi / seg if phase is None else phase
        m = Matrix.Translation(Vector(loc)) @ AXIS[axis] @ Matrix.Translation((0, 0, -h / 2))
        return self.prism(name, self.ngon(seg, r, phase), h, mat, m, **kw)

    def lathe(self, name, profile, loc, mat, axis="Z", seg=None, closed=True, **kw):
        """Тело вращения: profile — [(r, z)] снизу вверх, r=0 на концах закрывает."""
        seg = seg or self.lv.segs(max(r for r, _ in profile))
        m = Matrix.Translation(Vector(loc)) @ AXIS[axis]
        verts, faces, rings = [], [], []
        for r, z in profile:
            if r < 1e-6:
                rings.append([len(verts)])
                verts.append(m @ Vector((0, 0, z)))
            else:
                ring = []
                for i in range(seg):
                    a = 2 * math.pi * i / seg + math.pi / seg
                    ring.append(len(verts))
                    verts.append(m @ Vector((r * math.cos(a), r * math.sin(a), z)))
                rings.append(ring)
        for a, b in zip(rings, rings[1:]):
            if len(a) == 1:
                faces += [[a[0], b[(i + 1) % seg], b[i]] for i in range(seg)]
            elif len(b) == 1:
                faces += [[a[i], a[(i + 1) % seg], b[0]] for i in range(seg)]
            else:
                faces += [[a[i], a[(i + 1) % seg], b[(i + 1) % seg], b[i]] for i in range(seg)]
        if closed:
            if len(rings[0]) > 1:
                faces.append(rings[0][::-1])
            if len(rings[-1]) > 1:
                faces.append(rings[-1])
        return self.obj(name, verts, faces, mat, **kw)

    def ring(self, name, r_out, r_in, h, loc, mat, axis="Z", seg=None, **kw):
        """Кольцо (шайба с дыркой)."""
        seg = seg or self.lv.segs(r_out)
        m = Matrix.Translation(Vector(loc)) @ AXIS[axis]
        verts = []
        for z in (-h / 2, h / 2):
            for r in (r_out, r_in):
                for i in range(seg):
                    a = 2 * math.pi * i / seg + math.pi / seg
                    verts.append(m @ Vector((r * math.cos(a), r * math.sin(a), z)))
        o0, i0, o1, i1 = 0, seg, 2 * seg, 3 * seg
        faces = []
        for i in range(seg):
            j = (i + 1) % seg
            faces.append([o0 + i, o0 + j, o1 + j, o1 + i])  # наружу
            faces.append([i0 + j, i0 + i, i1 + i, i1 + j])  # внутрь
            faces.append([o0 + j, o0 + i, i0 + i, i0 + j])  # низ
            faces.append([o1 + i, o1 + j, i1 + j, i1 + i])  # верх
        return self.obj(name, verts, faces, mat, **kw)

    def arc_band(self, name, center, r_out, r_in, a0, a1, y0, y1, mat, seg=None, **kw):
        """Дуга-пластина в плоскости XZ (центр (cx, cz)), углы a0..a1 в градусах, толщина по Y."""
        seg = seg or max(4, self.lv.segs(r_out) // 4)
        cx, cz = center
        pts_o, pts_i = [], []
        for k in range(seg + 1):
            a = math.radians(a0 + (a1 - a0) * k / seg)
            pts_o.append((cx + r_out * math.cos(a), cz + r_out * math.sin(a)))
            pts_i.append((cx + r_in * math.cos(a), cz + r_in * math.sin(a)))
        poly = pts_o + pts_i[::-1]
        n = len(poly)
        verts = [Vector((x, y0, z)) for x, z in poly] + [Vector((x, y1, z)) for x, z in poly]
        faces = [list(range(n)), list(range(n, 2 * n))[::-1]]
        faces += [[i, n + i, n + (i + 1) % n, (i + 1) % n] for i in range(n)]
        return self.obj(name, verts, faces, mat, **kw)

    def tube(self, name, pts, r, mat, seg=None, **kw):
        """Шланг/трубка по ломаной pts (сглаживается сплайном), круглое сечение."""
        seg = seg or self.lv.seg_small
        cu = bpy.data.curves.new(name, "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = r
        cu.bevel_resolution = max(0, seg // 4 - 1)
        cu.use_fill_caps = True
        sp = cu.splines.new("BEZIER")
        sp.bezier_points.add(len(pts) - 1)
        for bp, p in zip(sp.bezier_points, pts):
            bp.co = Vector(p)
            bp.handle_left_type = bp.handle_right_type = "AUTO"
        sp.resolution_u = (3, 4, 6)[self.lv.n]
        tmp = bpy.data.objects.new("tmp", cu)
        self.col.objects.link(tmp)
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
        self.col.objects.unlink(tmp)
        bpy.data.objects.remove(tmp)
        o = bpy.data.objects.new(self._name(name), me)
        o.data.materials.clear()
        o.data.materials.append(self.mats[mat])
        self.col.objects.link(o)
        return o

    def bolt(self, name, loc, axis="Z", r=0.09, h=0.08):
        return self.cyl(name, r, h, loc, "Steel_Light", axis=axis, seg=6, bevel=0)


NO_BEVEL = {"Accent", "Glass", "Liquid", "Plastic_Black"}

AXIS = {
    "Z": Matrix(),
    "X": Matrix.Rotation(math.pi / 2, 4, "Y"),
    "Y": Matrix.Rotation(-math.pi / 2, 4, "X"),
}

# --------------------------------------------------------------------------- Колба
# Основа — авторская модель (Модели/Turrets/source/colba2.blend, копия «КОЛБа 2.blend»).
# Оси .blend: пол z = 0, ствол смотрит в -X и опущен на 8°, колба слева (-Y), ствол справа (+Y).
SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Модели", "Turrets", "source", "colba2.blend")

# В игре (ServerStorage.ColbaTurretTemplate) этих деталей .blend нет: воронку убрали (#67),
# болты и провода в FBX не попали.
NOT_IN_GAME = ("FlaskFiller", "DetailBolts_Merged", "Wire_Struts")

# Цвет детали — как в шаблоне игры (place/game.rbxl), по началу имени.
ROLE = [
    ("Колба.005", "Steel_Mid"), ("Колба", "Glass"),
    ("OctoBase", "Steel_Dark"), ("Turntable", "Steel_Dark"),
    ("ArmBasePlate", "Steel_Mid"), ("ArmHydLower", "Steel_Light"),
    ("FlaskCap", "Steel_Light"), ("FlaskCollar", "Steel_Mid"), ("FlaskRing", "Steel_Light"),
    ("FlaskRib", "Steel_Dark"), ("Strut", "Steel_Light"),
    ("Breech", "Steel_Dark"), ("Leg", "Steel_Dark"),
    ("DetailIndicator", "Accent"), ("NPlateL_Strip", "Accent"), ("NPlateR_Strip", "Accent"),
    ("LiquidTube", "Accent"), ("Coil", "Accent"), ("Vent", "Accent"),
    ("NPlate", "Steel_Mid"), ("NRib", "Steel_Mid"),
    ("Barrel", "Steel_Dark"), ("MiniBarrel", "Steel_Dark"), ("MuzzleRing", "Steel_Dark"),
    ("SideCover", "Steel_Mid"), ("SideShield", "Steel_Mid"), ("Rail", "Steel_Light"),
    ("DetailBolts", "Steel_Light"), ("Wire", "Plastic_Black"),
]

BASE_C = Vector((0.02, -0.05, 0))     # центр тумбы
OCTO_R = 5.10                         # тумба: до грани, z 0..1.6
TT_R, TT_Z = 4.5, 1.9                 # поворотный стол r 4.5, z 1.6..2.2
FLASK = Vector((-0.58, -2.30, 0))     # ось колбы
GUN_Y = 1.45
PITCH = math.atan2(0.93, 6.59)        # ствол поднимается к казённику (+X)
COIL0 = Vector((-4.22, GUN_Y, 5.70))  # центр первой катушки, на оси ствола
AXIS_DIR = Vector((math.cos(PITCH), 0, math.sin(PITCH)))


def role_of(name):
    return next((r for p, r in ROLE if name.startswith(p)), "Steel_Dark")


def load_source(b, keep_extra):
    """Авторская модель в коллекцию b.col: модификаторы применены, трансформы запечены, цвета игры."""
    with bpy.data.libraries.load(SOURCE) as (src, dst):
        dst.objects = [n for n in src.objects]
    dg = None
    tmp = bpy.data.collections.new("src")
    bpy.context.scene.collection.children.link(tmp)
    for o in dst.objects:
        if o is not None:
            tmp.objects.link(o)
    dg = bpy.context.evaluated_depsgraph_get()
    for o in list(tmp.objects):
        if o.type not in ("MESH", "CURVE"):
            continue
        if o.name.startswith(NOT_IN_GAME) and not keep_extra:
            continue
        me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
        me.transform(o.matrix_world)
        role = role_of(o.name)
        me.materials.clear()
        me.materials.append(b.mats[role])
        for p in me.polygons:
            p.material_index = 0
        name = "Flask" if o.name == "Колба" else "BarrelBody" if o.name == "Колба.005" else o.name
        no = bpy.data.objects.new(name, me)
        b.col.objects.link(no)
    for o in list(tmp.objects):
        bpy.data.objects.remove(o)
    bpy.data.collections.remove(tmp)
    # Жидкость: копия колбы 80% по ширине и 88% по высоте, как Liquid в шаблоне
    flask = b.col.objects["Flask"]
    me = flask.data.copy()
    c = FLASK + Vector((0, 0, 3.93))
    me.transform(Matrix.Translation(c) @ Matrix.Diagonal((0.8, 0.8, 0.88, 1)) @ Matrix.Translation(-c))
    me.materials.clear()
    me.materials.append(b.mats["Liquid"])
    b.col.objects.link(bpy.data.objects.new("Liquid", me))


def gun_m(t, extra=Matrix()):
    """Матрица на оси ствола: t — расстояние вдоль оси от первой катушки, местная Z — вдоль ствола."""
    p = COIL0 + AXIS_DIR * t
    return Matrix.Translation(p) @ Matrix.Rotation(-PITCH, 4, "Y") @ AXIS["X"] @ extra


def bevel_existing(b, names, width):
    """Фаска на авторских деталях без неё (бруски с острыми рёбрами)."""
    for o in b.col.objects:
        if o.name.startswith(names) and not o.modifiers:
            mod = o.modifiers.new("Bevel", "BEVEL")
            mod.width = width
            mod.segments = 1
            mod.limit_method = "ANGLE"
            mod.angle_limit = math.radians(35)


def lighten(b, names, ratio):
    """Треугольники с мелочи: катушки, трубки, индикаторы у автора гуще, чем видно в игре."""
    for o in b.col.objects:
        if o.name.startswith(names):
            mod = o.modifiers.new("Decimate", "DECIMATE")
            mod.ratio = ratio


def detail_l1(b):
    lv = b.lv
    # --- тумба: цоколь шире корпуса, решётки на прямых гранях, неоновые щели на косых
    b.prism("OctoPlinth", b.ngon(8, (OCTO_R + 0.14) / math.cos(math.pi / 8), math.pi / 8), 0.3, "Steel_Mid",
            Matrix.Translation(BASE_C - Vector((0, 0, 0.0))))
    for k in range(8):
        a = 2 * math.pi * k / 8
        rot = Matrix.Rotation(a, 4, "Z")
        if k % 2 == 0:
            b.box("Grille", (0.1, 2.6, 0.6), BASE_C + rot @ Vector((OCTO_R + 0.02, 0, 0.95)), "Plastic_Black", rot)
            slats = 4 if lv.n == 1 else 6
            for s in range(slats):
                y = -1.1 + 2.2 * s / (slats - 1)
                b.box("GrilleSlat", (0.1, 0.14, 0.54), BASE_C + rot @ Vector((OCTO_R + 0.05, y, 0.95)), "Steel_Light", rot,
                      bevel=0)
        else:
            b.box("Glow_Base", (0.08, 1.4, 0.12), BASE_C + rot @ Vector((OCTO_R + 0.03, 0, 1.1)), "Accent", rot)
    # --- поворотный стол: неоновое кольцо по кромке и болты
    b.ring("Glow_Turntable", TT_R + 0.03, TT_R - 0.1, 0.07, BASE_C + Vector((0, 0, TT_Z)), "Accent")
    nb = 8 if lv.n == 1 else 16
    for k in range(nb):
        a = 2 * math.pi * (k + 0.5) / nb
        p = BASE_C + Vector((4.05 * math.cos(a), 4.05 * math.sin(a), 2.24))
        if (p - FLASK).to_2d().length > 2.0:
            b.bolt("Bolt", p)
    # --- колба: ступица и неоновое кольцо на крышке
    b.cyl("FlaskCapHub", 0.75, 0.2, FLASK + Vector((0, 0, 6.35)), "Steel_Mid")
    b.ring("Glow_Cap", 1.15, 0.98, 0.04, FLASK + Vector((0, 0, 6.27)), "Accent")
    # --- казённик: чёрная решётка между задними рёбрами, штуцеры трубок
    b.box("BackGrille", (0.06, 2.3, 2.0), (7.44, GUN_Y, 7.1), "Plastic_Black")
    for dy in (-0.8, 0, 0.8):
        for x in (4.45, 7.05):
            b.cyl("TubeFitting", 0.3, 0.14, (x, GUN_Y + dy, 8.56), "Steel_Light", bevel=0)
    # --- ствол: тёмное отверстие в дульном кольце
    o = b.cyl("MuzzleBore", 0.42, 0.2, (0, 0, 0), "Plastic_Black")
    o.matrix_world = gun_m(-1.68)  # торец дульного кольца
    # фаски на острых авторских брусках, мелочь легче
    bevel_existing(b, ("Strut", "FlaskRib", "BarrelTop", "BarrelBottom", "Rail", "SideCover", "SideShield",
                       "MiniBarrel", "LegRightRib_Cap"), 0.05)
    lighten(b, ("Coil",), 0.5)
    lighten(b, ("LiquidTube",), 0.5)
    lighten(b, ("Wire",), 0.4)


def detail_l2(b):
    # --- тумба: бронеплиты с болтами на прямых гранях
    for k in range(0, 8, 2):
        a = 2 * math.pi * k / 8
        rot = Matrix.Rotation(a, 4, "Z")
        b.box("SkirtPlate", (0.14, 3.4, 0.36), BASE_C + rot @ Vector((OCTO_R + 0.07, 0, 0.42)), "Steel_Mid", rot)
        for y in (-1.5, 1.5):
            b.bolt("Bolt", BASE_C + rot @ Vector((OCTO_R + 0.15, y, 0.42)), axis="X", r=0.08)
    # --- колба: втулки на стойках, раскосы клетки, болты на воротнике
    for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
        p = FLASK + Vector((1.08 * sx, 1.08 * sy, 0))
        for z in (2.45, 5.7):
            b.box("StrutSleeve", (0.78, 0.78, 0.24), p + Vector((0, 0, z)), "Steel_Mid")
    for k in range(4):
        a0 = math.pi / 4 + k * math.pi / 2
        a1 = a0 + math.pi / 2
        r = 1.53
        p0 = FLASK + Vector((r * math.cos(a0), r * math.sin(a0), 2.9))
        p1 = FLASK + Vector((r * math.cos(a1), r * math.sin(a1), 4.9))
        d = p1 - p0
        o = b.cyl("Brace", 0.05, d.length, (0, 0, 0), "Steel_Mid", seg=6, bevel=0)
        o.matrix_world = Matrix.Translation((p0 + p1) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    for k in range(6):
        a = 2 * math.pi * k / 6
        b.bolt("Bolt", FLASK + Vector((1.5 * math.cos(a), 1.5 * math.sin(a), 2.3)))
    # --- ствол: хомуты на катушках, рёбра охлаждения за последней катушкой
    for k in range(6):
        o = b.ring("CoilClamp", 1.07, 0.95, 0.12, (0, 0, 0), "Steel_Light", bevel=0)
        o.matrix_world = gun_m(1.334 * k - 0.4)
    for k in range(4):
        o = b.ring("CoolingFin", 1.62, 1.3, 0.09, (0, 0, 0), "Steel_Mid", bevel=0)
        o.matrix_world = gun_m(7.15 + 0.38 * k)
    # --- гидроцилиндр подъёма: от опорной плиты к стволу под второй катушкой
    p0 = Vector((-1.7, GUN_Y, 2.55))
    p1 = COIL0 + AXIS_DIR * 1.6 - Vector((0, 0, 1.05))
    d = p1 - p0
    rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    for name, r, t0, t1, mat in (("HydBody", 0.26, 0.0, 0.58, "Steel_Light"), ("HydRod", 0.12, 0.5, 1.0, "Panel_Light")):
        o = b.cyl(name, r, d.length * (t1 - t0), (0, 0, 0), mat)
        o.matrix_world = Matrix.Translation(p0 + d * ((t0 + t1) / 2)) @ rot
    for p in (p0, p1):
        b.cyl("HydEye", 0.22, 0.5, p, "Steel_Mid", axis="Y")
    # --- казённик: манометр на боку, болты на N-панелях
    b.cyl("Gauge", 0.3, 0.12, (3.3, 2.62, 7.75), "Steel_Light", axis="Y")
    b.cyl("GaugeFace", 0.23, 0.04, (3.3, 2.69, 7.75), "Panel_Light", axis="Y", bevel=0)
    b.box("GaugeNeedle", (0.03, 0.02, 0.18), (3.3, 2.72, 7.8), "Accent")
    for y in (2.96, -0.06):
        for dx in (-1.1, 1.1):
            for dz in (-0.8, 0.8):
                b.bolt("Bolt", (5.76 + dx, y, 7.1 + dz), axis="Y", r=0.07)


def build(n, mats):
    lv = Lv(n)
    b = Builder(lv, mats)
    load_source(b, keep_extra=n >= 1)  # с L1 возвращаются авторские болты и провода из .blend
    if n >= 1:
        detail_l1(b)
    if n >= 2:
        detail_l2(b)
    return b.col


def bake(col, n):
    """Модификаторы в меш; затенение: гладко, жёсткие рёбра > 35° (у авторских деталей — как в .blend)."""
    dg = bpy.context.evaluated_depsgraph_get()
    tris = 0
    for o in list(col.objects):
        if o.modifiers:
            me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
            o.modifiers.clear()
            o.data = me
        me = o.data
        if o.matrix_world != Matrix():
            me.transform(o.matrix_world)
            o.matrix_world = Matrix()
        if not any(p.use_smooth for p in me.polygons) or n >= 1:
            me.shade_smooth()
            me.set_sharp_from_angle(angle=math.radians(35))
        tris += sum(len(p.vertices) - 2 for p in me.polygons)
    return tris


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)
    for n in range(3):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mats = make_materials(accent=(255, 255, 255))  # в файле акцент белый, как в шаблоне
        col = build(n, mats)
        tris = bake(col, n)
        path = os.path.join(out_dir, f"colba_l{n}.glb")
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True, use_selection=False)
        print(f"L{n}: {len(col.objects)} деталей, {tris} треугольников -> {path}")


if __name__ == "__main__":
    main()
