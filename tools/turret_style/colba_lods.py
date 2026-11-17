"""Образцы стиля: Колба в трёх уровнях детализации (Blender как модуль, `pip install bpy`).

    python tools/turret_style/colba_lods.py Модели/Turrets

Пишет colba_l0.glb, colba_l1.glb, colba_l2.glb. В игру не подключены — это образцы для выбора
уровня детализации (docs/model_style_guide.md).

  L0 — «как сейчас»: раскладка, размеры и цвета деталей сняты с ServerStorage.ColbaTurretTemplate
       (place/game.rbxl). Сами меши лежат на серверах Roblox, в облачной сессии их не скачать,
       поэтому каждая деталь — её габарит простой формой (призма, цилиндр, дуга). Силуэт и
       число деталей те же, грани примерно как у меша из Blender без фасок.
  L1 — +1 ступенька: фаски на всех рёбрах, круглое — 20-24 грани, швы панелей, болты на фланцах,
       решётки, отверстие ствола, шланг от колбы к казённику.
  L2 — +2: слоистая броня с зазорами, двойные фаски, гидроцилиндр подъёма, рёбра охлаждения,
       скобы на шлангах, клетка колбы с раскосами, мелочь на казённике.

Оси Blender: X — вперёд по стволу, Z — вверх, 1 единица = 1 стад, низ подошвы z = -1.6
(как TOWER_Y у турелей). Имена деталей латиницей, роль цвета — по материалу:
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
# Числа — из шаблона (смещения от RootPart, стады). Roblox (dx, dy, dz) -> Blender (dx, -dz, dy).
FLASK = Vector((0.75, 2.25, 0))  # центр модуля колбы по XY
GUN_Y = -1.5                     # ось ствола сбоку от центра
GUN_Z = 4.6                      # высота оси ствола (наклон 8° у шаблона снят)


def octo(r_flat):
    return r_flat / math.cos(math.pi / 8)


def build_base(b):
    lv = b.lv
    # Восьмигранная тумба 10.2 по граням, низ -1.6, верх 0
    if lv.n == 0:
        b.prism("OctoBase", b.ngon(8, octo(5.105), math.pi / 8), 1.6, "Steel_Dark", Matrix.Translation((0.15, 0, -1.6)))
    else:
        # цоколь чуть шире, корпус, скос сверху — три яруса вместо одного бруска
        b.prism("OctoPlinth", b.ngon(8, octo(5.2), math.pi / 8), 0.35, "Steel_Mid", Matrix.Translation((0.15, 0, -1.6)))
        b.prism("OctoBase", b.ngon(8, octo(5.0), math.pi / 8), 1.05, "Steel_Dark", Matrix.Translation((0.15, 0, -1.25)))
        b.prism("OctoTop", b.ngon(8, octo(4.75), math.pi / 8), 0.2, "Steel_Mid", Matrix.Translation((0.15, 0, -0.2)))
        for k in range(8):
            a = 2 * math.pi * k / 8
            rot = Matrix.Rotation(a, 4, "Z")
            c = Vector((0.15, 0, 0))
            if k % 2 == 0:
                # решётка вентиляции на четырёх гранях: чёрная ниша + планки
                b.box("Grille", (0.12, 2.6, 0.62), c + rot @ Vector((4.98, 0, -0.72)), "Plastic_Black", rot, bevel=0)
                slats = 4 if lv.n == 1 else 6
                for s in range(slats):
                    y = -1.1 + 2.2 * s / (slats - 1)
                    b.box("GrilleSlat", (0.1, 0.14, 0.56), c + rot @ Vector((5.0, y, -0.72)), "Steel_Light", rot, bevel=0)
            else:
                # неоновая щель-индикатор на диагональных гранях
                b.box("Glow_Base", (0.08, 1.4, 0.12), c + rot @ Vector((5.02, 0, -0.55)), "Accent", rot, bevel=0)
            if lv.n >= 2:
                # накладные бронепластины с зазором и болтами по углам
                b.box("SkirtPlate", (0.14, 3.2, 0.3), c + rot @ Vector((5.08, 0, -1.25)), "Steel_Mid", rot)
                for y in (-1.45, 1.45):
                    b.bolt("Bolt", c + rot @ Vector((5.17, y, -1.25)), axis="X", r=0.08)
    # Поворотный стол 9.0, 0.6
    if lv.n == 0:
        b.cyl("Turntable", 4.5, 0.6, (0.15, 0, 0.3), "Steel_Dark")
    else:
        b.cyl("Turntable", 4.5, 0.42, (0.15, 0, 0.21), "Steel_Dark", seg=None)
        b.cyl("TurntableTop", 4.2, 0.18, (0.15, 0, 0.51), "Steel_Mid", seg=None)
        b.ring("Glow_Turntable", 4.53, 4.38, 0.06, (0.15, 0, 0.3), "Accent", seg=None, bevel=0)
        nb = 8 if lv.n == 1 else 16
        for k in range(nb):
            a = 2 * math.pi * (k + 0.5) / nb
            b.bolt("Bolt", (0.15 + 3.95 * math.cos(a), 3.95 * math.sin(a), 0.63))


FLASK_PROFILE = [(0, 0.13), (1.1, 0.13), (1.36, 0.45), (1.38, 1.9), (1.3, 3.2), (0.95, 3.85),
                 (0.62, 4.15), (0.6, 4.53), (0, 4.53)]


def build_flask(b):
    lv = b.lv
    fx, fy = FLASK.x, FLASK.y
    # Колба (стекло) и жидкость: профиль бутыли с горлом
    prof = FLASK_PROFILE if lv.n > 0 else [(0, 0.13), (1.3, 0.13), (1.375, 0.6), (1.375, 3.3), (0.75, 4.1), (0.6, 4.53), (0, 4.53)]
    b.lathe("Flask", prof, (fx, fy, 0), "Glass", bevel=0)
    liq = [(r * 0.8, 0.25 + (z - 0.13) * 0.62) for r, z in prof[:5]] + [(0, 0.25 + (prof[4][1] - 0.13) * 0.62)]
    b.lathe("Liquid", liq, (fx, fy, 0), "Liquid", bevel=0)
    # Воротник снизу и крышка сверху
    b.cyl("FlaskCollar", 1.72, 0.6, (fx, fy, 0.38), "Steel_Mid")
    b.cyl("FlaskCap", 1.775, 0.41, (fx, fy, 4.44), "Steel_Light")
    if lv.n >= 1:
        b.cyl("FlaskCapHub", 0.8, 0.22, (fx, fy, 4.75), "Steel_Mid")
        b.ring("Glow_Cap", 1.1, 0.95, 0.05, (fx, fy, 4.66), "Accent", bevel=0)
    if lv.n >= 2:
        for k in range(6):
            a = 2 * math.pi * k / 6
            b.bolt("Bolt", (fx + 1.5 * math.cos(a), fy + 1.5 * math.sin(a), 0.7))
    if lv.n >= 2:
        for k in range(4):  # вентиляционные прорези в крышке
            a = 2 * math.pi * k / 4 + math.pi / 4
            b.box("CapSlot", (0.5, 0.12, 0.06), (fx + 1.3 * math.cos(a), fy + 1.3 * math.sin(a), 4.65), "Plastic_Black",
                  Matrix.Rotation(a, 4, "Z"), bevel=0)
    # Обручи
    for z, h in ((1.10, 0.35), (2.33, 0.30), (3.57, 0.35)):
        if lv.n == 0:
            b.cyl("FlaskRing", 1.46, h, (fx, fy, z), "Steel_Light")
        else:
            r_in = 1.39 if z < 3 else 1.31
            b.ring("FlaskRing", 1.5, r_in, h, (fx, fy, z), "Steel_Light")
    # Рёбра клетки (тонкие) и стойки (толстые)
    for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
        if lv.n == 0:
            b.box("FlaskRib", (0.28, 0.28, 2.64), (fx + 0.97 * sx, fy + 0.97 * sy, 2.33), "Steel_Dark")
        else:
            b.cyl("FlaskRib", 0.14, 2.64, (fx + 0.99 * sx, fy + 0.99 * sy, 2.33), "Steel_Dark")
        if lv.n < 2:
            b.box("Strut", (0.66, 0.66, 3.79), (fx + 1.08 * sx * 1.4, fy + 1.08 * sy * 1.4, 2.49), "Steel_Light",
                  Matrix.Rotation(math.pi / 4, 4, "Z"))
        else:
            # стойка: швеллер + втулки
            p = Vector((fx + 1.51 * sx, fy + 1.51 * sy, 0))
            rot = Matrix.Rotation(math.pi / 4, 4, "Z")
            b.box("Strut", (0.5, 0.5, 3.79), p + Vector((0, 0, 2.49)), "Steel_Light", rot)
            b.box("StrutInset", (0.54, 0.2, 2.6), p + Vector((0, 0, 2.49)), "Steel_Dark", rot, bevel=0.03)
            for z in (0.95, 4.05):
                b.box("StrutSleeve", (0.62, 0.62, 0.26), p + Vector((0, 0, z)), "Steel_Mid", rot)
    if lv.n >= 2:
        # раскосы клетки между стойками
        for k in range(4):
            a0 = math.pi / 4 + k * math.pi / 2
            a1 = a0 + math.pi / 2
            p0 = Vector((fx + 1.62 * math.cos(a0), fy + 1.62 * math.sin(a0), 1.2))
            p1 = Vector((fx + 1.62 * math.cos(a1), fy + 1.62 * math.sin(a1), 3.5))
            mid = (p0 + p1) / 2
            d = p1 - p0
            rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
            o = b.cyl("Brace", 0.06, d.length, (0, 0, 0), "Steel_Mid", seg=6, bevel=0)
            o.matrix_world = Matrix.Translation(mid) @ rot


def build_arm(b):
    lv = b.lv
    y = GUN_Y
    # Опорная плита
    b.box("ArmBasePlate", (4.24, 2.64, 0.3), (0.31, y, 0.75), "Steel_Mid")
    # Лебединая шея: дуги от плиты назад-вверх к казённику (центр дуги над плитой)
    c = (1.71, 5.45)
    if lv.n == 0:
        b.arc_band("LegRib", c, 6.29, 5.6, 200, 265, y - 1.2, y - 0.8, "Steel_Dark")
        b.arc_band("LegRib", c, 6.29, 5.6, 200, 265, y + 0.8, y + 1.2, "Steel_Dark")
        b.arc_band("ArmHyd", c, 5.6, 4.6, 205, 262, y - 0.8, y + 0.8, "Steel_Light")
    else:
        b.arc_band("LegRib", c, 6.3, 5.55, 200, 265, y - 1.22, y - 0.82, "Steel_Dark")
        b.arc_band("LegRib", c, 6.3, 5.55, 200, 265, y + 0.82, y + 1.22, "Steel_Dark")
        b.arc_band("ArmHyd", c, 5.6, 4.75, 205, 262, y - 0.78, y + 0.78, "Steel_Mid")
        b.arc_band("ArmCore", c, 5.45, 4.9, 207, 260, y - 0.84, y + 0.84, "Plastic_Black", bevel=0)
        # пятки дуг на плите
        b.box("ArmFoot", (1.3, 2.7, 0.4), (1.5, y, 1.05), "Steel_Dark")
        for dx in (-0.4, 0.4):
            for dy in (-1.05, 1.05):
                b.bolt("Bolt", (1.5 + dx, y + dy, 1.28))
    if lv.n >= 2:
        # гидроцилиндр подъёма: корпус от плиты, шток к стволу
        p0 = Vector((2.0, y, 1.0))
        p1 = Vector((3.4, y, GUN_Z - 0.95))
        d = p1 - p0
        rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        for name, r, t0, t1, mat in (("HydBody", 0.3, 0.0, 0.6, "Steel_Light"), ("HydRod", 0.14, 0.55, 1.0, "Panel_Light")):
            mid = p0 + d * ((t0 + t1) / 2)
            o = b.cyl(name, r, d.length * (t1 - t0), (0, 0, 0), mat)
            o.matrix_world = Matrix.Translation(mid) @ rot
        for p in (p0, p1):
            b.cyl("HydEye", 0.24, 0.5, p, "Steel_Mid", axis="Y")


def build_gun(b):
    lv = b.lv
    y, z = GUN_Y, GUN_Z
    # --- казённик
    if lv.n == 0:
        b.box("Breech", (3.4, 2.6, 2.8), (-5.59, y, z), "Steel_Dark")
        b.box("BreechExtension", (4.81, 2.24, 2.68), (-3.91, y, z), "Steel_Dark")
    else:
        b.box("Breech", (3.4, 2.5, 2.7), (-5.59, y, z), "Steel_Dark")
        b.box("BreechExtension", (4.6, 2.2, 2.5), (-3.91, y, z), "Steel_Dark")
        b.box("BreechTop", (2.9, 1.9, 0.18), (-5.59, y, z + 1.4), "Steel_Mid")  # верхняя крышка-панель
        b.box("BreechSeam", (0.08, 2.54, 2.4), (-4.3, y, z), "Plastic_Black", bevel=0)  # шов панелей
    if lv.n >= 2:
        # бронеплиты по бокам слоем поверх корпуса + решётка сзади + манометр
        for s in (-1, 1):
            b.box("BreechArmor", (1.6, 0.16, 1.2), (-3.4, y + s * 1.18, z - 0.55), "Steel_Mid")
            for dx in (-0.6, 0.6):
                b.bolt("Bolt", (-3.4 + dx, y + s * 1.27, z - 0.12), axis="Y", r=0.07)
        b.cyl("Gauge", 0.32, 0.12, (-4.6, y + 1.32, z + 0.75), "Steel_Light", axis="Y")
        b.cyl("GaugeFace", 0.24, 0.04, (-4.6, y + 1.39, z + 0.75), "Panel_Light", axis="Y", bevel=0)
        b.box("GaugeNeedle", (0.03, 0.02, 0.2), (-4.6, y + 1.42, z + 0.8), "Accent", bevel=0)
    # N-панели по бокам казённика, полоса и индикаторы (акцент)
    for s in (-1, 1):
        b.box("NPlate", (2.6, 0.18, 2.0), (-5.59, y + s * 1.39, z), "Steel_Mid")
        b.box("Glow_NStrip", (2.2, 0.08, 0.15), (-5.59, y + s * 1.49, z), "Accent", bevel=0)
        for dz in (0.3, -0.3):
            b.box("Glow_Indicator", (0.35, 0.06, 0.18), (-6.11 + (0.9 if lv.n else 0), y + s * 1.5, z + dz + (0.35 if lv.n else 0)),
                  "Accent", bevel=0)
        if lv.n >= 2:
            for dx in (-1.1, 1.1):
                for dz in (-0.8, 0.8):
                    b.bolt("Bolt", (-5.59 + dx, y + s * 1.49, z + dz), axis="Y", r=0.07)
    # задняя решётка
    for k, dy in enumerate((-0.8, 0, 0.8)):
        if lv.n == 0:
            b.box("NRib", (0.4, 0.4, 2.2), (-7.42, y + dy, z), "Steel_Mid")
        else:
            b.box("NRib", (0.34, 0.3, 2.2), (-7.36, y + dy, z), "Steel_Mid")
    if lv.n >= 1:
        b.box("BackGrille", (0.1, 2.1, 2.1), (-7.3, y, z), "Plastic_Black", bevel=0)
    # трубки жидкости дугой над казёнником (акцент)
    for dy in (-0.8, 0, 0.8):
        pts = [(-7.1, y + dy, z + 1.2), (-6.8, y + dy, z + 2.0), (-5.6, y + dy, z + 2.1), (-4.4, y + dy, z + 2.0), (-4.05, y + dy, z + 1.2)]
        if lv.n == 0:
            pts = [pts[0], (-6.6, y + dy, z + 2.05), (-4.6, y + dy, z + 2.05), pts[-1]]
        b.tube("LiquidTube", pts, 0.22 if lv.n else 0.25, "Accent", seg=(6, 8, 10)[lv.n])
        if lv.n >= 1:
            for x in (-7.1, -4.05):
                b.cyl("TubeFitting", 0.3, 0.22, (x, y + dy, z + 1.33), "Steel_Light")
    # крышки казённика
    for s in (-1, 1):
        b.box("BreechCover", (3.2, 0.28, 1.4), (-4.19, y + s * 1.14, z + 0.59 if lv.n == 0 else z + 0.55), "Steel_Dark")

    # --- рельсовый ствол
    xc = 1.83
    for dz in (0.57, -0.57):
        b.cyl("Barrel", 0.63, 8.27, (xc, y, z + dz), "Steel_Dark", axis="X")
    for s in (-1, 1):
        b.box("Rail", (8.35, 0.14, 1.92), (1.75, y + s * 0.7, z), "Steel_Light")
    # гильзы
    if lv.n == 0:
        b.prism("Sleeve", b.ngon(8, 1.42, math.pi / 8), 3.52, "Steel_Dark",
                Matrix.Translation((-2.31 - 1.76, y, z)) @ AXIS["X"])
        b.prism("Sleeve", b.ngon(8, 1.2, math.pi / 8), 2.78, "Steel_Dark",
                Matrix.Translation((0.29 - 1.39, y, z)) @ AXIS["X"])
    else:
        b.lathe("Sleeve", [(0, 0), (1.3, 0), (1.45, 0.25), (1.45, 3.27), (1.3, 3.52), (0, 3.52)],
                (-2.31 - 1.76, y, z), "Steel_Dark", axis="X")
        b.lathe("Sleeve", [(0, 0), (1.1, 0), (1.22, 0.2), (1.22, 2.58), (1.1, 2.78), (0, 2.78)],
                (0.29 - 1.39, y, z), "Steel_Dark", axis="X")
    if lv.n >= 2:
        # рёбра охлаждения на большой гильзе
        for k in range(5):
            b.ring("CoolingFin", 1.62, 1.4, 0.1, (-3.6 + 0.6 * k, y, z), "Steel_Mid", axis="X", bevel=0)
    # катушки (акцент)
    for k in range(6):
        x = -2.21 + 1.32 * k
        if lv.n == 0:
            b.cyl("Coil", 0.985, 0.71, (x, y, z), "Accent", axis="X")
        else:
            b.ring("Coil", 0.99, 0.72, 0.62, (x, y, z), "Accent", axis="X")
            if lv.n >= 2:
                b.ring("CoilClamp", 1.06, 0.95, 0.14, (x - 0.38, y, z), "Steel_Light", axis="X", bevel=0)
    # дульный узел
    if lv.n == 0:
        b.cyl("MuzzleRing", 1.16, 1.67, (5.28, y, z), "Steel_Dark", axis="X")
    else:
        b.ring("MuzzleRing", 1.16, 0.55, 1.67, (5.28, y, z), "Steel_Dark", axis="X")
        b.cyl("MuzzleBore", 0.56, 1.5, (5.3, y, z), "Plastic_Black", axis="X", bevel=0)
    for s in (-1, 1):
        b.box("SideShield", (2.94, 0.28, 0.92), (5.91, y + s * 0.56, z - 1.16), "Steel_Mid")
        b.box("SideCover", (2.53, 0.21, 0.73), (5.2, y + s * 0.89, z - 0.83), "Steel_Mid")
    for name, dy, dz in (("MiniBarrel", 0, 0.64), ("MiniBarrel", -0.82, -0.3), ("MiniBarrel", 0.82, -0.3)):
        if lv.n == 0:
            b.box(name, (2.14, 0.33, 0.51), (6.48, y + dy, z + dz), "Steel_Dark")
        else:
            b.ring(name, 0.22, 0.12, 2.14, (6.48, y + dy, z + dz), "Steel_Dark", axis="X")
    for k in range(3):
        b.box("Glow_Vent", (0.61, 0.29, 0.2) if lv.n == 0 else (0.5, 0.26, 0.06), (5.71 + 0.565 * k, y, z + 0.95),
              "Accent", bevel=0)
    if lv.n >= 1:
        b.box("VentPlate", (2.0, 0.6, 0.12), (6.28, y, z + 0.88), "Plastic_Black", bevel=0)


def build_hoses(b):
    lv = b.lv
    if lv.n == 0:
        return
    fx, fy = FLASK.x, FLASK.y
    y, z = GUN_Y, GUN_Z
    # шланг подачи: из воротника колбы к казённику
    pts = [(fx - 1.2, fy - 1.0, 0.55), (fx - 2.6, fy - 1.8, 0.9), (-4.2, y + 1.4, 1.6), (-5.2, y + 1.3, z - 1.6),
           (-5.6, y + 1.2, z - 1.25)]
    b.tube("Hose", pts, 0.16, "Plastic_Black")
    if lv.n >= 2:
        pts2 = [(fx - 0.6, fy - 1.4, 0.55), (fx - 1.6, fy - 2.6, 0.85), (-3.0, y + 1.5, 1.2), (-4.6, y + 1.3, z - 1.8),
                (-5.0, y + 1.2, z - 1.25)]
        b.tube("Hose", pts2, 0.12, "Plastic_Black")
        for p in ((fx - 2.6, fy - 1.8, 0.9), (-4.2, y + 1.4, 1.6)):
            b.ring("HoseClamp", 0.24, 0.15, 0.14, p, "Steel_Light", axis="Y", bevel=0)


def build(n, mats):
    lv = Lv(n)
    b = Builder(lv, mats)
    build_base(b)
    build_flask(b)
    build_arm(b)
    build_gun(b)
    build_hoses(b)
    return b.col


def bake(col, n):
    """Модификаторы в меш и затенение: L0 — плоские грани, L1/L2 — гладкие с острыми углами > 35°."""
    dg = bpy.context.evaluated_depsgraph_get()
    tris = 0
    for o in list(col.objects):
        if o.modifiers:
            me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
            o.modifiers.clear()
            o.data = me
        me = o.data
        if n == 0:
            for p in me.polygons:
                p.use_smooth = False
        else:
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
