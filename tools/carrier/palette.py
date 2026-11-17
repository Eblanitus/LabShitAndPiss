"""Палитра дрона-носильщика по вики (alchemy_td_art_style_v1): холодный серый металл, почти чёрный
пластик, светлые матовые панели, белый неон (игра перекрашивает его в цвет элемента).
Роль детали — по началу имени, как у жуков (раскраска по именам деталей). Цвета — sRGB 0..255."""
import re

COLORS = {
    "dark": ((46, 49, 55), 0.55, 0.6),     # корпус: тёмный металл (цвет, шероховатость, металличность)
    "mid": ((70, 75, 83), 0.5, 0.6),       # рама, стойки, ступицы
    "light": ((98, 104, 114), 0.45, 0.6),  # кромки, мелкие рёбра
    "panel": ((172, 178, 188), 0.8, 0.0),  # светлые матовые панели
    "black": ((24, 25, 28), 0.85, 0.0),    # гусеницы, щели, решётки
    "glow": ((245, 248, 255), 0.4, 0.0),   # неон (в Roblox — Material Neon)
}

# начало имени детали -> роль цвета
ROLE = [
    (r"^Glow", "glow"), (r"^MastTip", "glow"),
    (r"^Track", "black"), (r"^Tread", "black"), (r"^Grille", "black"), (r"^Vent", "black"),
    (r"^Lid", "panel"), (r"^SidePanel", "panel"), (r"^Panel", "panel"),
    (r"^Body", "dark"), (r"^Chassis", "mid"), (r"^Cab", "dark"), (r"^Fender", "dark"),
    (r"^Rake", "mid"), (r"^Tooth", "light"), (r"^Mast", "mid"), (r"^Bogie", "mid"), (r"^Wheel", "mid"),
    (r"^Sprocket", "mid"), (r"^Hub", "light"), (r"^Pivot", "light"), (r"^Edge", "light"), (r"^Arm", "mid"),
]


def role_of(name):
    return next((r for pat, r in ROLE if re.match(pat, name)), "dark")


def srgb01(c):
    return tuple(x / 255 for x in c)


def linear(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in srgb01(c))
