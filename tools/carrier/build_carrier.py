"""Путь 2: дрон-носильщик кодом из гранёных деталей, как жуки (tools/beetles/beetlegen.py).
Силуэт — по модели Hunyuan3D (Модели/носилщик.fbx): гусеничное шасси, кабина-шестигранник,
грабли спереди, две мачты сзади. Детальнее жуков: фаски на корпусе, протектор гусениц, катки.

    python tools/carrier/build_carrier.py Модели/Carrier/carrier_parts.glb

Оси как в Roblox: Y вверх, перед -Z (как у CarrierRig), правый борт +X, пол — y = 0, 1 единица = 1 стад,
длина ~2.4 стада. Имена деталей латиницей, роль цвета — по началу имени (palette.py):
Body*, Chassis, Lid, SidePanel_*, Grille, Vent*, Track_*, Wheel_*, Hub_*, Bogie_*, Rake, Tooth_*,
Pivot_*, Arm_*, Mast_*, MastTip_*, Glow_*, Edge_*. Колёса (Wheel_*) — отдельные детали: их можно крутить.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "beetles"))
sys.path.insert(0, HERE)
from beetlegen import Mesh, Model, loft  # noqa: E402
import palette  # noqa: E402


# ---------------------------------------------------------------- примитивы

def oriented(m):
    """Замкнутая деталь: нормали наружу (знак объёма), иначе Roblox срежет грани."""
    vol = sum(np.dot(a, np.cross(b, c)) for a, b, c in m.v)
    if vol < 0:
        m.v = [(a, c, b) for a, b, c in m.v]
    return m


def offset_poly(poly, d):
    """Выпуклый многоугольник (2D), сдвинутый внутрь на d."""
    p = [np.asarray(q, float) for q in poly]
    n = len(p)
    area = sum(p[i][0] * p[(i + 1) % n][1] - p[(i + 1) % n][0] * p[i][1] for i in range(n))
    s = 1 if area > 0 else -1
    out = []
    for i in range(n):
        a, b, c = p[i - 1], p[i], p[(i + 1) % n]
        e1, e2 = (b - a) / np.linalg.norm(b - a), (c - b) / np.linalg.norm(c - b)
        n1, n2 = s * np.array([-e1[1], e1[0]]), s * np.array([-e2[1], e2[0]])  # внутренние нормали
        bis = n1 + n2
        bis /= np.linalg.norm(bis)
        out.append(b + bis * d / max(0.2, np.dot(bis, n1)))
    return out


def prism(poly, axis, t0, t1, bevel=0.0):
    """Призма: многоугольник poly в плоскости поперёк оси axis ('x', 'y', 'z'), от t0 до t1,
    с фаской bevel по рёбрам торцов. Для 'x' точки poly — (z, y), для 'y' — (x, z), для 'z' — (x, y)."""
    def p3(q, t):
        a, b = q
        return np.array({"x": (t, b, a), "y": (a, t, b), "z": (a, b, t)}[axis], float)
    rings = []
    if bevel > 0:
        inner = offset_poly(poly, bevel)
        rings = [[p3(q, t0) for q in inner], [p3(q, t0 + bevel) for q in poly],
                 [p3(q, t1 - bevel) for q in poly], [p3(q, t1) for q in inner]]
    else:
        rings = [[p3(q, t0) for q in poly], [p3(q, t1) for q in poly]]
    return oriented(loft(rings))


def box(c, size, bevel=0.0):
    """Брусок с центром c и размером size; фаска по рёбрам вдоль X и торцам по Z."""
    cx, cy, cz = c
    sx, sy, sz = size
    b = min(bevel, sx / 3, sy / 3, sz / 3) if min(size) >= 0.12 else 0.0  # на мелочи фаска не видна
    x0, x1, y0, y1 = cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2
    if b > 0:
        poly = [(x0 + b, y0), (x1 - b, y0), (x1, y0 + b), (x1, y1 - b), (x1 - b, y1), (x0 + b, y1), (x0, y1 - b),
                (x0, y0 + b)]
    else:
        poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return prism(poly, "z", cz - sz / 2, cz + sz / 2, b)


def cylinder(c, r, axis, length, n=10, bevel=0.0, rot=None):
    rot = math.pi / n if rot is None else rot
    poly = [(r * math.cos(rot + 2 * math.pi * i / n), r * math.sin(rot + 2 * math.pi * i / n)) for i in range(n)]
    cx, cy, cz = c
    if axis == "x":
        poly = [(cz + a, cy + b) for a, b in poly]
        return prism(poly, "x", cx - length / 2, cx + length / 2, bevel)
    if axis == "z":
        poly = [(cx + a, cy + b) for a, b in poly]
        return prism(poly, "z", cz - length / 2, cz + length / 2, bevel)
    poly = [(cx + a, cz + b) for a, b in poly]
    return prism(poly, "y", cy - length / 2, cy + length / 2, bevel)


def hook(points, radii, n=4):
    """Гранёный изогнутый зуб по ломаной (тонкий конец — точка)."""
    pts = [np.asarray(p, float) for p in points]
    rings = []
    for i, p in enumerate(pts[:-1]):
        d = pts[i + 1] - pts[i - 1] if i else pts[1] - pts[0]
        d /= np.linalg.norm(d)
        side = np.array([1.0, 0, 0])
        up = np.cross(d, side)
        rx, ry = radii[i]
        rings.append([p + side * rx * math.cos(math.pi / 4 + k * math.pi / 2 * 4 / n)
                      + up * ry * math.sin(math.pi / 4 + k * math.pi / 2 * 4 / n) for k in range(n)])
    m = loft(rings, cap_start=True, cap_end=False)
    tip = pts[-1]
    last = rings[-1]
    for k in range(n):
        m.tri(last[k], last[(k + 1) % n], tip)
    return oriented(m)


def mirror_x(m):
    return m.mirrored_x()


def join(*ms):
    out = Mesh()
    for m in ms:
        out.extend(m)
    return out


# ---------------------------------------------------------------- размеры (стады)

W_CAB = 0.66            # полуширина кабины
TRACK_X = (0.43, 0.89)  # гусеница по X (правый борт; левый — зеркало)
TRACK_R = 0.30          # радиус ленивца/ведущего колеса по ленте
TRACK_Z = (-0.66, 0.72) # центры переднего и заднего колеса
TRACK_Y = TRACK_R + 0.0 # центр колёс над полом
BELT = 0.07             # толщина ленты

# борт кабины в профиль (z, y), перед — слева
CAB = [(-0.58, 0.70), (-0.84, 0.95), (-0.84, 1.20), (-0.52, 1.62), (0.92, 1.62), (1.00, 1.52), (1.00, 0.70)]


# ---------------------------------------------------------------- узлы

def track_path():
    """Точки по ленте (z, y) против часовой, если смотреть с +X: низ — вперёд к -Z ... — и нормали наружу."""
    z0, z1 = TRACK_Z
    r = TRACK_R
    pts = []
    arc = 7
    straight = 4
    # низ: от заднего колеса к переднему
    for i in range(straight):
        t = i / straight
        pts.append(((z1 + (z0 - z1) * t, TRACK_Y - r), (0, -1)))
    # передний полукруг (снизу вверх через перед)
    for i in range(arc):
        a = -math.pi / 2 - math.pi * i / arc
        pts.append(((z0 + r * math.cos(a), TRACK_Y + r * math.sin(a)), (math.cos(a), math.sin(a))))
    # верх: вперёд -> назад, лента чуть провисает к середине
    for i in range(straight):
        t = i / straight
        sag = 0.03 * math.sin(math.pi * t)
        pts.append(((z0 + (z1 - z0) * t, TRACK_Y + r - sag), (0, 1)))
    # задний полукруг
    for i in range(arc):
        a = math.pi / 2 - math.pi * i / arc
        pts.append(((z1 + r * math.cos(a), TRACK_Y + r * math.sin(a)), (math.cos(a), math.sin(a))))
    return pts


def track_mesh():
    x0, x1 = TRACK_X
    pts = track_path()
    rings = []
    for (z, y), (nz, ny) in pts:
        o = np.array([0, y, z])
        n = np.array([0, ny, nz])
        rings.append([np.array([x0, 0, 0]) + o, np.array([x1, 0, 0]) + o,
                      np.array([x1, 0, 0]) + o - n * BELT, np.array([x0, 0, 0]) + o - n * BELT])
    rings.append(rings[0])
    belt = oriented(loft(rings, cap_start=False, cap_end=False))
    # грунтозацепы: через точку ленты, на всю ширину
    lugs = Mesh()
    for i in range(0, len(pts), 2):
        (z, y), _ = pts[i]
        (z2, y2), _ = pts[(i + 1) % len(pts)]
        t = np.array([0, y2 - y, z2 - z], float)
        t /= np.linalg.norm(t)
        n = np.cross(t, np.array([1.0, 0, 0]))
        if np.dot(n, np.array([0, y - TRACK_Y, z - sum(TRACK_Z) / 2])) < 0:
            n = -n
        c = np.array([(x0 + x1) / 2, (y + y2) / 2, (z + z2) / 2]) + n * 0.02
        lugs.extend(oriented(_lug(c, t, n, x1 - x0 - 0.04, 0.09, 0.05)))
    return join(belt, lugs)


def _lug(c, t, n, w, length, h):
    side = np.array([1.0, 0, 0])
    corners = []
    for dy in (-h / 2, h / 2):
        top = 0.6 if dy > 0 else 1.0  # верх уже: скос
        ring = [c + side * sx * w / 2 + t * st * length / 2 * top + n * dy for sx, st in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        corners.append(ring)
    return loft(corners)


def wheels(side=1):
    """Ведущее и ленивец (большие), три катка с балансиром. Возвращает [(имя, mesh, роль-имя)]."""
    x0, x1 = TRACK_X
    xc = (x0 + x1) / 2
    w = x1 - x0 - 0.10
    out = []
    z0, z1 = TRACK_Z
    for k, z in enumerate((z0, z1), 1):
        out.append((f"Wheel_{k}", cylinder((xc, TRACK_Y, z), TRACK_R - BELT - 0.01, "x", w, n=10, bevel=0.03)))
        out.append((f"Hub_{k}", cylinder((x1 - 0.03, TRACK_Y, z), 0.12, "x", 0.08, n=6)))
    road = [-0.30, 0.03, 0.36]
    for k, z in enumerate(road, 3):
        out.append((f"Wheel_{k}", cylinder((xc, 0.15, z), 0.13, "x", w * 0.7, n=8)))
        out.append((f"Hub_{k}", cylinder((x1 - 0.06, 0.15, z), 0.06, "x", 0.06, n=6)))
    bogie = join(box((x1 - 0.12, 0.22, (road[0] + road[-1]) / 2), (0.05, 0.10, road[-1] - road[0] + 0.12)),
                 box((x1 - 0.12, 0.38, 0.03), (0.05, 0.28, 0.10)),
                 box((x0 + 0.03, 0.40, (z0 + z1) / 2), (0.05, 0.12, z1 - z0)))
    out.append(("Bogie", bogie))
    if side < 0:
        out = [(n, mirror_x(m)) for n, m in out]
    return out


def cab():
    body = prism(CAB, "x", -W_CAB, W_CAB, 0.07)
    rear = box((0, 0.47, 0.72), (0.84, 0.44, 0.56), 0.05)  # отсек под кабиной сзади
    return body, rear


def side_panels():
    """Светлые накладки на борт: передняя — шестигранная, задняя — прямоугольная; правая и левая."""
    front = [(-0.62, 0.80), (-0.74, 0.96), (-0.74, 1.17), (-0.48, 1.52), (0.10, 1.52), (0.10, 0.80)]
    back = [(0.18, 0.80), (0.18, 1.52), (0.82, 1.52), (0.88, 1.44), (0.88, 0.80)]
    out = []
    for i, poly in enumerate((front, back), 1):
        m = prism(poly, "x", W_CAB - 0.01, W_CAB + 0.035, 0.02)
        out.append((f"SidePanel_R{i}", m))
        out.append((f"SidePanel_L{i}", mirror_x(m)))
    return out


def front_details():
    out = []
    # решётка на носу: рамка + чёрные планки
    slats = Mesh()
    for k in range(3):
        slats.extend(box((0, 0.99 + k * 0.07, -0.85), (0.62, 0.035, 0.04), 0.0))
    out.append(("Grille", join(box((0, 1.06, -0.835), (0.70, 0.24, 0.03), 0.01), slats)))
    for sx in (1, -1):
        out.append((f"Glow_Lamp_{'R' if sx > 0 else 'L'}", box((sx * 0.52, 1.10, -0.85), (0.14, 0.07, 0.04), 0.01)))
    # кромка над носом (светлая) по скату
    edge = prism([(-0.85, 1.21), (-0.53, 1.63), (-0.49, 1.61), (-0.81, 1.19)], "x", -W_CAB + 0.06, W_CAB - 0.06)
    out.append(("Edge_Nose", edge))
    return out


def top_details():
    out = [("Lid", box((0, 1.645, 0.45), (0.74, 0.05, 0.84), 0.02))]
    vents = Mesh()
    for k in range(5):
        vents.extend(box((0, 1.635, -0.30 + k * 0.09), (0.56, 0.04, 0.045)))
    out.append(("Vent_Top", vents))
    out.append(("Glow_Lid", box((0, 1.675, 0.86), (0.50, 0.02, 0.04))))
    return out


def back_details():
    vents = Mesh()
    for k in range(4):
        vents.extend(box((0, 0.84 + k * 0.09, 1.012), (0.62, 0.045, 0.03)))
    return [("Vent_Back", vents),
            ("Glow_Back", box((0, 1.40, 1.012), (0.80, 0.05, 0.03))),
            ("Edge_Bumper", box((0, 0.36, 1.03), (0.90, 0.16, 0.08), 0.03))]


def rake():
    """Грабли: поперечина, решётчатая площадка, два рычага к шарнирам под носом, шесть зубьев."""
    bar = box((0, 0.66, -1.06), (1.14, 0.14, 0.12), 0.03)
    deck = Mesh()
    for k in range(5):
        deck.extend(box((-0.40 + k * 0.20, 0.64, -0.83), (0.07, 0.05, 0.36)))
    arms = Mesh()
    for sx in (1, -1):
        arms.extend(box((sx * 0.50, 0.66, -0.84), (0.08, 0.12, 0.42), 0.02))
    teeth = []
    for k in range(6):
        x = -0.50 + k * 0.20
        pts = [(x, 0.66, -1.10), (x, 0.60, -1.24), (x, 0.44, -1.34), (x, 0.24, -1.37), (x, 0.08, -1.31)]
        teeth.append((f"Tooth_{k + 1}", hook(pts, [(0.045, 0.055), (0.042, 0.05), (0.034, 0.04), (0.022, 0.026)])))
    pivots = []
    for sx in (1, -1):
        s = "R" if sx > 0 else "L"
        pivots.append((f"Pivot_Rake{s}", cylinder((sx * 0.50, 0.66, -0.62), 0.09, "x", 0.12, n=8)))
    return [("Rake", join(bar, deck, arms))] + teeth + pivots


def masts():
    out = []
    for sx in (1, -1):
        s = "R" if sx > 0 else "L"
        x = sx * (W_CAB + 0.11)
        out.append((f"Arm_{s}", box((sx * (W_CAB + 0.05), 0.95, 0.80), (0.10, 0.16, 0.20), 0.02)))
        out.append((f"Pivot_Mast{s}", cylinder((x, 0.95, 0.80), 0.10, "x", 0.10, n=8)))
        out.append((f"Mast_{s}", join(box((x, 1.42, 0.80), (0.08, 0.90, 0.08), 0.015),
                                      box((x, 1.42, 0.80), (0.11, 0.06, 0.11), 0.015))))
        out.append((f"MastTip_{s}", box((x, 1.91, 0.80), (0.10, 0.08, 0.10), 0.02)))
    return out


def build():
    m = Model()
    m.nodes[m.root]["name"] = "Carrier"
    for role, (rgb, rough, metal) in palette.COLORS.items():
        m.material("carrier_" + role, palette.linear(rgb), rough=rough, metal=metal)
    parts = []
    body, rear = cab()
    parts += [("Body", body), ("Chassis", join(rear, box((0, 0.48, -0.05), (0.84, 0.44, 1.30), 0.04)))]
    parts += side_panels() + front_details() + top_details() + back_details() + rake() + masts()
    for sx, s in ((1, "R"), (-1, "L")):
        tr = track_mesh()
        parts.append((f"Track_{s}", tr if sx > 0 else mirror_x(tr)))
        for name, mesh in wheels(sx):
            parts.append((f"{name}_{s}" if not name.startswith(("Wheel", "Hub")) else
                          f"{name.split('_')[0]}_{s}{name.split('_')[1]}", mesh))
    floor = min(p[1] for _, mesh in parts for t in mesh.v for p in t)  # грунтозацепы — ровно на пол
    for name, mesh in parts:
        m.part(name, mesh.transformed(lambda p: p - np.array([0, floor, 0])), "carrier_" + palette.role_of(name))
    return m


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "Модели", "Carrier", "carrier_parts.glb")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    model = build()
    model.save(out)
    if "-v" in sys.argv:
        for n in model.nodes:
            if n["mesh"] is not None:
                print(f"{n['name']:16s} {n['mesh'].ntris():5d}")
    print(out, model.tris(), "tris,", sum(1 for n in model.nodes if n["mesh"] is not None), "parts")
