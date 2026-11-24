"""Pure Cairo vector blueprints and Sony A7C II (ILCE-7CM2) hardware button art.

Coordinates in TOP_BUTTONS, REAR_BUTTONS, and RING_BUTTONS are the single source of truth
shared by chassis artwork and GTK widget placement (every hit target >= 44x44, zero center overlap).
"""
import math

import cairo

TOP_W = 960
TOP_H = 214
REAR_W = 960
REAR_H = 476

REAR_LCD_RECT = (92, 102, 464, 348)  # 464:348 == 4:3 exact
REAR_RING_RECT = (634, 198, 208, 208)

TOP_BUTTONS = {
    'MODE': (554, 46, 92, 92),
    'MODE_SQ': (532, 148, 44, 44),
    'MODE_MOVIE': (578, 152, 44, 44),
    'MODE_STILL': (624, 148, 44, 44),
    'FRONT_LEFT': (680, 6, 44, 44),
    'FRONT_RIGHT': (724, 6, 44, 44),
    'SHUTTER_HALF': (772, 20, 44, 44),
    'SHUTTER': (820, 18, 52, 52),
    'OFF': (878, 12, 44, 44),
    'ON': (878, 60, 44, 44),
    'REC': (770, 78, 46, 46),
    'TOP_LEFT': (818, 120, 44, 78),
    'TOP_RIGHT': (862, 120, 44, 78),
}

REAR_BUTTONS = {
    'MENU': (444, 26, 68, 44),
    'C1': (524, 26, 46, 44),
    'REAR_LEFT': (612, 26, 45, 44),
    'REAR_RIGHT': (657, 26, 45, 44),
    'AF_ON': (616, 76, 48, 46),
    'FN': (617, 130, 46, 46),
    'PLAYBACK': (650, 422, 48, 44),
    'DELETE': (746, 422, 48, 44),
}

RING_BUTTONS = {
    'CONTROL_LEFT': (8, 8, 44, 44),
    'UP': (82, 34, 44, 44),
    'CONTROL_RIGHT': (156, 8, 44, 44),
    'LEFT': (34, 82, 44, 44),
    'ENTER': (82, 82, 44, 44),
    'RIGHT': (130, 82, 44, 44),
    'DOWN': (82, 130, 44, 44),
}

# Palette: dark matte magnesium chassis + high-contrast crisp white/silver technical line-art
COL_BG = (0.075, 0.090, 0.102)
COL_BODY = (0.106, 0.125, 0.141)
COL_PANEL = (0.133, 0.157, 0.176)
COL_DARK = (0.055, 0.067, 0.078)
COL_METAL = (0.195, 0.225, 0.248)
COL_LINE = (0.855, 0.882, 0.902)
COL_LINE_DIM = (0.490, 0.545, 0.580)
COL_LINE_FAINT = (0.260, 0.305, 0.335)
COL_INK = (0.945, 0.960, 0.965)
COL_ACCENT = (0.922, 0.627, 0.306)
COL_SONY_ORANGE = (0.835, 0.388, 0.176)
COL_RED = (0.855, 0.220, 0.180)
COL_RED_HOT = (0.980, 0.305, 0.255)
COL_TEAL = (0.118, 0.640, 0.560)
COL_GREEN = (0.369, 0.761, 0.561)

MODE_ANGLES = {
    'AUTO': 142.0,
    'P': 102.0,
    'A': 64.0,
    'S': 28.0,
    'M': -10.0,
    'MR1': -54.0,
    '1': -54.0,
    'MR2': -92.0,
    '2': -92.0,
    'MR3': -130.0,
    '3': -130.0,
}

MODE_DIAL_RING = ('AUTO', 'P', 'A', 'S', 'M', 'MR1', 'MR2', 'MR3')

MODE_SWITCH_ANGLES = {
    1: 58.0,   # STILL (right detent aligned to MODE_STILL)
    2: 90.0,   # MOVIE (center detent aligned to MODE_MOVIE)
    3: 122.0,  # S&Q   (left detent aligned to MODE_SQ)
}


def _round_rect(cr, x, y, w, h, r):
    r = min(r, w / 2.0, h / 2.0)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _circle(cr, cx, cy, r):
    cr.new_sub_path()
    cr.arc(cx, cy, r, 0, 2 * math.pi)


def _text(cr, x, y, text, size=11.0, bold=True, color=COL_INK, align='center', family='Sans', italic=False):
    cr.save()
    cr.new_path()
    slant = cairo.FONT_SLANT_ITALIC if italic else cairo.FONT_SLANT_NORMAL
    weight = cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL
    cr.select_font_face(family, slant, weight)
    cr.set_font_size(size)
    xb, yb, tw, th, _, _ = cr.text_extents(text)
    if align == 'center':
        tx = x - (xb + tw / 2.0)
    elif align == 'right':
        tx = x - (xb + tw)
    else:
        tx = x - xb
    ty = y - (yb + th / 2.0)
    cr.set_source_rgba(*color[:3], color[3] if len(color) > 3 else 1.0)
    cr.move_to(tx, ty)
    cr.show_text(text)
    cr.new_path()
    cr.restore()


def _knurled_edge(cr, cx, cy, r_outer, r_inner, count, color=COL_LINE_DIM, width=1.0, offset_deg=0.0):
    cr.save()
    cr.new_path()
    cr.set_source_rgba(*color[:3], color[3] if len(color) > 3 else 1.0)
    cr.set_line_width(width)
    offset = math.radians(offset_deg)
    for idx in range(count):
        ang = offset + (2.0 * math.pi * idx) / count
        ca, sa = math.cos(ang), math.sin(ang)
        cr.move_to(cx + r_inner * ca, cy + r_inner * sa)
        cr.line_to(cx + r_outer * ca, cy + r_outer * sa)
    cr.stroke()
    cr.restore()


def _screw(cr, cx, cy, r=5.2):
    cr.save()
    cr.new_path()
    _circle(cr, cx, cy, r)
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.0)
    cr.stroke()
    for a in (0.0, math.pi / 2.0):
        cr.move_to(cx - (r - 2.0) * math.cos(a), cy - (r - 2.0) * math.sin(a))
        cr.line_to(cx + (r - 2.0) * math.cos(a), cy + (r - 2.0) * math.sin(a))
    cr.stroke()
    cr.restore()


def _strap_lug(cr, x, y, side):
    cr.save()
    cr.new_path()
    sign = -1.0 if side == 'left' else 1.0
    _round_rect(cr, x - (8 if side == 'left' else 0), y - 5, 8, 10, 2.5)
    cr.set_source_rgb(*COL_METAL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.2)
    cr.stroke()
    cx = x + sign * 11.0
    _circle(cr, cx, y, 7.0)
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.4)
    cr.stroke()
    _circle(cr, cx, y, 3.2)
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.0)
    cr.stroke()
    cr.restore()


def _camera_icon(cr, cx, cy, scale=1.0, color=COL_INK):
    cr.save()
    cr.new_path()
    cr.translate(cx, cy)
    cr.scale(scale, scale)
    cr.set_source_rgba(*color[:3], color[3] if len(color) > 3 else 1.0)
    cr.set_line_width(1.35)
    _round_rect(cr, -7.5, -4.0, 15.0, 9.5, 1.8)
    cr.stroke()
    cr.move_to(-3.5, -4.0)
    cr.line_to(-2.2, -6.4)
    cr.line_to(2.2, -6.4)
    cr.line_to(3.5, -4.0)
    cr.stroke()
    _circle(cr, 0.0, 0.8, 2.7)
    cr.stroke()
    cr.restore()


def _movie_icon(cr, cx, cy, scale=1.0, color=COL_INK):
    cr.save()
    cr.new_path()
    cr.translate(cx, cy)
    cr.scale(scale, scale)
    cr.set_source_rgba(*color[:3], color[3] if len(color) > 3 else 1.0)
    _round_rect(cr, -7.5, -4.2, 10.5, 8.4, 1.5)
    cr.fill()
    cr.move_to(3.4, -1.5)
    cr.line_to(7.5, -4.0)
    cr.line_to(7.5, 4.0)
    cr.line_to(3.4, 1.5)
    cr.close_path()
    cr.fill()
    cr.restore()


def _play_icon(cr, cx, cy, color=COL_INK):
    cr.save()
    cr.new_path()
    cr.set_source_rgba(*color[:3], color[3] if len(color) > 3 else 1.0)
    cr.set_line_width(1.5)
    _round_rect(cr, cx - 9.0, cy - 6.8, 18.0, 13.6, 2.5)
    cr.stroke()
    cr.move_to(cx - 3.2, cy - 4.0)
    cr.line_to(cx + 4.8, cy)
    cr.line_to(cx - 3.2, cy + 4.0)
    cr.close_path()
    cr.fill()
    cr.restore()


def _trash_icon(cr, cx, cy, color=COL_INK):
    cr.save()
    cr.new_path()
    cr.set_source_rgba(*color[:3], color[3] if len(color) > 3 else 1.0)
    cr.set_line_width(1.5)
    cr.move_to(cx - 6.5, cy - 4.5)
    cr.line_to(cx + 6.5, cy - 4.5)
    cr.move_to(cx - 2.6, cy - 7.0)
    cr.line_to(cx + 2.6, cy - 7.0)
    cr.move_to(cx, cy - 7.0)
    cr.line_to(cx, cy - 4.5)
    cr.stroke()
    _round_rect(cr, cx - 5.2, cy - 2.8, 10.4, 10.5, 1.2)
    cr.stroke()
    for dx in (-2.0, 2.0):
        cr.move_to(cx + dx, cy - 0.5)
        cr.line_to(cx + dx, cy + 5.6)
    cr.stroke()
    cr.restore()


def _zoom_icon(cr, cx, cy, color=COL_LINE):
    cr.save()
    cr.new_path()
    cr.set_source_rgb(*color)
    cr.set_line_width(1.3)
    _circle(cr, cx - 1.5, cy - 1.5, 5.2)
    cr.stroke()
    cr.move_to(cx - 4.0, cy - 1.5)
    cr.line_to(cx + 1.0, cy - 1.5)
    cr.move_to(cx - 1.5, cy - 4.0)
    cr.line_to(cx - 1.5, cy + 1.0)
    cr.move_to(cx + 2.3, cy + 2.3)
    cr.line_to(cx + 6.2, cy + 6.2)
    cr.stroke()
    cr.restore()


def _send_icon(cr, cx, cy, color=COL_LINE):
    cr.save()
    cr.new_path()
    cr.set_source_rgb(*color)
    cr.set_line_width(1.3)
    _round_rect(cr, cx - 1.5, cy - 6.5, 8.2, 13.0, 1.5)
    cr.stroke()
    cr.move_to(cx - 7.5, cy)
    cr.line_to(cx + 1.5, cy)
    cr.move_to(cx - 1.5, cy - 2.8)
    cr.line_to(cx + 1.8, cy)
    cr.line_to(cx - 1.5, cy + 2.8)
    cr.stroke()
    cr.restore()


def _timer_drive_icons(cr, cx, cy, color=COL_LINE):
    cr.save()
    cr.new_path()
    cr.set_source_rgb(*color)
    cr.set_line_width(1.3)
    _circle(cr, cx, cy - 10, 5.5)
    cr.stroke()
    cr.move_to(cx, cy - 10)
    cr.line_to(cx + 2.6, cy - 12.6)
    cr.move_to(cx - 1.8, cy - 16.8)
    cr.line_to(cx + 1.8, cy - 16.8)
    cr.stroke()
    _round_rect(cr, cx - 6.0, cy + 4.0, 8.0, 6.2, 1.0)
    cr.stroke()
    cr.move_to(cx + 3.8, cy + 6.2)
    cr.line_to(cx + 3.8, cy + 12.2)
    cr.line_to(cx - 3.5, cy + 12.2)
    cr.stroke()
    cr.restore()


def _index_icon(cr, cx, cy, color=COL_LINE):
    cr.save()
    cr.new_path()
    cr.set_source_rgb(*color)
    step = 4.2
    x0, y0 = cx - 6.3, cy - 4.2
    for row in range(2):
        for col in range(3):
            if (row + col) % 2 == 0:
                cr.rectangle(x0 + col * step, y0 + row * step, step, step)
    cr.fill()
    cr.set_line_width(1.0)
    cr.rectangle(x0, y0, step * 3, step * 2)
    cr.stroke()
    cr.restore()


def _curved_spin_arrow(cr, cx, cy, r, ccw, color):
    """Vector curved arrow along control wheel upper shoulders (avoids missing Unicode glyphs)."""
    cr.save()
    cr.new_path()
    cr.set_source_rgba(*color[:3], color[3] if len(color) > 3 else 1.0)
    cr.set_line_width(1.7)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    if ccw:
        # Arc curving down-left toward 9 o'clock
        a0, a1 = -0.35 * math.pi, -0.85 * math.pi
        cr.arc_negative(cx, cy, r, a0, a1)
        tip_x = cx + r * math.cos(a1)
        tip_y = cy + r * math.sin(a1)
        tangent = a1 - math.pi / 2.0
    else:
        # Arc curving down-right toward 3 o'clock
        a0, a1 = -0.65 * math.pi, -0.15 * math.pi
        cr.arc(cx, cy, r, a0, a1)
        tip_x = cx + r * math.cos(a1)
        tip_y = cy + r * math.sin(a1)
        tangent = a1 + math.pi / 2.0
    cr.stroke()
    # Clean arrowhead at arc end
    for side in (-2.5, 2.5):
        ang = tangent + side
        cr.move_to(tip_x, tip_y)
        cr.line_to(tip_x - 4.6 * math.cos(ang), tip_y - 4.6 * math.sin(ang))
    cr.stroke()
    cr.restore()


def _top_silhouette_path(cr):
    """Sony A7C II orthographic top-plate contour matching user blueprint."""
    cr.new_path()
    cr.move_to(54, 34)
    cr.line_to(650, 34)
    cr.curve_to(674, 34, 688, 12, 718, 8)
    cr.line_to(848, 8)
    cr.curve_to(904, 8, 932, 38, 934, 96)
    cr.line_to(934, 174)
    cr.curve_to(934, 198, 916, 204, 888, 202)
    cr.line_to(752, 200)
    cr.line_to(736, 188)
    cr.line_to(678, 188)
    cr.line_to(666, 202)
    cr.line_to(534, 202)
    cr.line_to(522, 188)
    cr.line_to(220, 188)
    cr.line_to(220, 208)
    cr.line_to(38, 208)
    cr.curve_to(26, 208, 24, 194, 24, 176)
    cr.line_to(24, 64)
    cr.curve_to(24, 44, 38, 34, 54, 34)
    cr.close_path()


def _rear_silhouette_path(cr):
    """Sony A7C II orthographic rear-body contour matching user blueprint."""
    cr.new_path()
    cr.move_to(36, 12)
    cr.line_to(196, 12)
    cr.curve_to(210, 12, 214, 24, 224, 24)
    cr.line_to(898, 24)
    cr.curve_to(920, 24, 934, 38, 934, 62)
    cr.line_to(934, 434)
    cr.curve_to(934, 456, 918, 468, 892, 468)
    cr.line_to(52, 468)
    cr.curve_to(32, 468, 24, 454, 24, 434)
    cr.line_to(24, 28)
    cr.curve_to(24, 16, 28, 12, 36, 12)
    cr.close_path()


def draw_top_chassis(cr, ui_state):
    """Draw Sony A7C II top-down line-art chassis behind interactive top controls."""
    cr.set_source_rgb(*COL_BG)
    cr.paint()

    # Lens mount flange peeking front-center + signature orange E-mount collar
    cr.save()
    _round_rect(cr, 204, 10, 358, 28, 6)
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.3)
    cr.stroke()
    cr.set_source_rgb(*COL_SONY_ORANGE)
    cr.set_line_width(2.0)
    cr.move_to(214, 31)
    cr.line_to(552, 31)
    cr.stroke()
    cr.restore()

    _strap_lug(cr, 24, 118, 'left')
    _strap_lug(cr, 934, 168, 'right')

    # Main top-plate body fill + chamfered vector contour
    _top_silhouette_path(cr)
    cr.set_source_rgb(*COL_BODY)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.6)
    cr.stroke()

    # EVF seam + top-plate split + grip contour + unified shutter/ON-OFF plinth
    cr.save()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.1)
    cr.move_to(24, 152)
    cr.curve_to(90, 178, 172, 184, 224, 184)
    cr.line_to(220, 208)
    cr.move_to(500, 34)
    cr.line_to(500, 188)
    cr.move_to(660, 72)
    cr.curve_to(756, 62, 858, 68, 934, 102)
    cr.stroke()
    # Sculpted shutter plinth + coaxial ON/OFF rotary power collar, curved track, and lever arm
    _round_rect(cr, 767, 13, 108, 60, 28)
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_FAINT)
    cr.set_line_width(1.1)
    cr.stroke()
    cr.restore()

    # Coaxial ON/OFF switch housing & animated rotary lever centered on Shutter (846, 44)
    power_pos = max(0.0, min(1.0, float(ui_state.get('power_pos', 1.0 if ui_state.get('running') else 0.0))))
    power_ang = -11.0 + 46.0 * power_pos
    cr.save()
    _top_silhouette_path(cr)
    cr.clip()
    cr.new_sub_path()
    cr.arc(846.0, 44.0, 74.0, math.radians(-20.0), math.radians(45.0))
    cr.arc_negative(846.0, 44.0, 30.0, math.radians(45.0), math.radians(-20.0))
    cr.close_path()
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.1)
    cr.stroke()
    # Curved guide slot connecting OFF (-11 deg) and ON (+35 deg) detents
    cr.save()
    cr.new_path()
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.arc(846.0, 44.0, 46.0, math.radians(-13.0), math.radians(37.0))
    cr.set_source_rgb(*COL_BG)
    cr.set_line_width(7.5)
    cr.stroke_preserve()
    cr.set_source_rgba(*(COL_GREEN if power_pos > 0.5 else COL_LINE_FAINT), 0.55)
    cr.set_line_width(1.2)
    cr.stroke()
    cr.restore()
    # Coaxial machined collar ring around Shutter
    _circle(cr, 846.0, 44.0, 30.5)
    cr.set_source_rgb(*COL_PANEL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.1)
    cr.stroke()
    # Rotating physical lever arm + knurled thumb paddle
    cr.save()
    cr.translate(846.0, 44.0)
    cr.rotate(math.radians(power_ang))
    _round_rect(cr, 25.0, -7.2, 27.0, 14.4, 4.5)
    cr.set_source_rgb(*COL_METAL)
    cr.fill_preserve()
    cr.set_source_rgb(*(COL_GREEN if power_pos > 0.5 else COL_LINE))
    cr.set_line_width(1.35)
    cr.stroke()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.0)
    for rx in (35.0, 39.0, 43.0):
        cr.move_to(rx, -4.4)
        cr.line_to(rx, 4.4)
    cr.stroke()
    _circle(cr, 48.0, 0.0, 2.2)
    cr.set_source_rgb(*(COL_GREEN if power_pos > 0.5 else COL_LINE))
    cr.fill()
    cr.restore()
    cr.restore()

    # Dual speaker vents
    for dx in (118, 138):
        _round_rect(cr, dx, 76, 11, 4, 2)
        cr.set_source_rgb(*COL_DARK)
        cr.fill_preserve()
        cr.set_source_rgb(*COL_LINE_DIM)
        cr.set_line_width(1.0)
        cr.stroke()

    # Model engraving: alpha 7C II
    _text(cr, 120, 128, 'α', size=20, bold=False, color=COL_INK, align='center', family='Serif', italic=True)
    _text(cr, 144, 129, '7C II', size=16, bold=True, color=COL_INK, align='center')

    # Focal plane mark (circle with horizontal line)
    cr.save()
    cr.new_path()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.3)
    _circle(cr, 244, 86, 6.0)
    cr.stroke()
    cr.move_to(232, 86)
    cr.line_to(256, 86)
    cr.stroke()
    cr.restore()

    # Multi Interface (MI) Hot Shoe + 4 miniature Phillips screws
    for sx, sy in ((284, 56), (284, 148), (464, 56), (464, 148)):
        _screw(cr, sx, sy, 4.8)
    _round_rect(cr, 310, 72, 126, 84, 4)
    cr.set_source_rgb(*COL_PANEL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.4)
    cr.stroke()
    _round_rect(cr, 324, 80, 98, 72, 3)
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.1)
    cr.stroke()
    cr.save()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.2)
    _circle(cr, 373, 112, 11.0)
    cr.stroke()
    _circle(cr, 373, 112, 4.5)
    cr.stroke()
    cr.move_to(356, 140)
    cr.line_to(390, 140)
    cr.stroke()
    cr.restore()

    # Mode dial white reference tick dash at 9 o'clock
    cr.save()
    cr.set_source_rgb(*COL_INK)
    cr.set_line_width(2.6)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.move_to(522, 92)
    cr.line_to(535, 92)
    cr.stroke()
    cr.restore()

    # Coaxial Still/Movie/S&Q fanned base plate, detent track, and swinging radial lever
    mode_sw = int(ui_state.get('mode_switch') or 1)
    ang_deg = float(ui_state.get('mode_switch_deg', MODE_SWITCH_ANGLES.get(mode_sw, 58.0)))
    cr.save()
    cr.new_sub_path()
    cr.arc(600.0, 92.0, 67.0, math.radians(38.0), math.radians(142.0))
    cr.arc_negative(600.0, 92.0, 42.0, math.radians(142.0), math.radians(38.0))
    cr.close_path()
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.1)
    cr.stroke()
    # Curved guide arc & three detent ticks (STILL 58°, MOVIE 90°, S&Q 122°)
    cr.save()
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.new_path()
    cr.arc(600.0, 92.0, 52.0, math.radians(55.0), math.radians(125.0))
    cr.set_source_rgb(*COL_BG)
    cr.set_line_width(6.5)
    cr.stroke()
    for det_deg in (58.0, 90.0, 122.0):
        rad = math.radians(det_deg)
        ca, sa = math.cos(rad), math.sin(rad)
        is_near = abs(ang_deg - det_deg) < 8.0
        cr.set_source_rgb(*(COL_ACCENT if is_near else COL_LINE_DIM))
        cr.set_line_width(2.0 if is_near else 1.2)
        cr.move_to(600.0 + 61.5 * ca, 92.0 + 61.5 * sa)
        cr.line_to(600.0 + 66.5 * ca, 92.0 + 66.5 * sa)
        cr.stroke()
    cr.restore()
    # Swinging physical coaxial lever arm
    cr.save()
    cr.translate(600.0, 92.0)
    cr.rotate(math.radians(ang_deg))
    _round_rect(cr, 39.0, -7.0, 22.0, 14.0, 4.0)
    cr.set_source_rgb(*COL_METAL)
    cr.fill_preserve()
    cr.set_source_rgb(*(COL_ACCENT if ui_state.get('running') else COL_LINE))
    cr.set_line_width(1.3)
    cr.stroke()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.0)
    for gx in (45.0, 49.0, 53.0):
        cr.move_to(gx, -4.2)
        cr.line_to(gx, 4.2)
    cr.stroke()
    cr.set_source_rgb(*(COL_ACCENT if ui_state.get('running') else COL_INK))
    cr.set_line_width(2.0)
    cr.move_to(56.0, 0.0)
    cr.line_to(60.5, 0.0)
    cr.stroke()
    cr.restore()
    cr.restore()

    # Crisp blueprint dial callouts for 前拨轮 & 右上拨轮 (non-overlapping with hitboxes)
    _text(cr, 724, 54, '前拨轮', size=9.5, bold=True, color=COL_LINE_DIM)
    _text(cr, 782, 159, '右上拨轮', size=9.5, bold=True, color=COL_LINE_DIM)

    # Rear edge top-view peeks aligned horizontally with Rear View MENU / C1 / Rear Dial L
    for px, pw in ((456, 44), (536, 22), (620, 74)):
        _round_rect(cr, px, 188, pw, 7, 2.5)
        cr.set_source_rgb(*COL_PANEL)
        cr.fill_preserve()
        cr.set_source_rgb(*COL_LINE_DIM)
        cr.set_line_width(1.0)
        cr.stroke()
    cr.save()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(0.9)
    for tx in range(626, 692, 6):
        cr.move_to(tx, 189)
        cr.line_to(tx, 194)
    cr.stroke()
    cr.restore()

    # Subtle power / recording status LED at top-left shoulder
    vm_state = ui_state.get('vm_state', 'disconnected')
    led_col = (COL_RED_HOT if ui_state.get('recording') else
               COL_GREEN if vm_state == 'running' else
               COL_ACCENT if vm_state in ('starting', 'stopping') else
               COL_RED if vm_state in ('faulted', 'error') else
               COL_LINE_FAINT)
    cr.save()
    _circle(cr, 46, 56, 4.2)
    cr.set_source_rgb(*led_col)
    cr.fill()
    cr.restore()


def draw_rear_chassis(cr, ui_state):
    """Draw Sony A7C II orthographic rear-view line-art chassis behind rear controls."""
    cr.set_source_rgb(*COL_BG)
    cr.paint()

    # Top-edge peeking dial/shoe silhouettes matching HEHX blueprint
    _round_rect(cr, 316, 10, 114, 16, 3)
    cr.set_source_rgb(*COL_PANEL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.2)
    cr.stroke()
    _round_rect(cr, 550, 2, 116, 22, 4)
    cr.set_source_rgb(*COL_METAL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.3)
    cr.stroke()
    cr.save()
    for tx in range(556, 662, 6):
        cr.move_to(tx, 3)
        cr.line_to(tx + 3, 18)
        cr.move_to(tx + 3, 3)
        cr.line_to(tx, 18)
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(0.8)
    cr.stroke()
    cr.restore()

    _round_rect(cr, 782, 6, 112, 18, 4)
    cr.set_source_rgb(*COL_METAL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.3)
    cr.stroke()
    cr.save()
    for tx in range(788, 890, 6):
        cr.move_to(tx, 7)
        cr.line_to(tx + 3, 21)
        cr.move_to(tx + 3, 7)
        cr.line_to(tx, 21)
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(0.8)
    cr.stroke()
    cr.restore()

    _strap_lug(cr, 24, 48, 'left')
    _strap_lug(cr, 934, 72, 'right')

    # Main camera rear body plate
    _rear_silhouette_path(cr)
    cr.set_source_rgb(*COL_BODY)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.6)
    cr.stroke()

    # EVF rubber eyecup block + glass + IR eye sensor
    _round_rect(cr, 18, 12, 188, 84, 14)
    cr.set_source_rgb(*COL_PANEL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.5)
    cr.stroke()
    _round_rect(cr, 32, 22, 160, 64, 10)
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.1)
    cr.stroke()
    _round_rect(cr, 48, 28, 92, 52, 6)
    cr.set_source_rgb(0.03, 0.045, 0.055)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.stroke()
    cr.save()
    cr.set_source_rgba(0.24, 0.72, 0.65, 0.22)
    cr.move_to(58, 34)
    cr.line_to(94, 34)
    cr.line_to(70, 74)
    cr.line_to(54, 74)
    cr.close_path()
    cr.fill()
    cr.restore()
    _round_rect(cr, 156, 32, 18, 44, 8)
    cr.set_source_rgb(0.02, 0.025, 0.03)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.0)
    cr.stroke()

    # Diopter-adjustment dial right of eyecup
    dcx, dcy = 238, 54
    _circle(cr, dcx, dcy, 22)
    cr.set_source_rgb(*COL_PANEL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.3)
    cr.stroke()
    _knurled_edge(cr, dcx, dcy, 21, 14, 18, COL_LINE_DIM, 1.0)
    _circle(cr, dcx, dcy, 12)
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.stroke()

    # Vari-angle LCD articulating left hinge + outer door frame
    _round_rect(cr, 34, 118, 30, 314, 5)
    cr.set_source_rgb(*COL_PANEL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.3)
    cr.stroke()
    cr.save()
    for hy in (148, 402):
        cr.move_to(36, hy)
        cr.line_to(62, hy)
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.stroke()
    cr.restore()

    _round_rect(cr, 64, 90, 514, 370, 8)
    cr.set_source_rgb(*COL_PANEL)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE)
    cr.set_line_width(1.4)
    cr.stroke()

    lx, ly, lw, lh = REAR_LCD_RECT
    _round_rect(cr, lx - 10, ly - 6, lw + 20, lh + 12, 5)
    cr.set_source_rgb(*COL_DARK)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_FAINT)
    cr.set_line_width(1.0)
    cr.stroke()

    # Right thumb grip contoured leatherette region + subtle stippled texture
    cr.save()
    cr.new_path()
    cr.move_to(796, 80)
    cr.line_to(902, 80)
    cr.curve_to(920, 80, 926, 94, 926, 118)
    cr.line_to(926, 426)
    cr.curve_to(926, 448, 912, 458, 886, 458)
    cr.line_to(874, 458)
    cr.curve_to(866, 386, 868, 250, 848, 198)
    cr.curve_to(832, 160, 796, 138, 796, 80)
    cr.close_path()
    cr.set_source_rgb(0.082, 0.095, 0.108)
    cr.fill_preserve()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.2)
    cr.stroke_preserve()
    cr.clip()
    cr.set_source_rgba(0.68, 0.72, 0.75, 0.12)
    for gy in range(86, 456, 7):
        off = 4 if (gy // 7) % 2 else 0
        for gx in range(798 + off, 924, 8):
            _circle(cr, gx, gy, 1.35)
            cr.fill()
    cr.restore()

    # Control deck divider seam
    cr.save()
    cr.set_source_rgb(*COL_LINE_DIM)
    cr.set_line_width(1.1)
    cr.move_to(592, 74)
    cr.line_to(592, 468)
    cr.move_to(592, 74)
    cr.line_to(934, 74)
    cr.stroke()
    cr.restore()

    # Silk-screened white Sony legends beside rear buttons & around Control Wheel
    _zoom_icon(cr, 608, 78, COL_LINE)
    _send_icon(cr, 605, 132, COL_LINE)

    rx, ry, rw, rh = REAR_RING_RECT
    rcx, rcy = rx + rw / 2.0, ry + rh / 2.0
    _text(cr, rcx, ry - 9, 'DISP', size=11.0, bold=True, color=COL_INK)
    _text(cr, rx + rw + 19, rcy, 'ISO', size=11.0, bold=True, color=COL_INK)
    _timer_drive_icons(cr, rx - 15, rcy, COL_LINE)
    _index_icon(cr, rcx - 8, ry + rh + 12, COL_LINE)
    _text(cr, 804, 415, 'C2', size=11.0, bold=True, color=COL_INK)
    _text(cr, 744, 48, '后拨轮', size=9.5, bold=True, color=COL_LINE_DIM)


def _draw_button_focus(cr, w, h, focused, circle=False, accent=COL_ACCENT):
    if not focused:
        return
    cr.save()
    cr.new_path()
    cr.set_source_rgb(*accent)
    cr.set_line_width(2.0)
    if circle:
        r = min(w, h) / 2.0 - 2.0
        _circle(cr, w / 2.0, h / 2.0, r)
    else:
        _round_rect(cr, 2.0, 2.0, w - 4.0, h - 4.0, 8.0)
    cr.stroke()
    cr.restore()


def _button_states(widget):
    flags = widget.get_state_flags()
    ctx = widget.get_style_context()
    from gi.repository import Gtk
    hover = bool(flags & Gtk.StateFlags.PRELIGHT)
    active = bool(flags & Gtk.StateFlags.ACTIVE)
    disabled = not widget.get_sensitive()
    focused = widget.has_focus()
    recording = ctx.has_class('recording')
    return hover, active, disabled, focused, recording


def _draw_circle_cap(cr, cx, cy, r, hover, active, disabled, focused,
                     ring_col=COL_LINE, fill_col=COL_PANEL, text=None, text_size=11.0,
                     icon_fn=None, extra_border=None):
    alpha = 0.42 if disabled else 1.0
    dy = 1.2 if active else 0.0
    cr.save()
    cr.new_path()
    _circle(cr, cx, cy + dy + 1.5, r)
    cr.set_source_rgba(0, 0, 0, 0.45 * alpha)
    cr.fill()

    _circle(cr, cx, cy + dy, r)
    cr.set_source_rgba(*(COL_METAL if hover and not active else COL_DARK if active else fill_col), alpha)
    cr.fill_preserve()
    border = extra_border or (COL_ACCENT if hover else ring_col)
    cr.set_source_rgba(*border, alpha)
    cr.set_line_width(2.0 if extra_border else 1.4)
    cr.stroke()

    _circle(cr, cx, cy + dy, max(2.0, r - 3.5))
    cr.set_source_rgba(*COL_LINE_FAINT, alpha)
    cr.set_line_width(0.9)
    cr.stroke()

    ink = (*COL_INK[:3], alpha)
    if text:
        _text(cr, cx, cy + dy, text, size=text_size, bold=True, color=ink)
    if icon_fn is not None:
        icon_fn(cr, cx, cy + dy, ink)
    cr.restore()
    _draw_button_focus(cr, cx * 2, cy * 2, focused, circle=True)


def draw_camera_button(name, widget, cr, ui_state):
    """Draw individual camera hardware control directly on its Gtk.Button allocation."""
    alloc = widget.get_allocation()
    w, h = float(alloc.width), float(alloc.height)
    cx, cy = w / 2.0, h / 2.0
    hover, active, disabled, focused, recording = _button_states(widget)
    alpha = 0.42 if disabled else 1.0

    if name == 'MODE':
        r = min(w, h) / 2.0 - 3.0
        sel = ui_state.get('mode_pos') or 'M'
        rot = float(ui_state.get('mode_rot', MODE_ANGLES.get(sel, -10.0)))
        cr.save()
        _circle(cr, cx, cy, r)
        cr.set_source_rgba(*COL_METAL, alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if hover else COL_LINE), alpha)
        cr.set_line_width(1.6)
        cr.stroke()
        _knurled_edge(cr, cx, cy, r - 0.5, r - 6.0, 44, (*COL_LINE_DIM, alpha), 1.0, offset_deg=-rot)
        _circle(cr, cx, cy, r - 6.0)
        cr.set_source_rgba(*COL_PANEL, alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*COL_LINE_DIM, alpha)
        cr.set_line_width(1.0)
        cr.stroke()
        for label_txt, base_deg in (('AUTO', 142.0), ('P', 102.0), ('A', 64.0), ('S', 28.0),
                                    ('M', -10.0), ('1', -54.0), ('2', -92.0), ('3', -130.0)):
            ang = math.radians(base_deg - rot + 180.0)
            lx = cx + (r - 17.5) * math.cos(ang)
            ly = cy + (r - 17.5) * math.sin(ang)
            mapped = 'MR' + label_txt if label_txt in ('1', '2', '3') else label_txt
            is_cur = mapped == sel or label_txt == sel
            if label_txt == 'AUTO':
                cr.save()
                cr.translate(lx, ly)
                _round_rect(cr, -12.5, -5.0, 25.0, 10.0, 2.0)
                cr.set_source_rgba(*(COL_ACCENT if is_cur else COL_TEAL), alpha)
                cr.fill()
                _text(cr, 0, 0, 'AUTO', size=7.2, bold=True, color=(*COL_INK, alpha))
                cr.restore()
            else:
                _text(cr, lx, ly, label_txt, size=9.2 if label_txt in 'PASM' else 8.6,
                      bold=True, color=(*(COL_ACCENT if is_cur else COL_INK), alpha))
        # Central push-lock button (click center or press Enter/Space to open full mode popover)
        _circle(cr, cx, cy, r - 29.0)
        cr.set_source_rgba(*(COL_METAL if hover else COL_DARK), alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if hover else COL_LINE_DIM), alpha)
        cr.set_line_width(1.1)
        cr.stroke()
        _text(cr, cx, cy, sel, size=9.5, bold=True, color=(*COL_ACCENT, alpha))
        cr.restore()
        _draw_button_focus(cr, w, h, focused, circle=True)
        return True

    if name in ('MODE_SQ', 'MODE_MOVIE', 'MODE_STILL'):
        sw = int(ui_state.get('mode_switch') or 1)
        is_sel = ((name == 'MODE_STILL' and sw == 1)
                  or (name == 'MODE_MOVIE' and sw == 2)
                  or (name == 'MODE_SQ' and sw == 3))
        cr.save()
        # Keep top edge open so the swinging coaxial lever on top_canvas aligns unobstructed
        pad_y, pad_h = 9.0, h - 13.0
        _round_rect(cr, 3.0, pad_y, w - 6.0, pad_h, 8.0)
        cr.set_source_rgba(*(COL_METAL if is_sel or hover else COL_DARK), alpha * (0.94 if (is_sel or hover) else 0.78))
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if is_sel else COL_LINE_DIM if hover else COL_LINE_FAINT), alpha)
        cr.set_line_width(1.5 if is_sel else 1.0)
        cr.stroke()
        if is_sel:
            _circle(cr, cx, pad_y + 3.5, 1.8)
            cr.set_source_rgba(*COL_ACCENT, alpha)
            cr.fill()
        col = (*(COL_INK if is_sel else COL_LINE), alpha)
        iy = pad_y + pad_h * 0.54
        if name == 'MODE_SQ':
            _text(cr, cx, iy, 'S&Q', size=10.0, bold=True, color=col)
        elif name == 'MODE_MOVIE':
            _movie_icon(cr, cx, iy, scale=1.0, color=col)
        else:
            _camera_icon(cr, cx, iy, scale=1.0, color=col)
        cr.restore()
        _draw_button_focus(cr, w, h, focused)
        return True

    if name == 'REC':
        ring = COL_RED_HOT if recording else COL_RED
        _draw_circle_cap(cr, cx, cy, min(w, h) / 2.0 - 4.0, hover, active, disabled, focused,
                         fill_col=COL_DARK, extra_border=ring)
        cr.save()
        _circle(cr, cx, cy + (1.0 if active else 0.0), 6.0)
        cr.set_source_rgba(*(COL_RED_HOT if recording else COL_RED), alpha)
        cr.fill()
        cr.restore()
        return True

    if name == 'SHUTTER':
        r = min(w, h) / 2.0 - 3.0
        dy = 1.5 if active else 0.0
        cr.save()
        _circle(cr, cx, cy, r)
        cr.set_source_rgba(*COL_DARK, alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if hover else COL_LINE), alpha)
        cr.set_line_width(1.5)
        cr.stroke()
        pat = cairo.RadialGradient(cx - 4, cy + dy - 4, 2, cx, cy + dy, r - 4)
        pat.add_color_stop_rgba(0, 0.36, 0.40, 0.43, alpha)
        pat.add_color_stop_rgba(1, 0.12, 0.14, 0.16, alpha)
        _circle(cr, cx, cy + dy, r - 4.5)
        cr.set_source(pat)
        cr.fill_preserve()
        cr.set_source_rgba(*COL_LINE_DIM, alpha)
        cr.set_line_width(1.0)
        cr.stroke()
        _circle(cr, cx, cy + dy, r - 11.0)
        cr.set_source_rgba(*COL_LINE_FAINT, alpha)
        cr.stroke()
        cr.restore()
        _draw_button_focus(cr, w, h, focused, circle=True)
        return True

    if name == 'SHUTTER_HALF':
        dy = 1.0 if active else 0.0
        cr.save()
        _round_rect(cr, 3, 4, w - 6, h - 8, 17)
        cr.set_source_rgba(*(COL_METAL if hover else COL_PANEL), alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if hover else COL_LINE_DIM), alpha)
        cr.set_line_width(1.3)
        cr.stroke()
        cr.new_sub_path()
        cr.arc(cx, cy + dy, 11.5, math.pi * 0.65, math.pi * 1.35)
        cr.set_source_rgba(*COL_ACCENT, alpha)
        cr.set_line_width(1.8)
        cr.stroke()
        _text(cr, cx + 2, cy + dy, '半按', size=9.5, bold=True, color=(*COL_INK, alpha))
        cr.restore()
        _draw_button_focus(cr, w, h, focused, circle=True)
        return True

    if name in ('ON', 'OFF'):
        running = bool(ui_state.get('running'))
        lit = (name == 'ON' and running) or (name == 'OFF' and not running)
        cap_alpha = 0.96 if lit else (0.58 if disabled else 1.0)
        ly = cy + (3.0 if name == 'OFF' else 0.0)
        cr.save()
        # Keep the left track open for the coaxial rotary lever; render outer detent indicator
        if hover or lit:
            _round_rect(cr, 16.0, ly - 11.0, w - 18.0, 22.0, 7.0)
            if name == 'ON' and lit:
                cr.set_source_rgba(0.11, 0.30, 0.21, 0.82 * cap_alpha)
            elif hover:
                cr.set_source_rgba(*COL_METAL, 0.65 * cap_alpha)
            else:
                cr.set_source_rgba(*COL_DARK, 0.65 * cap_alpha)
            cr.fill_preserve()
            border = COL_GREEN if (name == 'ON' and lit) else (COL_ACCENT if hover else COL_LINE_DIM)
            cr.set_source_rgba(*border, cap_alpha)
            cr.set_line_width(1.3 if lit else 1.0)
            cr.stroke()
        _circle(cr, 20.0, ly, 2.2)
        cr.set_source_rgba(*(COL_GREEN if (name == 'ON' and lit) else (COL_INK if lit else COL_LINE_DIM)), cap_alpha)
        cr.fill()
        _text(cr, 32.0, ly, name, size=8.4, bold=True, color=(*(COL_INK if lit or hover else COL_LINE), cap_alpha))
        cr.restore()
        _draw_button_focus(cr, w, h, focused)
        return True

    if name in ('TOP_LEFT', 'TOP_RIGHT'):
        is_left = name == 'TOP_LEFT'
        r = 36.0
        dcx = w if is_left else 0.0
        dcy = cy
        cr.save()
        cr.rectangle(0, 0, w, h)
        cr.clip()
        _circle(cr, dcx, dcy, r)
        cr.set_source_rgba(*(COL_METAL if hover else COL_PANEL), alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if hover else COL_LINE), alpha)
        cr.set_line_width(1.5)
        cr.stroke()
        _knurled_edge(cr, dcx, dcy, r - 0.5, r - 6.0, 44, (*COL_LINE, alpha), 1.1)
        _circle(cr, dcx, dcy, r - 6.0)
        cr.set_source_rgba(*COL_BODY, alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*COL_LINE_DIM, alpha)
        cr.stroke()
        cr.move_to(dcx, dcy)
        cr.line_to(dcx + (-17 if is_left else 17), dcy - 12)
        cr.line_to(dcx + (-9 if is_left else 9), dcy - 20)
        cr.close_path()
        cr.set_source_rgba(1, 1, 1, 0.08 * alpha)
        cr.fill()
        _text(cr, w * (0.45 if is_left else 0.55), cy, '‹' if is_left else '›',
              size=14.0, bold=True, color=(*(COL_ACCENT if hover else COL_LINE), alpha))
        cr.restore()
        _draw_button_focus(cr, w, h, focused)
        return True

    if name in ('FRONT_LEFT', 'FRONT_RIGHT', 'REAR_LEFT', 'REAR_RIGHT'):
        is_left = name.endswith('_LEFT')
        y0, dh = (8.0, 20.0) if name.startswith('FRONT') else (11.0, 22.0)
        cr.save()
        cr.rectangle(0, 0, w, h)
        cr.clip()
        # Seamless two-half drum joining cleanly across center seam
        x_start = 1.0 if is_left else -4.0
        drum_w = w + 3.0
        cr.set_source_rgba(*(COL_METAL if hover else COL_DARK), alpha)
        _round_rect(cr, x_start, y0, drum_w, dh, 4)
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if hover else COL_LINE), alpha)
        cr.set_line_width(1.3)
        cr.stroke()
        cr.set_source_rgba(*COL_LINE, alpha)
        cr.set_line_width(1.2)
        for tx in range(5, int(w) - 1, 5):
            cr.move_to(tx, y0 + 2.5)
            cr.line_to(tx, y0 + dh - 2.5)
        cr.stroke()
        _text(cr, w * (0.44 if is_left else 0.56), y0 + dh + 7.5, '‹' if is_left else '›',
              size=11.5, bold=True, color=(*(COL_ACCENT if hover else COL_LINE), alpha))
        cr.restore()
        _draw_button_focus(cr, w, h, focused)
        return True

    if name == 'MENU':
        dy = 1.0 if active else 0.0
        cr.save()
        _round_rect(cr, 3, 7 + dy, w - 6, h - 14, (h - 14) / 2.0)
        cr.set_source_rgba(*(COL_METAL if hover else COL_PANEL), alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if hover else COL_LINE), alpha)
        cr.set_line_width(1.5)
        cr.stroke()
        _round_rect(cr, 6, 10 + dy, w - 12, h - 20, (h - 20) / 2.0)
        cr.set_source_rgba(*COL_LINE_FAINT, alpha)
        cr.set_line_width(0.9)
        cr.stroke()
        _text(cr, cx, cy + dy, 'MENU', size=11.0, bold=True, color=(*COL_INK, alpha))
        cr.restore()
        _draw_button_focus(cr, w, h, focused)
        return True

    if name in ('C1', 'AF_ON', 'FN'):
        r = {'C1': 17.0, 'AF_ON': 20.0, 'FN': 18.0}[name]
        lbl = {'C1': 'C1', 'AF_ON': 'AF-ON', 'FN': 'Fn'}[name]
        sz = 10.5 if name == 'AF_ON' else 11.0
        _draw_circle_cap(cr, cx, cy, r, hover, active, disabled, focused, text=lbl, text_size=sz)
        return True

    if name == 'PLAYBACK':
        _draw_circle_cap(cr, cx, cy, 19.0, hover, active, disabled, focused, icon_fn=_play_icon)
        return True

    if name == 'DELETE':
        _draw_circle_cap(cr, cx, cy, 19.0, hover, active, disabled, focused, icon_fn=_trash_icon)
        return True

    if name in ('UP', 'DOWN', 'LEFT', 'RIGHT'):
        arrow = {'UP': '▲', 'DOWN': '▼', 'LEFT': '◀', 'RIGHT': '▶'}[name]
        _draw_circle_cap(cr, cx, cy, 17.5, hover, active, disabled, focused,
                         fill_col=COL_DARK, ring_col=COL_LINE_DIM, text=arrow, text_size=10.0)
        return True

    if name == 'ENTER':
        _draw_circle_cap(cr, cx, cy, 19.5, hover, active, disabled, focused,
                         fill_col=COL_PANEL, ring_col=COL_LINE, text='OK', text_size=9.5)
        return True

    if name in ('CONTROL_LEFT', 'CONTROL_RIGHT'):
        ccw = name == 'CONTROL_LEFT'
        cr.save()
        _circle(cr, cx, cy, 15.0)
        cr.set_source_rgba(*(COL_METAL if hover else COL_DARK), 0.85 * alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*(COL_ACCENT if hover else COL_LINE_DIM), alpha)
        cr.set_line_width(1.2)
        cr.stroke()
        _curved_spin_arrow(cr, cx + (1.5 if ccw else -1.5), cy + 3.0, 9.0, ccw,
                           (*(COL_ACCENT if hover else COL_INK), alpha))
        cr.restore()
        _draw_button_focus(cr, w, h, focused, circle=True)
        return True

    return False


def draw_control_wheel_ring(widget, cr):
    """Draw the rear Sony Control Wheel outer knurled ring on self.ring EventBox."""
    alloc = widget.get_allocation()
    w, h = float(alloc.width), float(alloc.height)
    cx, cy = w / 2.0, h / 2.0
    ctx = widget.get_style_context()
    disabled = ctx.has_class('wheel-off')
    dragging = ctx.has_class('wheel-drag')
    alpha = 0.45 if disabled else 1.0

    cr.save()
    cr.new_path()
    r_outer = min(w, h) / 2.0 - 4.0
    r_inner = r_outer * 0.68
    _circle(cr, cx, cy, r_outer + 2.0)
    cr.set_source_rgba(*COL_DARK, alpha)
    cr.fill()

    _circle(cr, cx, cy, r_outer)
    cr.set_source_rgba(*COL_PANEL, alpha)
    cr.fill_preserve()
    cr.set_source_rgba(*(COL_ACCENT if dragging else COL_LINE), alpha)
    cr.set_line_width(2.0 if dragging else 1.5)
    cr.stroke()

    _knurled_edge(cr, cx, cy, r_outer - 1.5, r_inner + 2.0, 48,
                  (*(COL_ACCENT if dragging else COL_LINE_DIM), alpha), 1.1)

    _circle(cr, cx, cy, r_inner)
    cr.set_source_rgba(*COL_DARK, alpha)
    cr.fill_preserve()
    cr.set_source_rgba(*COL_LINE_DIM, alpha)
    cr.set_line_width(1.2)
    cr.stroke()
    cr.restore()
    return False
