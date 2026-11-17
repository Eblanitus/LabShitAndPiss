"""Образцы стиля: Колба в трёх уровнях детализации (Blender как модуль, `pip install bpy`).

    python tools/turret_style/colba_lods.py Модели/Turrets

Пишет colba_l0.glb, colba_l1.glb, colba_l2.glb. В игру не подключены — это образцы для выбора
уровня детализации (docs/model_style_guide.md).

  L0 — как в игре: авторская модель Модели/Turrets/source/colba2.blend (копия «КОЛБа 2.blend»)
       без того, чего нет в ServerStorage.ColbaTurretTemplate (воронка FlaskFiller, болты
       DetailBolts_Merged, провода Wire_Struts), цвета деталей — как в шаблоне, плюс жидкость.
  L1 — +1 ступенька формой: тумба со скосом и наклонными стенками, бутыль в литой чаше с тремя
       лапами и куполом, А-стойка с гидроцилиндром, гранёный казённик, восьмигранный кожух ствола
       с раструбом и дульным тормозом. Катушки, трубки, N-панели, рёбра, мини-стволы — авторские.
  L2 — +2: контрфорсы тумбы, бронещитки казённика, корона колбы, перемычка стойки, хребет ствола.

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


def load_source(b, skip=()):
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
        if o.name.startswith(NOT_IN_GAME + tuple(skip)):
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
    flask = b.col.objects.get("Flask")
    if flask is None:
        return
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


# Детали, которые L1 заменяет своими формами. Остаются: катушки, трубки жидкости, N-панели с полосой
# и индикаторами, задние рёбра, мини-стволы, опорная плита — то, по чему Колбу узнают.
REPLACED = ("OctoBase", "Turntable", "Колба", "FlaskCap", "FlaskCollar", "FlaskRing", "FlaskRib", "Strut",
            "Leg", "ArmHydLower", "BreechNew", "BreechExtension", "Barrel", "Rail", "MuzzleRing", "SideCover",
            "SideShield", "Vent")


def loft(b, name, rings, mat, caps=True):
    """Тело по сечениям: rings — списки точек (Vector) одинаковой длины, по порядку вдоль тела."""
    n = len(rings[0])
    verts = [v for r in rings for v in r]
    faces = []
    for k in range(len(rings) - 1):
        a0, a1 = k * n, (k + 1) * n
        faces += [[a0 + i, a0 + (i + 1) % n, a1 + (i + 1) % n, a1 + i] for i in range(n)]
    if caps:
        faces.append(list(range(n))[::-1])
        faces.append(list(range((len(rings) - 1) * n, len(rings) * n)))
    return b.obj(name, verts, faces, mat, bevel=0)


def chamf(w, h, ct, cb):
    """Прямоугольник w x h с фасками: сверху ct, снизу cb (точки (u, v) против часовой)."""
    return [(-w / 2 + cb, -h / 2), (w / 2 - cb, -h / 2), (w / 2, -h / 2 + cb), (w / 2, h / 2 - ct),
            (w / 2 - ct, h / 2), (-w / 2 + ct, h / 2), (-w / 2, h / 2 - ct), (-w / 2, -h / 2 + cb)]


def octo_poly(r_flat):
    R = r_flat / math.cos(math.pi / 8)
    return [(R * math.cos(math.pi / 8 + i * math.pi / 4), R * math.sin(math.pi / 8 + i * math.pi / 4)) for i in range(8)]


def circle(r, n):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def ring_z(c, poly, z, k=1.0):
    return [Vector((c.x + u * k, c.y + v * k, z)) for u, v in poly]


def ring_x(x, y0, z0, poly, k=1.0):
    return [Vector((x, y0 + u * k, z0 + v * k)) for u, v in poly]


SIDE = Vector((0, 1, 0))
UP = Vector((-math.sin(PITCH), 0, math.cos(PITCH)))


def gun_pt(t, u, v):
    return COIL0 + AXIS_DIR * t + SIDE * u + UP * v


def ring_gun(t, poly, k=1.0):
    return [gun_pt(t, u * k, v * k) for u, v in poly]


def lathe_z(b, name, c, prof, mat, seg=32):
    """Тело вращения вокруг вертикали через c: prof — [(r, z)]."""
    return loft(b, name, [ring_z(c, circle(max(r, 1e-4), seg), z) for r, z in prof], mat)


def sweep_arm(b, name, c, ang, path, w, th, mat):
    """Лапа опоры колбы: брусок w x th по кривой path [(r, z)] в вертикальной плоскости под углом ang."""
    er = Vector((math.cos(ang), math.sin(ang), 0))
    et = Vector((-math.sin(ang), math.cos(ang), 0))
    rings = []
    for i, (r, z) in enumerate(path):
        r0, z0 = path[max(0, i - 1)]
        r1, z1 = path[min(len(path) - 1, i + 1)]
        L = math.hypot(r1 - r0, z1 - z0)
        nr, nz = (z1 - z0) / L, -(r1 - r0) / L  # нормаль наружу
        base = c + er * r + Vector((0, 0, z))
        nvec = er * nr + Vector((0, 0, nz))
        rings.append([base + nvec * (dn * th / 2) + et * (dt * w / 2) for dn, dt in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    return loft(b, name, rings, mat)


def plate_xz(b, name, poly, y0, y1, mat):
    """Пластина: многоугольник в плоскости XZ, толщина по Y от y0 до y1."""
    return loft(b, name, [[Vector((x, y, z)) for x, z in poly] for y in (y0, y1)], mat)


def slot_gun(b, name, t, u, v, dt, du, dv, mat):
    """Брусок на стволе: центр (t, u, v), размеры вдоль ствола dt, вбок du, вверх dv."""
    q = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    rings = [[gun_pt(t + a * dt / 2, u + s * du / 2, v + c * dv / 2) for a, c in q] for s in (-1, 1)]
    return loft(b, name, rings, mat)


def form_base(b):
    # тумба: цоколь, скос, наклонные стенки к столу — вместо прямой восьмигранной плиты
    secs = [(5.3, 0.0), (5.3, 0.22), (5.12, 0.4), (4.9, 1.32), (4.7, 1.6)]
    loft(b, "Base", [ring_z(BASE_C, octo_poly(r), z) for r, z in secs], "Steel_Dark")
    # стол: барабан со скошенными кромками и приподнятый центр
    secs = [(4.3, 1.6), (4.6, 1.74), (4.6, 1.98), (4.32, 2.2)]
    loft(b, "Turntable", [ring_z(BASE_C, circle(r, 48), z) for r, z in secs], "Steel_Mid")
    lathe_z(b, "TurntableHub", BASE_C, [(0, 2.18), (3.35, 2.18), (3.35, 2.26), (3.15, 2.34), (0, 2.34)],
            "Steel_Dark", seg=40)


def form_flask(b):
    # стекло — бутыль с плечами и горлом, жидкость повторяет форму
    lathe_z(b, "Flask", FLASK, [(0, 1.78), (1.05, 1.78), (1.3, 1.95), (1.4, 2.3), (1.4, 4.5), (1.25, 5.0),
                                (0.85, 5.42), (0.62, 5.6), (0.6, 6.05), (0, 6.05)], "Glass")
    lathe_z(b, "Liquid", FLASK, [(0, 1.86), (1.0, 1.86), (1.22, 2.0), (1.31, 2.3), (1.31, 4.55), (0, 4.55)],
            "Liquid", seg=28)
    # литая чаша снизу, купол-крышка сверху
    lathe_z(b, "FlaskSocket", FLASK, [(0, 1.68), (1.98, 1.68), (1.98, 1.9), (1.66, 2.42), (1.36, 2.46), (0, 2.46)],
            "Steel_Mid")
    lathe_z(b, "FlaskCap", FLASK, [(0, 5.82), (1.22, 5.82), (1.22, 5.96), (0.98, 6.26), (0.6, 6.42), (0, 6.42)],
            "Steel_Light")
    # три изогнутые лапы по контуру бутыли от чаши к крышке и пояс на плечах
    for k in range(3):
        a = math.radians(50 + 120 * k)
        sweep_arm(b, "FlaskArm", FLASK, a, [(1.85, 2.0), (1.62, 2.5), (1.55, 3.0), (1.55, 4.4), (1.42, 5.05),
                                            (1.2, 5.88)], 0.66, 0.3, "Steel_Light")
    b.ring("FlaskBand", 1.66, 1.42, 0.2, FLASK + Vector((0, 0, 4.48)), "Steel_Mid", seg=32, bevel=0)


ARM_POLY = [(-1.9, 2.5), (1.9, 2.5), (5.4, 5.75), (5.4, 6.3), (3.5, 6.3), (-0.5, 3.25)]
ARM_INNER = [(-0.9, 2.75), (1.4, 2.75), (4.5, 5.65), (3.6, 5.95), (-0.2, 3.25)]


def form_arm(b):
    # А-стойка: две фигурные щеки с утопленной панелью и гидроцилиндр между ними
    for y0, y1, face, d in ((0.25, 0.65, 0.25, -0.04), (2.25, 2.65, 2.65, 0.04)):
        plate_xz(b, "ArmCheek", ARM_POLY, y0, y1, "Steel_Dark")
        plate_xz(b, "ArmCheekPanel", ARM_INNER, face, face + d, "Steel_Mid")
    p0 = Vector((0.0, GUN_Y, 2.6))
    p1 = Vector((3.7, GUN_Y, 5.7))
    d = p1 - p0
    rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    for name, r, t0, t1, mat in (("HydBody", 0.34, 0.0, 0.6, "Steel_Light"), ("HydRod", 0.15, 0.55, 1.0, "Panel_Light")):
        o = b.cyl(name, r, d.length * (t1 - t0), (0, 0, 0), mat, seg=20, bevel=0)
        o.matrix_world = Matrix.Translation(p0 + d * ((t0 + t1) / 2)) @ rot
    b.cyl("HydEye", 0.3, 1.9, p0 + Vector((0, 0, 0.05)), "Steel_Mid", axis="Y", seg=20, bevel=0)


def form_breech(b):
    # казённик: гранёный блок с крупными скосами сверху, сужается назад; перед — тоньше, к стволу
    prof = chamf(2.6, 2.8, 0.62, 0.32)
    loft(b, "Breech", [ring_x(4.06, GUN_Y, 7.1, prof), ring_x(6.95, GUN_Y, 7.1, prof),
                       ring_x(7.46, GUN_Y, 7.1, prof, 0.84)], "Steel_Dark")
    prof = chamf(2.24, 2.66, 0.55, 0.38)
    loft(b, "BreechFront", [ring_x(1.6, GUN_Y, 6.75, prof, 0.82), ring_x(2.45, GUN_Y, 6.85, prof),
                            ring_x(4.2, GUN_Y, 6.95, prof)], "Steel_Dark")
    b.box("BackGrille", (0.06, 2.0, 1.9), (7.5, GUN_Y, 7.1), "Plastic_Black", bevel=0)


def form_barrel(b):
    # кожух ствола (восьмигранник внутри катушек), раструб гильзы к казённику, дульный тормоз
    oc, big = octo_poly(0.7), octo_poly(1.3)
    loft(b, "Shroud", [ring_gun(-0.95, oc), ring_gun(4.7, oc), ring_gun(5.25, big), ring_gun(8.4, big),
                       ring_gun(8.6, big, 0.9)], "Steel_Dark")
    for t in (5.25, 6.0, 6.75, 7.5):  # рёбра раструба
        loft(b, "SleeveRib", [ring_gun(t, octo_poly(1.42)), ring_gun(t + 0.22, octo_poly(1.42))], "Steel_Mid")
    loft(b, "MuzzleBrake", [ring_gun(-0.8, octo_poly(0.86)), ring_gun(-1.0, octo_poly(1.06)),
                            ring_gun(-1.85, octo_poly(1.06)), ring_gun(-2.08, octo_poly(1.16)),
                            ring_gun(-2.12, octo_poly(1.0))], "Steel_Mid")
    for t in (-1.2, -1.58):  # прорези тормоза по бокам и светящиеся отдушины сверху
        for s in (-1, 1):
            slot_gun(b, "BrakeSlot", t, s * 1.08, 0, 0.22, 0.05, 0.84, "Plastic_Black")
        slot_gun(b, "Glow_BrakeVent", t, 0, 1.08, 0.2, 0.6, 0.04, "Accent")
    loft(b, "MuzzleBore", [ring_gun(-2.0, octo_poly(0.45)), ring_gun(-2.15, octo_poly(0.45))], "Plastic_Black")


def detail_l1(b):
    form_base(b)
    form_flask(b)
    form_arm(b)
    form_breech(b)
    form_barrel(b)


def detail_l2(b):
    # контрфорсы на косых гранях тумбы
    for k in range(1, 8, 2):
        a = math.pi / 4 * k
        er = Vector((math.cos(a), math.sin(a), 0))
        et = Vector((-math.sin(a), math.cos(a), 0))
        prof = [(4.6, 0.0), (5.95, 0.0), (5.95, 0.22), (4.75, 1.5)]  # клин от цоколя к стенке
        loft(b, "Buttress", [[BASE_C + er * r + et * w + Vector((0, 0, z)) for r, z in prof] for w in (-0.75, 0.75)],
             "Steel_Mid")
    # бронещитки по бокам казённика, слоем поверх корпуса
    shield = [(1.9, 5.85), (4.1, 5.85), (4.4, 6.25), (4.4, 7.4), (3.9, 7.75), (2.3, 7.75), (1.9, 7.3)]
    plate_xz(b, "BreechShield", shield, 0.12, 0.3, "Steel_Mid")
    plate_xz(b, "BreechShield", shield, 2.6, 2.78, "Steel_Mid")
    # корона на крышке колбы связывает лапы, навершие
    b.ring("FlaskCrown", 1.42, 1.12, 0.26, FLASK + Vector((0, 0, 5.86)), "Steel_Mid", seg=32, bevel=0)
    lathe_z(b, "FlaskCapTop", FLASK, [(0, 6.4), (0.42, 6.4), (0.42, 6.62), (0.3, 6.72), (0, 6.72)], "Steel_Mid", seg=16)
    # перемычка между щеками стойки
    o = b.box("ArmBridge", (0.7, 2.4, 0.5), (0, 0, 0), "Steel_Mid", bevel=0)
    o.matrix_world = Matrix.Translation((2.9, GUN_Y, 4.9)) @ Matrix.Rotation(math.radians(-43), 4, "Y")
    # хребет над кожухом от тормоза до раструба
    loft(b, "ShroudSpine", [ring_gun(t, [(u, v + 1.0) for u, v in chamf(0.36, 0.3, 0.1, 0.0)]) for t in (-0.75, 4.9)],
         "Steel_Mid")


def build(n, mats):
    lv = Lv(n)
    b = Builder(lv, mats)
    load_source(b, skip=REPLACED if n >= 1 else ())  # с L1 основные формы строятся заново
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
