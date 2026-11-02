"""Control panel, styled like a 2012-era social site: flat blue top bar, white boxes, grey header strips, blue links."""
import math
import random
import time
from pathlib import Path

from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd

from . import audio, editor, exchange, presets, sound, story
from .effects import REGISTRY, make

TOP_H, SIDE_W, MARGIN, PAD, CAPTION_H, LABEL_W = 38, 390, 14, 10, 62, 118
TIMELINE_H = 276
POOL_W, PAGE_H = 0, 0  # the Studio layout's media pool and page bar
ROUNDING, skin, page = 0.0, "classic", "Edit"
PAGES = ("Camera", "Edit", "Sound", "Library", "Story", "Deliver")
SKINS = {"classic": dict(TOP_H=38, SIDE_W=390, MARGIN=14, PAD=10, CAPTION_H=62, POOL_W=0, PAGE_H=0, ROUNDING=0.0),
         "studio": dict(TOP_H=32, SIDE_W=360, MARGIN=4, PAD=0, CAPTION_H=44, POOL_W=250, PAGE_H=36, ROUNDING=2.0)}


def rgb(h, a=1.0):
    return imgui.ImVec4(int(h[1:3], 16) / 255, int(h[3:5], 16) / 255, int(h[5:7], 16) / 255, a)


def gl_rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


THEMES = {
    "light": dict(BLUE="#3b5998", BLUE_DARK="#29487d", BLUE_PALE="#d8dfea", BLUE_TINT="#eceff5", PAGE="#e9ebee", BOX="#ffffff", BORDER="#d3d6db", STRIP="#f6f7f9",
                  TEXT="#1d2129", LABEL="#4b4f56", GREY="#90949c", LINK="#3b5998", BAR="#3b5998", BAR_DARK="#29487d", EDGE="#bdc7d8", SEP="#dddfe2",
                  GRAB="#6d84b4", SCROLL="#c4cde0", SCROLL_HOVER="#a9b5d1", SCROLL_ACTIVE="#8b9dc3", HOVER="#e1e6f0"),
    # Studio: neutral graphite so the picture is the only colour on screen, as in a grading suite. One accent, and it marks what's active.
    "studio": dict(BLUE="#3f6fb5", BLUE_DARK="#2a2a2c", BLUE_PALE="#d0d0d0", BLUE_TINT="#343438", PAGE="#141415", BOX="#222224", BORDER="#0e0e0f", STRIP="#2b2b2e",
                   TEXT="#d4d4d6", LABEL="#a2a2a6", GREY="#7c7c82", LINK="#7fa6dc", BAR="#1b1b1d", BAR_DARK="#2c2c30", EDGE="#56565c", SEP="#111112",
                   GRAB="#8a8a90", SCROLL="#3a3a3e", SCROLL_HOVER="#4a4a50", SCROLL_ACTIVE="#5c5c62", HOVER="#2f3238"),
    "dark": dict(BLUE="#4e69a2", BLUE_DARK="#2d3a55", BLUE_PALE="#c7d2e8", BLUE_TINT="#2f3a4e", PAGE="#18191a", BOX="#242526", BORDER="#3e4042", STRIP="#303132",
                 TEXT="#e4e6eb", LABEL="#b8bbc1", GREY="#8a8d91", LINK="#8fb0ee", BAR="#1f2a40", BAR_DARK="#2f3f60", EDGE="#5a5d62", SEP="#3e4042",
                 GRAB="#6d84b4", SCROLL="#4a4c50", SCROLL_HOVER="#5e6166", SCROLL_ACTIVE="#74777c", HOVER="#3a3f4b"),
}
RED, GREEN = "#dd3c10", "#42b72a"
globals().update(THEMES["light"])
theme = "light"

FONT = BOLD = None


def set_theme(name):
    """Swap the whole palette. Everything reads these colours when it draws, so the change is immediate."""
    global theme
    theme = name
    globals().update(THEMES[name])
    s = imgui.get_style()
    for a in ("frame_rounding", "grab_rounding", "tab_rounding", "popup_rounding", "scrollbar_rounding", "selectable_rounding"):
        setattr(s, a, ROUNDING)
    C = imgui.Col_
    for col, h in {
        C.text: TEXT, C.text_disabled: GREY, C.window_bg: BOX, C.child_bg: BOX, C.popup_bg: BOX,
        C.border: BORDER, C.frame_bg: BOX, C.frame_bg_hovered: STRIP, C.frame_bg_active: BLUE_TINT,
        C.scrollbar_bg: STRIP, C.scrollbar_grab: SCROLL, C.scrollbar_grab_hovered: SCROLL_HOVER, C.scrollbar_grab_active: SCROLL_ACTIVE,
        C.check_mark: LINK, C.slider_grab: GRAB, C.slider_grab_active: BLUE,
        C.button: STRIP, C.button_hovered: PAGE, C.button_active: BLUE_TINT,
        C.header: BLUE_TINT, C.header_hovered: HOVER, C.header_active: BLUE_TINT,
        C.tab: STRIP, C.tab_hovered: HOVER, C.tab_selected: BOX, C.tab_dimmed: STRIP, C.tab_dimmed_selected: BOX,
        C.tab_selected_overline: BLUE, C.tab_dimmed_selected_overline: BLUE,
        C.separator: SEP, C.text_selected_bg: BLUE_TINT, C.text_link: LINK, C.nav_cursor: LINK,
    }.items():
        s.set_color_(col, rgb(h))
    s.set_color_(C.border_shadow, rgb("#000000", 0.0))


def set_skin(name, palette=None):
    """Classic is the 2012 look; Studio is a Resolve-style workspace. Sizes and fonts switch together."""
    global skin, FONT, BOLD
    skin = name
    globals().update(SKINS[name])
    FONT, BOLD = FONTS[name]
    imgui.get_io().font_default = FONT
    set_theme(palette or ("studio" if name == "studio" else "light"))


FONTS = {}


def setup():
    """Fonts + flat, square style. Call once after imgui.create_context()."""
    global FONT, BOLD
    fonts = imgui.get_io().fonts
    # Verdana (Windows) or its Linux look-alike DejaVu Sans: close to the era's Tahoma/Lucida look.
    for regular, bold_ in (("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                           ("C:/Windows/Fonts/verdana.ttf", "C:/Windows/Fonts/verdanab.ttf")):
        if Path(regular).exists() and Path(bold_).exists():
            FONT = fonts.add_font_from_file_ttf(regular, 13)
            BOLD = fonts.add_font_from_file_ttf(bold_, 13)
            imgui.get_io().font_default = FONT
            break
    FONTS["classic"] = (FONT, BOLD)
    here = Path(__file__).parent / "fonts"
    FONTS["studio"] = (fonts.add_font_from_file_ttf(str(here / "FiraSans-Regular.ttf"), 13), fonts.add_font_from_file_ttf(str(here / "FiraSans-Medium.ttf"), 13))

    s = imgui.get_style()
    for a in ("window_rounding", "child_rounding", "frame_rounding", "popup_rounding", "scrollbar_rounding", "grab_rounding",
              "tab_rounding", "selectable_rounding", "menu_item_rounding", "image_rounding"):
        setattr(s, a, 0.0)
    s.window_border_size = s.child_border_size = s.popup_border_size = s.frame_border_size = 1.0
    s.window_padding, s.frame_padding = imgui.ImVec2(10, 10), imgui.ImVec2(6, 4)
    s.item_spacing, s.item_inner_spacing = imgui.ImVec2(6, 6), imgui.ImVec2(6, 4)
    s.scrollbar_size, s.grab_min_size, s.indent_spacing = 11.0, 9.0, 14.0
    set_theme(theme)


def bold(text, color=None, size=13):
    imgui.push_font(BOLD, size)
    imgui.text_colored(rgb(color or TEXT), text)
    imgui.pop_font()


def blue_button(label):
    for col, h in ((imgui.Col_.button, "#4e69a2"), (imgui.Col_.button_hovered, "#465e91"), (imgui.Col_.button_active, BLUE_DARK),
                   (imgui.Col_.text, "#ffffff"), (imgui.Col_.border, "#435a8b")):
        imgui.push_style_color(col, rgb(h))
    imgui.push_font(BOLD, 13)
    pressed = imgui.button(label)
    imgui.pop_font()
    imgui.pop_style_color(5)
    return pressed


def check(label, v):
    """Square white checkbox with a blue tick (imgui's own one renders with a dark fill here)."""
    p, size = imgui.get_cursor_screen_pos(), imgui.get_frame_height()
    clicked = imgui.invisible_button(label, imgui.ImVec2(size, size))
    dl, b = imgui.get_window_draw_list(), 3
    a0, a1 = imgui.ImVec2(p.x + b, p.y + b), imgui.ImVec2(p.x + size - b, p.y + size - b)
    dl.add_rect_filled(a0, a1, imgui.get_color_u32(rgb(BLUE_TINT if imgui.is_item_hovered() else BOX)))
    dl.add_rect(a0, a1, imgui.get_color_u32(rgb(EDGE)))
    if v:
        s = a1.x - a0.x
        pts = [imgui.ImVec2(a0.x + s * 0.2, a0.y + s * 0.5), imgui.ImVec2(a0.x + s * 0.42, a0.y + s * 0.72), imgui.ImVec2(a0.x + s * 0.8, a0.y + s * 0.25)]
        dl.add_polyline(pts, imgui.get_color_u32(rgb(LINK)), 2.0, 0)
    return clicked, (not v) if clicked else v


def section(title):
    """Grey header strip spanning the box, like the boxed modules of the time."""
    imgui.dummy(imgui.ImVec2(0, 2))
    dl, p, w = imgui.get_window_draw_list(), imgui.get_cursor_screen_pos(), imgui.get_content_region_avail().x
    x0, x1 = p.x - 10, p.x + w + 10
    dl.add_rect_filled(imgui.ImVec2(x0, p.y), imgui.ImVec2(x1, p.y + 24), imgui.get_color_u32(rgb(STRIP)))
    dl.add_line(imgui.ImVec2(x0, p.y), imgui.ImVec2(x1, p.y), imgui.get_color_u32(rgb(BORDER)))
    dl.add_line(imgui.ImVec2(x0, p.y + 24), imgui.ImVec2(x1, p.y + 24), imgui.get_color_u32(rgb(BORDER)))
    imgui.set_cursor_screen_pos(imgui.ImVec2(p.x, p.y + 5))
    bold(title, LABEL)
    imgui.set_cursor_screen_pos(imgui.ImVec2(p.x, p.y + 32))


def links(*items):
    """Row of 'a · b · c' text links; returns the label that was clicked."""
    hit = None
    for i, label in enumerate(items):
        if i:
            imgui.same_line(0, 4)
            imgui.text_colored(rgb(GREY), "·")
            imgui.same_line(0, 4)
        if imgui.text_link(label):
            hit = label
    return hit


ACRONYMS = {"vhs": "VHS", "lut": "LUT", "jpeg": "JPEG", "lcd": "LCD", "hsv": "HSV", "crt": "CRT", "ir": "IR", "agc": "AGC"}


def pretty(name):
    return " ".join(ACRONYMS.get(w, w) for w in name.split("_")).capitalize() if name.split("_")[0] not in ACRONYMS \
        else " ".join(ACRONYMS.get(w, w) for w in name.split("_"))


def bottom(app):
    """Space around the viewer: height below it and width to its left."""
    return (TIMELINE_H + MARGIN if app.editing else 0) + PAGE_H, POOL_W + MARGIN if app.editing and POOL_W else 0


def photo_rects(win, img, below=0):
    """Window-space (x, y, w, h) of the white photo box, the image inside it, and the caption strip."""
    below, left = below if isinstance(below, tuple) else (below, 0)
    ax, ay = MARGIN + left, TOP_H + MARGIN
    aw, ah = win[0] - SIDE_W - 3 * MARGIN - left, win[1] - TOP_H - 2 * MARGIN - below
    s = min((aw - 2 * PAD) / img[0], (ah - 2 * PAD - CAPTION_H) / img[1])
    iw, ih = int(img[0] * s), int(img[1] * s)
    bx = ax + (aw - iw - 2 * PAD) // 2
    box = (bx, ay, iw + 2 * PAD, ih + 2 * PAD + CAPTION_H)
    return box, (bx + PAD, ay + PAD, iw, ih), (bx + PAD, ay + PAD + ih, iw, CAPTION_H + PAD)


# ---- widgets ----

def key_button(app, obj, key):
    """Keyframe diamond: click to add or remove a key at the playhead. Filled = key here, outline = keyed elsewhere."""
    t = app.ed.playhead_source()
    if t is None:
        return
    p, s = imgui.get_cursor_screen_pos(), imgui.get_frame_height()
    if imgui.invisible_button(f"##key{key}", imgui.ImVec2(16, s)):
        editor.toggle_key(obj, key, t)
    cx, cy, r = p.x + 8, p.y + s / 2, 5
    pts = [imgui.ImVec2(cx, cy - r), imgui.ImVec2(cx + r, cy), imgui.ImVec2(cx, cy + r), imgui.ImVec2(cx - r, cy)]
    dl, on, keyed = imgui.get_window_draw_list(), editor.key_at(obj, key, t), key in obj.keys
    color = imgui.get_color_u32(rgb(RED if on or keyed else EDGE))
    if on:
        dl.add_convex_poly_filled(pts, color)
    else:
        dl.add_polyline(pts, color, 1.5, imgui.ImDrawFlags_.closed)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Keyframe at the playhead")


def param_widget(app, e, p):
    v, k = e.v[p.key], p.kind
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), pretty(p.key))
    imgui.same_line(LABEL_W)
    keyable = app.editing and k in ("int", "float")
    imgui.set_next_item_width(-22 if keyable else -1)
    label = f"##{p.key}"
    if keyable:
        changed, val = (imgui.slider_int(label, v, int(p.lo), int(p.hi)) if k == "int" else imgui.slider_float(label, v, p.lo, p.hi, "%.2f"))
        imgui.same_line(0, 4)
        key_button(app, e, p.key)
        return changed, val
    if k == "bool":
        return check(label, v)
    if k == "int":
        return imgui.slider_int(label, v, int(p.lo), int(p.hi))
    if k == "float":
        return imgui.slider_float(label, v, p.lo, p.hi, "%.2f")
    if k == "color":
        return imgui.color_edit3(label, v)
    if k == "vec3":
        return imgui.slider_float3(label, v, p.lo, p.hi, "%.2f")
    if k == "enum":
        opts = p.choices()
        changed, i = imgui.combo(label, opts.index(v) if v in opts else 0, opts)
        return changed, opts[i] if opts else v
    return imgui.input_text(label, v)


def randomize(e):
    for p in e.params:
        k = p.kind
        if k == "float":
            e.v[p.key] = random.uniform(p.lo, p.hi)
        elif k == "int":
            e.v[p.key] = random.randint(int(p.lo), int(p.hi))
        elif k == "bool":
            e.v[p.key] = random.random() < 0.5
        elif k in ("color", "vec3"):
            e.v[p.key] = [random.uniform(p.lo, p.hi) for _ in range(3)]
        elif k == "enum" and p.choices():
            e.v[p.key] = random.choice(p.choices())


def style_row(app, e):
    """Pick a named style for this effect, or save the current settings as one."""
    names = list(presets.styles(e.type))
    imgui.align_text_to_frame_padding()
    bold("Style", LABEL)
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    changed, i = imgui.combo("##style", 0, ["Choose a style..."] + names)
    if changed and i:
        e.v, e.error = make(e.type, presets.styles(e.type)[names[i - 1]]).v, None
    imgui.set_cursor_pos_x(LABEL_W)
    imgui.set_next_item_width(-80)
    _, e.style_name = imgui.input_text("##stylename", getattr(e, "style_name", "My style"))
    imgui.same_line()
    if imgui.button("Save style"):
        presets.save_style(e, e.style_name)
        app.message = f"Saved style \"{e.style_name}\" for {pretty(e.type)}"
    imgui.dummy(imgui.ImVec2(0, 2))


def step_list(app):
    steps, action = app.steps, None
    if not steps:
        imgui.text_colored(rgb(GREY), "No effects yet. Add one below.")
    for i, e in enumerate(steps):
        imgui.push_id(str(id(e)))
        if not hasattr(e, "keys"):
            e.keys = {}
        _, e.enabled = check("##on", e.enabled)
        imgui.same_line()
        imgui.push_font(BOLD, 13)
        imgui.push_style_color(imgui.Col_.text, rgb(LINK if e.enabled else GREY))
        is_open = imgui.collapsing_header(f"{pretty(e.type)}###h")
        imgui.pop_style_color()
        imgui.pop_font()
        if is_open:
            imgui.indent()
            if e.error:
                imgui.text_colored(rgb(RED), e.error)
            style_row(app, e)
            for p in e.params:
                changed, val = param_widget(app, e, p)
                if changed:
                    e.v[p.key], e.error = val, None
                    if p.key in getattr(e, "keys", {}):
                        editor.set_key(e, p.key, app.ed.playhead_source(), val)
            hit = links("Move up", "Move down", "Copy", "Reset", "Shuffle", "Remove")
            if hit:
                action = (i, hit)
            imgui.unindent()
            imgui.dummy(imgui.ImVec2(0, 4))
        imgui.pop_id()
    if action:
        i, a = action
        if a == "Remove":
            steps.pop(i)
        elif a == "Copy":
            steps.insert(i + 1, make(steps[i].type, steps[i].v))
        elif a == "Reset":
            steps[i] = make(steps[i].type)
        elif a == "Shuffle":
            randomize(steps[i])
        else:
            j = i + (-1 if a == "Move up" else 1)
            if 0 <= j < len(steps):
                steps[i], steps[j] = steps[j], steps[i]


# ---- regions ----

FIXED = imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_resize | imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_title_bar \
    | imgui.WindowFlags_.no_saved_settings


def badge(text, color):
    dl, p = imgui.get_window_draw_list(), imgui.get_cursor_screen_pos()
    imgui.push_font(BOLD, 11)
    ts = imgui.calc_text_size(text)
    dl.add_rect_filled(imgui.ImVec2(p.x, p.y + 1), imgui.ImVec2(p.x + ts.x + 10, p.y + ts.y + 5), imgui.get_color_u32(rgb(color)))
    imgui.set_cursor_screen_pos(imgui.ImVec2(p.x + 5, p.y + 3))
    imgui.text_colored(rgb("#ffffff"), text)
    imgui.pop_font()
    imgui.same_line(0, 14)


def nav_tab(app, label, tab):
    """Text tab in the blue bar. The tab you're on gets the darker block behind it."""
    imgui.push_font(BOLD, 13)
    size = imgui.calc_text_size(label)
    p = imgui.ImVec2(imgui.get_cursor_screen_pos().x, 0)
    imgui.set_cursor_screen_pos(p)
    box = imgui.ImVec2(size.x + 28, TOP_H)
    if imgui.invisible_button(f"##{tab}", box):
        if app.tab != tab:
            app.ed.pause()
            app.tab, app.message = tab, ""
            if tab == "editor" and app.ed.clip:
                app.save_name = app.ed.clip.preset_name
    dl = imgui.get_window_draw_list()
    if app.tab == tab or imgui.is_item_hovered():
        dl.add_rect_filled(p, imgui.ImVec2(p.x + box.x, TOP_H), imgui.get_color_u32(rgb(BAR_DARK)))
    dl.add_text(imgui.ImVec2(p.x + 14, (TOP_H - size.y) / 2), imgui.get_color_u32(rgb("#ffffff" if app.tab == tab else "#d8dfea")), label)
    imgui.pop_font()
    imgui.same_line(0, 0)


def theme_toggle(app):
    imgui.same_line(0, 18)
    imgui.push_style_color(imgui.Col_.text_link, rgb("#d8dfea"))
    if skin == "classic":
        imgui.set_cursor_pos_y(11)
        if imgui.text_link("Light mode" if theme == "dark" else "Dark mode"):
            app.set_look("classic", "light" if theme == "dark" else "dark")
        imgui.same_line(0, 14)
        if imgui.text_link("Studio view"):
            app.set_look("studio", "studio")
    elif imgui.text_link("Classic view"):
        app.set_look("classic", "light")
    imgui.pop_style_color()


def top_bar(app, w):
    imgui.set_next_window_pos(imgui.ImVec2(0, 0))
    imgui.set_next_window_size(imgui.ImVec2(w, TOP_H))
    imgui.push_style_color(imgui.Col_.window_bg, rgb(BAR))
    imgui.push_style_color(imgui.Col_.border, rgb(BAR_DARK))
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(max(MARGIN, 10), 8))
    imgui.begin("##top", flags=FIXED | imgui.WindowFlags_.no_scrollbar)
    imgui.push_font(BOLD, 15 if skin == "studio" else 20)
    imgui.text_colored(rgb("#ffffff"), "badcamera")
    imgui.pop_font()
    imgui.same_line(0, 24)
    if skin == "classic":
        nav_tab(app, "Camera", "camera")
        nav_tab(app, "Editor", "editor")
    theme_toggle(app)

    status = f"{app.fps:.0f} fps   camera {app.cam.fps:.0f} fps   {app.size[0]}x{app.size[1]}"
    badges = []
    if app.rec.proc:
        t = int(time.time() - app.rec_t0)
        badges.append((f"REC {t // 60}:{t % 60:02d}", "#e02b2b"))
    if app.vcam.cam:
        badges.append(("VIRTUAL CAM ON", GREEN))
    imgui.push_font(BOLD, 11)
    badge_w = sum(imgui.calc_text_size(b).x + 24 for b, _ in badges)
    imgui.pop_font()
    imgui.same_line(w - max(MARGIN, 10) - imgui.calc_text_size(status).x - badge_w)
    imgui.set_cursor_pos_y(TOP_H // 2 - 8)
    for text, color in badges:
        badge(text, color)
    imgui.text_colored(rgb("#d8dfea"), status)
    imgui.end()
    imgui.pop_style_var()
    imgui.pop_style_color(2)


def camera_caption(app):
    bold(app.presets[app.preset_i]["name"], LINK, 15)
    enabled = sum(e.enabled for e in app.steps)
    imgui.same_line()
    imgui.text_colored(rgb(GREY), f"  {enabled} effect{'s' * (enabled != 1)}  ·  {app.argv.source}")
    hit = links("Take photo", "Stop recording" if app.rec.proc else "Record video",
                "Turn off virtual cam" if app.vcam.cam else "Turn on virtual cam",
                "Show effect" if app.bypass else "Show original", "Unmirror" if app.mirror else "Mirror")
    if hit == "Take photo":
        app.want_snapshot = True
    elif hit in ("Record video", "Stop recording"):
        app.toggle_record()
    elif hit and "virtual cam" in hit:
        app.toggle_vcam()
    elif hit in ("Show effect", "Show original"):
        app.bypass = not app.bypass
    elif hit in ("Mirror", "Unmirror"):
        app.mirror = not app.mirror


def timecode(t):
    return f"{int(t) // 60}:{int(t) % 60:02d}.{int(t * 100) % 100:02d}"


def editor_caption(app):
    ed = app.ed
    clip = ed.clip
    bold(clip.name if clip else "Editor", LINK, 15)
    imgui.same_line()
    imgui.text_colored(rgb(GREY), f"  {timecode(ed.t)} / {timecode(ed.tl.duration)}" + (f"  ·  {clip.preset_name}" if clip else ""))
    if ed.exporter:
        ex = ed.exporter
        more = f" ({len(ed.queue)} more)" if ed.queue else ""
        imgui.progress_bar(ex.n / ex.total, imgui.ImVec2(220, 16), f"Exporting {100 * ex.n // ex.total}%{more}" if ex.audio_ready else "Rendering audio...")
        imgui.same_line()
        if imgui.text_link("Cancel"):
            ex.cancel()
            app.message, ed.exporter = "Export cancelled", None
            ed.next_job()
        return
    hit = links("Pause" if ed.playing else "Play", "Take photo", "Show effect" if app.bypass else "Show original")
    if hit in ("Play", "Pause"):
        ed.toggle_play()
    elif hit == "Take photo":
        app.want_snapshot = True
    elif hit in ("Show effect", "Show original"):
        app.bypass = not app.bypass
    if ed.recover:
        hit = links("Recover last session", "Discard it")
        if hit == "Recover last session":
            missing = ed.recover_autosave()
            app.message = f"Missing files: {', '.join(missing)}" if missing else "Recovered"
        elif hit:
            ed.recover = False
            ed.clean_exit()


def caption(app, w, h):
    _, _, (cx, cy, cw, ch) = photo_rects((w, h), app.view_size(), bottom(app))
    imgui.set_next_window_pos(imgui.ImVec2(cx, cy))
    imgui.set_next_window_size(imgui.ImVec2(cw, ch))
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0, 8))
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
    imgui.begin("##caption", flags=FIXED | imgui.WindowFlags_.no_background | imgui.WindowFlags_.no_scrollbar)
    if app.editing:
        editor_caption(app)
    else:
        camera_caption(app)
    if app.message:
        imgui.text_colored(rgb(GREY), app.message)
    elif not app.camtex and not app.editing:
        imgui.text_colored(rgb(GREY), "Waiting for the camera...")
    imgui.end()
    imgui.pop_style_var(2)


def open_dialog(app, title, filters, done, multi=False, save=False, folder=False):
    if folder:
        app.dialog = (pfd.select_folder(title), done)
    elif save:
        app.dialog = (pfd.save_file(title, "", filters), done)
    else:
        app.dialog = (pfd.open_file(title, "", filters, pfd.opt.multiselect if multi else pfd.opt.none), done)


def slider_row(app, tx, key, label, lo, hi):
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), label)
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-22 if app.editing else -1)
    changed, val = imgui.slider_float(f"##{key}", tx.v[key], lo, hi, "%.2f")
    if changed:
        tx.v[key] = val
        if key in tx.keys:
            editor.set_key(tx, key, app.ed.playhead_source(), val)
    if app.editing:
        imgui.same_line(0, 4)
        key_button(app, tx, key)


def transform_panel(app):
    tx = app.tx
    section("Transform")
    if tx is None:
        imgui.text_colored(rgb(GREY), "Select a clip to move it.")
        return
    for key, label, lo, hi in (("rotate", "Rotate", -180, 180), ("stretch", "Stretch", 0.1, 3), ("squash", "Squash", 0.1, 3),
                               ("move_x", "Move X", -1, 1), ("move_y", "Move Y", -1, 1), ("zoom", "Zoom", 0.1, 8)):
        slider_row(app, tx, key, label, lo, hi)
    hit = links("Rotate left", "Rotate right", "Flip H", "Flip V", "Reset")
    if hit == "Rotate left":
        tx.v["rotate"] = (tx.v["rotate"] - 90 + 180) % 360 - 180
    elif hit == "Rotate right":
        tx.v["rotate"] = (tx.v["rotate"] + 90 + 180) % 360 - 180
    elif hit == "Flip H":
        tx.v["flip_h"] = not tx.v["flip_h"]
    elif hit == "Flip V":
        tx.v["flip_v"] = not tx.v["flip_v"]
    elif hit == "Reset":
        tx.v.update(editor.transform.new())
        tx.keys.clear()
    imgui.text_colored(rgb(GREY), "Or drag the picture to move it, scroll to zoom.")


def presets_panel(app):
    section("Presets")
    imgui.begin_child("##presets", imgui.ImVec2(0, 190), imgui.ChildFlags_.borders)
    n_builtin = app.n_builtin
    for i, p in enumerate(app.presets):
        if i == n_builtin:
            imgui.dummy(imgui.ImVec2(0, 2))
            bold("YOUR PRESETS", GREY, 11)
        selected = i == app.preset_i
        imgui.push_style_color(imgui.Col_.text, rgb(TEXT if selected else LINK))
        imgui.push_font(BOLD if selected else FONT, 13)
        if imgui.selectable(f"{p['name']}##{i}", selected)[0]:
            app.load_preset(i)
        imgui.pop_font()
        imgui.pop_style_color()
    imgui.end_child()
    imgui.set_next_item_width(SIDE_W - 2 * 10 - 120)
    _, app.save_name = imgui.input_text("##name", app.save_name)
    imgui.same_line()
    if blue_button("Save"):
        app.message = f"Saved to {presets.save(app.save_name, app.steps)}"
        app.reload_presets(app.save_name)
    imgui.same_line()
    if imgui.button("Revert"):
        app.load_preset(app.preset_i)
    current = app.presets[app.preset_i]
    extra = ["New tape copy"] if presets.uses_old_vhs(current) else []
    hit = links("Share preset", "Import preset", *extra)
    if hit == "Share preset":
        open_dialog(app, "Share preset", ["Preset", "*.json"], lambda path: presets.export_file(current, path), save=True)
    elif hit == "Import preset":
        open_dialog(app, "Import preset", ["Preset", "*.json"], lambda paths: app.reload_presets(app.import_preset(paths[0])))
    elif hit == "New tape copy":
        name = presets.upgrade_copy(current)
        app.message = f"Made \"{name}\". Your original is unchanged."
        app.reload_presets(name)


def effects_panel(app):
    section("Effects")
    if app.editing and not app.ed.clip:
        imgui.text_colored(rgb(GREY), "Select a clip on the timeline to add effects.")
        return
    step_list(app)
    imgui.dummy(imgui.ImVec2(0, 2))
    types = sorted(REGISTRY)
    imgui.set_next_item_width(SIDE_W - 2 * 10 - 110)
    _, app.add_i = imgui.combo("##add", app.add_i, [pretty(t) for t in types])
    imgui.same_line()
    if blue_button("Add effect"):
        app.steps.append(make(types[app.add_i]))
    if app.editing and len(app.ed.tl.clips) > 1 and imgui.text_link("Apply these effects to all clips"):
        app.apply_to_all()


def live_panel(app):
    section("Live monitor")
    devices = sorted(str(p) for p in Path("/dev").glob("video*")) or ["0", "1", "2"]
    new = combo_row("Input", "##input", app.argv.source, devices)
    if new != app.argv.source:
        app.switch_source(new)
    app.clean_on = check_row("Also record the clean feed", "##clean", app.clean_on)
    imgui.text_colored(rgb(GREY), "A capture card shows up here like a camera.")


def recording_panel(app):
    live_panel(app)
    section("Recording")
    names, ids = ["No microphone"], [None]
    try:
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                names.append(d["name"])
                ids.append(i)
    except Exception:  # no PortAudio on this machine: record silently
        pass
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), "Microphone")
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    changed, i = imgui.combo("##mic", ids.index(app.mic_device) if app.mic_device in ids else 0, names)
    if changed:
        app.mic_device = ids[i]
    if app.mic_device is not None:
        imgui.align_text_to_frame_padding()
        imgui.text_colored(rgb(LABEL), "Audio effect")
        imgui.same_line(LABEL_W)
        imgui.set_next_item_width(-1)
        names_ = audio.NAMES
        changed, i = imgui.combo("##micfx", names_.index(app.mic_audio) if app.mic_audio in names_ else 0, names_)
        if changed:
            app.mic_audio = None if names_[i] == audio.ORIGINAL else names_[i]


def audio_panel(app):
    clip = app.ed.clip
    section("Audio")
    if not clip:
        return
    if not clip.info["audio"] and not clip.sync_path:
        imgui.text_colored(rgb(GREY), "This clip has no sound.")
        return
    if imgui.text_link("Sync recorder take"):
        def picked(paths):
            def work():
                offset, score = app.ed.sync_take(clip, paths[0])
                return f"Synced at {offset:+.3f} s, match {score * 100:.0f}%" + ("" if score > 0.1 else ". That's a weak match, check by ear")
            app.background(work)
        open_dialog(app, "Pick the separate audio take", ["Audio", "*.wav *.mp3 *.flac *.m4a *.aiff"], picked)
    if clip.sync_path:
        imgui.same_line()
        if imgui.text_link("Use camera sound"):
            clip.sync_path = ""
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), "Hardware")
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    changed, i = imgui.combo("##audio", audio.NAMES.index(clip.audio), audio.NAMES)
    if changed:
        clip.audio, clip.auto_audio = audio.NAMES[i], False
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), "Tape noise")
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    steps = audio.NOISE_STEPS
    changed, i = imgui.slider_int("##noise", steps.index(clip.noise), 0, len(steps) - 1, f"{int(clip.noise * 100)}%")
    if changed:
        clip.noise = steps[i]
    clip.denoise = combo_row("Clean up take", "##denoise", clip.denoise, list(audio.DENOISE))
    clip.space = combo_row("Room", "##room", clip.space, list(sound.ROOMS))
    _, clip.wet = imgui_slider("Mix", "##wet", clip.wet, 0, 1)
    _, clip.gain = imgui_slider("Volume", "##gain", clip.gain, 0, 2)
    imgui.same_line(LABEL_W)
    imgui.set_cursor_pos_x(LABEL_W)
    _, clip.mute = check("##mute", clip.mute)
    imgui.same_line()
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), "Mute")
    key = (clip.path, clip.audio, clip.noise, clip.denoise)
    if key in app.ed.worker.pending:
        imgui.text_colored(rgb(GREY), "Rendering this sound... playing it clean for now.")
    elif key in app.ed.worker.errors:
        imgui.text_colored(rgb(RED), app.ed.worker.errors[key][:120])


def combo_row(label, id_, value, options):
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), label)
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    changed, i = imgui.combo(id_, options.index(value) if value in options else 0, options)
    return options[i] if changed else value


def check_row(label, id_, value):
    _, value = check(id_, value)
    imgui.same_line()
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), label)
    return value


def imgui_slider(label, id_, v, lo, hi):
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), label)
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    return imgui.slider_float(id_, v, lo, hi, "%.2f")


def transition_panel(app):
    ed = app.ed
    if not ed.clip or ed.sel >= len(ed.tl.clips) - 1:
        return
    section("Transition to next clip")
    c = ed.clip
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), "Type")
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    changed, i = imgui.combo("##trans", editor.TRANSITIONS.index(c.trans), editor.TRANSITIONS)
    if changed:
        c.trans = editor.TRANSITIONS[i]
    if c.trans != "Cut":
        _, c.trans_d = imgui_slider("Length", "##transd", c.trans_d, 0.1, 3)


def export_panel(app):
    ed = app.ed
    section("Export")
    ed.tl.fmt = combo_row("Format", "##fmt", ed.tl.fmt, list(editor.FORMATS))
    if blue_button("Export video"):
        app.start_export()
    imgui.same_line()
    if imgui.button("Export stems"):
        app.export_stems()
    section("Send to Resolve")
    hit = links("FCPXML", "OTIO", "EDL")
    if hit:
        ext, fn = {"FCPXML": ("fcpxml", exchange.export_fcpxml), "OTIO": ("otio", exchange.export_otio), "EDL": ("edl", exchange.export_edl)}[hit]
        open_dialog(app, f"Export {hit}", [hit, f"*.{ext}"], lambda path: setattr(app, "message", f"Wrote {fn(ed.tl, path if path.endswith(ext) else f'{path}.{ext}')}"), save=True)
    section("Credits")
    text_, warn = sound.credits(ed.tl, app.lib_items())
    for w in warn:
        imgui.text_colored(rgb(RED), f"Licence: {w}")
    if not warn:
        imgui.text_colored(rgb(GREY), "No licence problems in the sound tracks.")
    if imgui.text_link("Save sound credits"):
        open_dialog(app, "Save credits", ["Text", "*.txt"], lambda path: Path(path).write_text(text_ or "No credits needed.", encoding="utf-8"), save=True)
    section("Render queue")
    app.queue_variant = combo_row("Version", "##variant", app.queue_variant, list(editor.VARIANTS))
    if imgui.button("Add to queue"):
        ed.enqueue(app.queue_variant)
    imgui.same_line()
    if ed.queue and blue_button("Start queue"):
        ed.pause()
        ed.next_job()
    for i, job in enumerate(ed.queue):
        imgui.push_id(i)
        imgui.text_colored(rgb(GREY), job["name"])
        imgui.same_line()
        if imgui.text_link("Remove"):
            ed.queue.pop(i)
            imgui.pop_id()
            break
        imgui.pop_id()
    section("Project")
    hit = links("Save", "Open", "Bundle")
    if hit == "Save":
        def save(path):
            path = path if path.endswith(".bcproj") else f"{path}.bcproj"
            editor.save_project(ed.tl, path)
            ed.project_path, app.message = path, f"Saved {path}"
        if ed.project_path:
            save(ed.project_path)
        else:
            open_dialog(app, "Save project", ["BadCamera project", "*.bcproj"], save, save=True)
    elif hit == "Open":
        open_dialog(app, "Open project", ["BadCamera project", "*.bcproj"], lambda paths: app.open_project(paths[0]))
    elif hit == "Bundle":
        def bundle(folder):
            app.message = f"Bundled to {editor.bundle_project(ed.tl, folder)}"
        open_dialog(app, "Pick an empty folder for the bundle", [], bundle, folder=True)


def overlay_panel(app):
    ed, c = app.ed, app.ed.clip
    if ed.over_sel is None or c is None:
        return
    section("Overlay")
    for i, label in enumerate(("X", "Y", "Width", "Height")):
        _, c.rect[i] = imgui_slider(label, f"##rect{i}", c.rect[i], 0, 1)
    _, c.opacity = imgui_slider("Opacity", "##opacity", c.opacity, 0, 1)
    if imgui.text_link("Remove overlay"):
        ed.tl.overlays.pop(ed.over_sel)
        ed.over_sel = None


def sound_panel(app):
    ed = app.ed
    section("Sound tracks")
    if blue_button("Add sound"):
        open_dialog(app, "Add sound", ["Audio", "*.wav *.mp3 *.flac *.m4a *.ogg *.aac"], lambda paths: [ed.add_sound(p) for p in paths], multi=True)
    imgui.same_line()
    imgui.text_colored(rgb(GREY), "or drag one from the Library")
    snd = ed.sound
    if snd:
        bold(snd.name, LABEL)
        tracks = list(editor.SOUND_TRACKS)
        snd.track = tracks.index(combo_row("Track", "##sndtrack", tracks[snd.track], tracks))
        snd.audio = combo_row("Hardware", "##sndaudio", snd.audio, [editor.MATCH] + audio.NAMES)
        snd.space = combo_row("Room", "##sndroom", snd.space, list(sound.ROOMS))
        _, snd.gain = imgui_slider("Volume", "##sndgain", snd.gain, 0, 2)
        _, snd.fade_in = imgui_slider("Fade in", "##fadein", snd.fade_in, 0, min(snd.length, 10))
        _, snd.fade_out = imgui_slider("Fade out", "##fadeout", snd.fade_out, 0, min(snd.length, 10))
        snd.mute = check_row("Mute", "##sndmute", snd.mute)
        if imgui.text_link("Add volume point at playhead"):
            snd.points.append([snd.start + max(ed.t - snd.at, 0.0), 1.0])
        if snd.points:
            for i, q in enumerate(sorted(snd.points)):
                imgui.push_id(f"pt{i}")
                _, q[1] = imgui_slider(timecode(q[0]), "##pt", q[1], 0, 2)
                imgui.pop_id()
            if imgui.text_link("Clear volume points"):
                snd.points.clear()
    section("Levels")
    level_meter(app)
    app.loud_target = combo_row("Target", "##loud", app.loud_target, list(sound.LOUDNESS))
    if imgui.button("Match loudness"):
        def work():
            lufs, peak, gain = ed.set_loudness(sound.LOUDNESS[app.loud_target])
            return f"Was {lufs:.1f} LUFS, peak {peak:.1f} dB. Master {gain:+.1f} dB"
        app.background(work)
    imgui.same_line()
    imgui.text_colored(rgb(GREY), f"Master {ed.tl.master:+.1f} dB")


def level_meter(app, width=None):
    """Peak bars for the last audio buffer. Green is safe, amber is hot, red is at the ceiling."""
    p = imgui.get_cursor_screen_pos()
    w = width or imgui.get_content_region_avail().x
    dl = imgui.get_window_draw_list()
    for ch, v in enumerate(app.ed.meter):
        y = p.y + ch * 8
        db = 20 * math.log10(max(v, 1e-5))
        x = max(min((db + 60) / 60, 1.0), 0.0)
        dl.add_rect_filled(imgui.ImVec2(p.x, y), imgui.ImVec2(p.x + w, y + 6), imgui.get_color_u32(rgb(STRIP)))
        color = "#dd3c10" if db > -1 else "#e0a020" if db > -9 else "#42b72a"
        dl.add_rect_filled(imgui.ImVec2(p.x, y), imgui.ImVec2(p.x + w * x, y + 6), imgui.get_color_u32(rgb(color)))
    imgui.dummy(imgui.ImVec2(w, 18))


def library_panel(app):
    ed = app.ed
    section("Sound library")
    items = app.lib_items()
    imgui.set_next_item_width(-1)
    _, app.lib_query = imgui.input_text_with_hint("##libq", "Search: door, breath, wind...", app.lib_query)
    cats = ["All"] + sorted({i["category"] for i in items})
    app.lib_cat = combo_row("Category", "##libcat", app.lib_cat, cats)
    found = sound.search_local(items, app.lib_query, app.lib_cat)
    if app.fs_key and blue_button("Get sound pack"):
        app.get_sound_pack()
    if app.fs_key:
        imgui.same_line()
    if imgui.button("Add sound folder"):
        open_dialog(app, "Pick a folder of sounds", [], app.add_sound_folder, folder=True)
    imgui.same_line()
    if imgui.button("Stop"):
        ed.stop_preview()
    imgui.text_colored(rgb(GREY), f"{len(found)} sounds")
    imgui.begin_child("##libitems", imgui.ImVec2(0, 240), imgui.ChildFlags_.borders)
    for i in found:
        imgui.push_id(i["path"])
        k = sound.licence_kind(i["license"])
        if imgui.small_button("Play"):
            ed.preview_sound(i["path"])
        imgui.same_line()
        if imgui.small_button("Add"):
            ed.add_sound(i["path"], track=1)
        imgui.same_line()
        imgui.selectable(i["name"], False)
        if imgui.is_item_active() and imgui.is_mouse_dragging(imgui.MouseButton_.left):
            ed.lib_drag = i  # dropped on a sound lane in the timeline
        if imgui.is_item_hovered():
            imgui.set_tooltip(f"{i['license']}\n{i['author']}, {i['source']}\nDrag onto a sound track")
        if not k["commercial"]:
            imgui.same_line()
            imgui.text_colored(rgb(RED), "Resolve" if k["label"] == "Finish in Resolve" else "NC")
        imgui.pop_id()
    imgui.end_child()
    section("Freesound")
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), "API key")
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    _, app.fs_key = imgui.input_text("##fskey", app.fs_key, imgui.InputTextFlags_.password)
    if not app.fs_key:
        imgui.text_colored(rgb(GREY), "Free key: freesound.org/apiv2/apply")
    imgui.set_next_item_width(-70)
    _, app.fs_query = imgui.input_text_with_hint("##fsq", "Search Freesound", app.fs_query)
    imgui.same_line()
    if imgui.button("Search") and app.fs_key:
        app.freesound_search()
    app.fs_any = check_row("Include licences other than CC0", "##fsany", app.fs_any)
    for r in app.fs_results:
        imgui.push_id(str(r["id"]))
        k = sound.licence_kind(r["license"])
        if imgui.small_button("Get"):
            app.freesound_add(r)
        imgui.same_line()
        imgui.text_colored(rgb(RED if not k["commercial"] else TEXT), f"{r['name'][:30]}  {r['duration']:.0f}s  {k['label']}")
        imgui.pop_id()


def clip_story_panel(app):
    c = app.ed.clip
    section("This clip")
    if not c:
        imgui.text_colored(rgb(GREY), "Select a clip first.")
        return
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), "Date and time")
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    _, c.story = imgui.input_text_with_hint("##story", "1996-07-21 21:14", c.story)
    if c.story and story.parse_when(c.story) is None:
        imgui.text_colored(rgb(RED), "Use the form 1996-07-21 21:14")
    else:
        imgui.text_colored(rgb(GREY), "Blank carries on from the clip before.")
    c.power_on = check_row("Camera powers on", "##pon", c.power_on)
    c.power_off = check_row("Camera powers off", "##poff", c.power_off)
    c.battery = check_row("Battery dies at the end", "##batt", c.battery)
    c.motion = combo_row("Handheld", "##motion", c.motion, list(story.MOTIONS))
    if c.motion != "None":
        _, c.motion_amount = imgui_slider("Amount", "##mamt", c.motion_amount, 0, 2)
    if c.motion == "From video":
        imgui.text_colored(rgb(GREY), Path(c.motion_file).name if c.motion_file else "Pick a clip of you walking with a camera.")
        if imgui.text_link("Pick motion clip"):
            app.pick_motion(c)
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb(LABEL), "Shot note")
    imgui.set_next_item_width(-1)
    _, c.note = imgui.input_text_multiline("##note", c.note, imgui.ImVec2(0, 48))


def damage_panel(app):
    ed, tl = app.ed, app.ed.tl
    section("Tape age")
    _, tl.age_start = imgui_slider("Start of film", "##age0", tl.age_start, 0, 1)
    _, tl.age_end = imgui_slider("End of film", "##age1", tl.age_end, 0, 1)
    section("Scare moment")
    if blue_button("Add scare at playhead"):
        items = app.lib_items()
        ed.add_scare(next((i for i in items if i["category"] == "Stingers"), None))
    imgui.text_colored(rgb(GREY), "A stinger, a camera jolt and a tape fault together.")
    section("Realism pass")
    _, app.realism_amount = imgui_slider("Amount", "##rea", app.realism_amount, 0.1, 3)
    _, app.realism_seed = imgui.input_int("Variation", app.realism_seed)
    if imgui.button("Scatter small faults"):
        story.realism_pass(tl, app.realism_seed, app.realism_amount)
    section("Damage events")
    app.event_kind = combo_row("Fault", "##kind", app.event_kind, story.EVENT_KINDS)
    _, app.event_amount = imgui_slider("Strength", "##eamt", app.event_amount, 0.1, 1)
    _, app.event_length = imgui_slider("Seconds", "##elen", app.event_length, 0.1, 6)
    if blue_button("Add at playhead"):
        tl.events.append({"t": ed.t, "d": app.event_length, "kind": app.event_kind, "amount": app.event_amount})
        tl.events.sort(key=lambda e: e["t"])
    for i, e in enumerate(tl.events):
        imgui.push_id(f"ev{i}")
        if imgui.text_link(f"{timecode(e['t'])}  {e['kind']}"):
            ed.seek(e["t"])
        imgui.same_line()
        if imgui.text_link("Remove"):
            tl.events.pop(i)
            imgui.pop_id()
            break
        imgui.pop_id()


def script_panel(app):
    ed, tl = app.ed, app.ed.tl
    section("Script")
    if imgui.button("Import script"):
        def load(paths):
            tl.scenes = story.parse_script(Path(paths[0]).read_text(encoding="utf-8", errors="replace"))
            app.message = f"Found {len(tl.scenes)} scenes"
        open_dialog(app, "Import a screenplay", ["Screenplay", "*.fountain *.txt"], load)
    if tl.scenes:
        shot = {c.scene for c in tl.clips if c.scene}
        imgui.same_line()
        imgui.text_colored(rgb(GREY), f"{len(shot)} of {len(tl.scenes)} scenes covered")
        c = ed.clip
        imgui.begin_child("##scenes", imgui.ImVec2(0, 150), imgui.ChildFlags_.borders)
        for sc in tl.scenes:
            imgui.push_id(sc["n"])
            have = sc["n"] in shot
            imgui.text_colored(rgb(TEXT if have else RED), f"{sc['n']}. {sc['title'][:34]}")
            if c:
                imgui.same_line()
                if imgui.small_button("Mine" if c.scene == sc["n"] else "Attach"):
                    c.scene = 0 if c.scene == sc["n"] else sc["n"]
            imgui.pop_id()
        imgui.end_child()
        if imgui.text_link("Put clips in script order"):
            tl.clips.sort(key=lambda k: k.scene or 10 ** 6)


def reels_panel(app):
    ed, tl = app.ed, app.ed.tl
    section("Reels")
    names = sorted({ed.reel, *tl.reels})
    for n in names:
        imgui.push_id(n)
        if imgui.text_link(n) and n != ed.reel:
            ed.switch_reel(n)
        if n == ed.reel:
            imgui.same_line()
            imgui.text_colored(rgb(GREY), "(open)")
        else:
            imgui.same_line()
            if imgui.small_button("Render into this reel"):
                if ed.nest_reel(n):
                    app.message = "Reel added to the queue. It joins this timeline when it finishes."
                    ed.next_job()
        imgui.pop_id()
    imgui.set_next_item_width(-70)
    _, app.reel_name = imgui.input_text("##reelname", app.reel_name)
    imgui.same_line()
    if imgui.button("New") and app.reel_name.strip():
        ed.switch_reel(app.reel_name.strip())


def markers_panel(app):
    ed, tl = app.ed, app.ed.tl
    section("Markers")
    imgui.set_next_item_width(-70)
    _, app.marker_text = imgui.input_text_with_hint("##marker", "Scene 12, take 3", app.marker_text)
    imgui.same_line()
    if imgui.button("Add"):
        app.add_marker()
    for i, m in enumerate(tl.markers):
        imgui.push_id(f"mk{i}")
        if imgui.text_link(f"{timecode(m['t'])}  {m['label'] or 'Marker'}"):
            ed.seek(m["t"])
        imgui.same_line()
        if imgui.text_link("Remove"):
            tl.markers.pop(i)
            imgui.pop_id()
            break
        imgui.pop_id()


def cards_panel(app):
    ed = app.ed
    section("Title card")
    names = list(story.CARDS)
    new = combo_row("Style", "##card", app.card_name, names)
    if new != app.card_name:
        app.card_name, app.card_text = new, story.CARDS[new][2]
    imgui.set_next_item_width(-1)
    _, app.card_text = imgui.input_text_multiline("##cardtext", app.card_text, imgui.ImVec2(0, 62))
    imgui.text_colored(rgb(GREY), "Use | for a new line.")
    _, app.card_seconds = imgui_slider("Seconds", "##cards", app.card_seconds, 0.5, 10)
    if blue_button("Add card"):
        ed.add_card(app.card_name, app.card_text.replace("\n", "|"), app.card_seconds)
    section("CCTV")
    app.cctv_mode = combo_row("Layout", "##cctv", app.cctv_mode, ["Quad split", "Switcher"])
    if app.cctv_mode == "Switcher":
        _, app.cctv_every = imgui_slider("Cut every", "##every", app.cctv_every, 1, 15)
    if imgui.button("Pick up to 4 videos"):
        open_dialog(app, "Pick CCTV feeds", ["Videos", " ".join(f"*{t}" for t in editor.VIDEO_TYPES)],
                    lambda paths: ed.cctv(paths, app.cctv_mode, app.cctv_every), multi=True)


def sidebar(app, w, h):
    below = (TIMELINE_H + MARGIN + PAGE_H if app.editing else PAGE_H) if skin == "studio" else 0
    imgui.set_next_window_pos(imgui.ImVec2(w - SIDE_W - MARGIN, TOP_H + MARGIN))
    imgui.set_next_window_size(imgui.ImVec2(SIDE_W, h - TOP_H - 2 * MARGIN - below))
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(10, 0))
    imgui.begin("##side", flags=FIXED)

    if skin == "studio" and app.editing:  # the page bar picks the panels, so there are no tabs in here
        for panel in STUDIO_PANELS[page]:
            panel(app)
    elif app.editing:
        imgui.dummy(imgui.ImVec2(0, 4))
        if imgui.begin_tab_bar("##sidetabs"):
            for label, panels in (("Look", (transform_panel, overlay_panel, presets_panel, effects_panel)),
                                  ("Sound", (audio_panel, sound_panel)), ("Library", (library_panel,)),
                                  ("Story", (clip_story_panel, script_panel, reels_panel, damage_panel, markers_panel, cards_panel)),
                                  ("Finish", (transition_panel, export_panel))):
                if imgui.begin_tab_item(label)[0]:
                    for panel in panels:
                        panel(app)
                    imgui.end_tab_item()
            imgui.end_tab_bar()
    else:
        transform_panel(app)
        presets_panel(app)
        effects_panel(app)
        recording_panel(app)

    section("Keyboard")
    keys = (("Space", "play / pause"), ("S", "cut at playhead"), ("M", "add a marker"), ("Delete", "remove clip"), ("Ctrl+Z", "undo (Shift to redo)"),
            ("Left / Right", "one frame"), ("B", "show original")) if app.editing else \
        (("Left / Right", "change preset"), ("Space", "take photo"), ("R", "record video"),
         ("V", "virtual cam on/off"), ("B", "show original"), ("F", "fullscreen"))
    for key, what in keys:
        bold(key, LABEL)
        imgui.same_line(LABEL_W)
        imgui.text_colored(rgb(GREY), what)
    imgui.dummy(imgui.ImVec2(0, 6))
    imgui.text_colored(rgb(GREY), "badcamera © 2026  ·  photos and videos go to captures/")
    imgui.dummy(imgui.ImVec2(0, 8))
    imgui.end()
    imgui.pop_style_var()


STUDIO_PANELS = {"Edit": (transform_panel, overlay_panel, presets_panel, effects_panel), "Sound": (audio_panel, sound_panel), "Library": (library_panel,),
                 "Story": (clip_story_panel, script_panel, reels_panel, damage_panel, markers_panel, cards_panel), "Deliver": (transition_panel, export_panel)}


def media_pool(app, w, h):
    """Every file in the project. Click to put it on the end of the timeline."""
    ed = app.ed
    imgui.set_next_window_pos(imgui.ImVec2(MARGIN, TOP_H + MARGIN))
    imgui.set_next_window_size(imgui.ImVec2(POOL_W, h - TOP_H - 3 * MARGIN - TIMELINE_H - PAGE_H))
    imgui.begin("##pool", flags=FIXED)
    bold("Media Pool", LABEL)
    imgui.same_line(POOL_W - 76)
    if imgui.button("Import"):
        open_dialog(app, "Add videos", ["Videos", " ".join(f"*{t}" for t in editor.VIDEO_TYPES)], app.add_files, multi=True)
    seen, items = set(), []
    for c in ed.tl.clips + ed.tl.overlays:
        if c.path not in seen:
            seen.add(c.path)
            items.append(c)
    if not items:
        imgui.text_colored(rgb(GREY), "Drop videos here.")
    for c in items:
        imgui.push_id(c.path)
        p = imgui.get_cursor_screen_pos()
        if imgui.invisible_button("##item", imgui.ImVec2(POOL_W - 20, 42)):
            ed.tl.clips.append(editor.Clip(c.path, c.info))
            ed.sel, ed.over_sel = len(ed.tl.clips) - 1, None
        dl = imgui.get_window_draw_list()
        if imgui.is_item_hovered():
            dl.add_rect_filled(p, imgui.ImVec2(p.x + POOL_W - 20, p.y + 42), imgui.get_color_u32(rgb(HOVER)), ROUNDING)
        strip = strip_texture(app, c.path)
        if strip:
            ref, n = strip
            dl.add_image(ref, imgui.ImVec2(p.x + 2, p.y + 3), imgui.ImVec2(p.x + 64, p.y + 39), imgui.ImVec2(0, 1 - 1 / n), imgui.ImVec2(1, 1))
        dl.push_clip_rect(p, imgui.ImVec2(p.x + POOL_W - 22, p.y + 42), True)
        dl.add_text(imgui.ImVec2(p.x + 72, p.y + 6), imgui.get_color_u32(rgb(TEXT)), c.name)
        dl.add_text(imgui.ImVec2(p.x + 72, p.y + 22), imgui.get_color_u32(rgb(GREY)), timecode(c.info["duration"]))
        dl.pop_clip_rect()
        imgui.pop_id()
    imgui.end()


def page_bar(app, w, h):
    """Workspaces along the bottom, one click each, as in Resolve."""
    global page
    imgui.set_next_window_pos(imgui.ImVec2(0, h - PAGE_H))
    imgui.set_next_window_size(imgui.ImVec2(w, PAGE_H))
    imgui.push_style_color(imgui.Col_.window_bg, rgb(BAR))
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0, 0))
    imgui.begin("##pages", flags=FIXED | imgui.WindowFlags_.no_scrollbar)
    dl, cell = imgui.get_window_draw_list(), 104
    x0 = (w - cell * len(PAGES)) / 2
    for i, name in enumerate(PAGES):
        x = x0 + i * cell
        imgui.set_cursor_screen_pos(imgui.ImVec2(x, h - PAGE_H))
        current = (name == "Camera" and not app.editing) or (app.editing and name == page)
        if imgui.invisible_button(f"##page{name}", imgui.ImVec2(cell, PAGE_H)):
            app.ed.pause()
            app.tab, app.message = "camera" if name == "Camera" else "editor", ""
            if name != "Camera":
                page = name
        ts = imgui.calc_text_size(name)
        color = "#ffffff" if current else (TEXT if imgui.is_item_hovered() else GREY)
        dl.add_text(imgui.ImVec2(x + (cell - ts.x) / 2, h - PAGE_H + (PAGE_H - ts.y) / 2), imgui.get_color_u32(rgb(color)), name)
        if current:
            dl.add_rect_filled(imgui.ImVec2(x + 18, h - PAGE_H), imgui.ImVec2(x + cell - 18, h - PAGE_H + 2), imgui.get_color_u32(rgb(LINK)))
    imgui.end()
    imgui.pop_style_var()
    imgui.pop_style_color()


# ---- timeline ----

RULER_H, OVER_H, VIDEO_H, WAVE_H, SOUND_H = 18, 22, 54, 32, 20
LANES = len(editor.SOUND_TRACKS)
KEY_RED = "#dd3c10"


def strip_texture(app, path):
    """Upload a finished filmstrip once; returns (imgui ref, frames) or None while it's being made."""
    ed = app.ed
    ready = ed.thumbs.ready.pop(path, None)
    if ready is not None:
        n, pixels = ready
        tex = app.ctx.texture((editor.Thumbs.W, n * editor.Thumbs.H), 4, pixels[::-1].tobytes())
        app.imgui.register_texture(tex)
        ed.strips[path] = (imgui.ImTextureRef(tex.glo), n)
    return ed.strips.get(path)


def draw_clip(app, dl, c, i, x0, x1, top, sel):
    video_y, wave_y = top + RULER_H + OVER_H, top + RULER_H + OVER_H + VIDEO_H + 2
    vid_b = imgui.ImVec2(x1, video_y + VIDEO_H)
    dl.add_rect_filled(imgui.ImVec2(x0, video_y), vid_b, imgui.get_color_u32(rgb(BLUE_TINT)))
    strip = strip_texture(app, c.path)
    dl.push_clip_rect(imgui.ImVec2(x0, video_y), imgui.ImVec2(x1, wave_y + WAVE_H), True)
    if strip:
        ref, n = strip
        tw = VIDEO_H * editor.Thumbs.W / editor.Thumbs.H
        x = x0
        while x < x1:
            f = min(int((c.start + (x - x0) / max(x1 - x0, 1) * c.length) / max(c.info["duration"], 0.01) * n), n - 1)
            v0, v1 = 1 - (f + 1) / n, 1 - f / n
            dl.add_image(ref, imgui.ImVec2(x, video_y), imgui.ImVec2(x + tw, video_y + VIDEO_H), imgui.ImVec2(0, v0), imgui.ImVec2(1, v1))
            x += tw
    dl.add_rect_filled(imgui.ImVec2(x0, video_y), imgui.ImVec2(x1, video_y + 15), imgui.get_color_u32(rgb("#000000", 0.5)))
    dl.add_text(imgui.ImVec2(x0 + 4, video_y + 1), imgui.get_color_u32(rgb("#ffffff")), c.name if c.preset_name == "None" else f"{c.name}  ·  {c.preset_name}")
    peaks = app.ed.wave(c.path) if c.info["audio"] else None
    dl.add_rect_filled(imgui.ImVec2(x0, wave_y), imgui.ImVec2(x1, wave_y + WAVE_H), imgui.get_color_u32(rgb(STRIP)))
    if peaks is not None and len(peaks):
        color, mid = imgui.get_color_u32(rgb(GREY if c.mute else "#6d84b4")), wave_y + WAVE_H / 2
        for px in range(int(max(x0, 0)), int(x1), 2):
            src = c.start + (px - x0) / max(x1 - x0, 1) * c.length
            k = int(src * 50)
            if 0 <= k < len(peaks):
                a = float(peaks[k]) * WAVE_H / 2
                dl.add_line(imgui.ImVec2(px, mid - a), imgui.ImVec2(px, mid + a + 1), color)
    for pts in [*(e.keys.values() for e in c.steps if getattr(e, "keys", None)), c.tx.keys.values()]:
        for track in pts:
            for t, _ in track:
                x = x0 + (t - c.start) / max(c.length, 1e-6) * (x1 - x0)
                dl.add_rect_filled(imgui.ImVec2(x - 2, video_y + VIDEO_H - 7), imgui.ImVec2(x + 2, video_y + VIDEO_H - 2), imgui.get_color_u32(rgb(KEY_RED)))
    dl.pop_clip_rect()
    dl.add_rect(imgui.ImVec2(x0, video_y), imgui.ImVec2(x1, wave_y + WAVE_H), imgui.get_color_u32(rgb(BLUE if sel else BORDER)), 0.0, 2.0 if sel else 1.0)


def timeline(app, w, h):
    ed, tl = app.ed, app.ed.tl
    width = w - 2 * MARGIN if skin == "studio" else w - SIDE_W - 3 * MARGIN
    imgui.set_next_window_pos(imgui.ImVec2(MARGIN, h - TIMELINE_H - MARGIN - PAGE_H))
    imgui.set_next_window_size(imgui.ImVec2(width, TIMELINE_H))
    imgui.begin("##timeline", flags=FIXED | imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse)
    if blue_button("Add videos"):
        open_dialog(app, "Add videos", ["Videos", " ".join(f"*{t}" for t in editor.VIDEO_TYPES)], app.add_files, multi=True)
    imgui.same_line()
    if imgui.button("Add overlay"):
        open_dialog(app, "Add overlay video", ["Videos", " ".join(f"*{t}" for t in editor.VIDEO_TYPES)], lambda paths: [ed.add_overlay(p) for p in paths], multi=True)
    imgui.same_line()
    if imgui.button("Pause" if ed.playing else "Play"):
        ed.toggle_play()
    imgui.same_line()
    if imgui.button("Cut"):
        app.split()
    imgui.same_line()
    if imgui.button("Delete"):
        app.delete_clip()
    imgui.same_line()
    if imgui.button("Undo"):
        tl.undo()
        ed.sel = min(ed.sel, len(tl.clips) - 1)
    imgui.same_line()
    if imgui.button("Redo"):
        tl.redo()
        ed.sel = min(ed.sel, len(tl.clips) - 1)
    imgui.same_line()
    imgui.set_next_item_width(110)
    _, ed.zoom = imgui.slider_float("##zoom", ed.zoom, 1, 40, "Zoom %.0fx", imgui.SliderFlags_.logarithmic)
    imgui.same_line()
    level_meter(app, 160)

    p = imgui.get_cursor_screen_pos()
    size = imgui.ImVec2(imgui.get_content_region_avail().x, RULER_H + OVER_H + VIDEO_H + WAVE_H + SOUND_H * LANES + 8)
    imgui.invisible_button("##canvas", size)
    hovered, active = imgui.is_item_hovered(), imgui.is_item_active()
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(p, imgui.ImVec2(p.x + size.x, p.y + RULER_H), imgui.get_color_u32(rgb(STRIP)))
    if not tl.clips and not tl.overlays and not tl.sounds:
        dl.add_text(imgui.ImVec2(p.x + size.x / 2 - 130, p.y + RULER_H + OVER_H + 34), imgui.get_color_u32(rgb(GREY)), "Drop videos anywhere in this window to start")
    dur = max(tl.duration, 0.1)
    pps = size.x / dur * ed.zoom
    view = size.x / pps
    if ed.t < ed.scroll or ed.t > ed.scroll + view:  # keep the playhead on screen
        ed.scroll = max(0.0, ed.t - view * 0.1)
    ed.scroll = min(ed.scroll, max(dur - view, 0.0))

    def to_x(t):
        return p.x + (t - ed.scroll) * pps

    mouse = imgui.get_mouse_pos()
    mouse_t = ed.scroll + (mouse.x - p.x) / pps
    step = next((s for s in (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600) if s * pps >= 60), 1200)
    tick = int(ed.scroll / step) * step
    while tick <= ed.scroll + view:
        x = to_x(tick)
        dl.add_line(imgui.ImVec2(x, p.y + 12), imgui.ImVec2(x, p.y + RULER_H), imgui.get_color_u32(rgb(GREY)))
        dl.add_text(imgui.ImVec2(x + 3, p.y + 1), imgui.get_color_u32(rgb(GREY)), f"{int(tick) // 60}:{tick % 60:04.1f}" if step < 1 else f"{int(tick) // 60}:{int(tick) % 60:02d}")
        tick += step

    dl.push_clip_rect(p, imgui.ImVec2(p.x + size.x, p.y + size.y), True)
    lay = tl.layout()
    hover_edge = None
    lane_y, over_y, sound_y = p.y + RULER_H + OVER_H, p.y + RULER_H, p.y + RULER_H + OVER_H + VIDEO_H + WAVE_H + 4
    if ed.lib_drag:
        imgui.set_mouse_cursor(imgui.MouseCursor_.hand)
        if imgui.is_mouse_released(imgui.MouseButton_.left):
            if sound_y <= mouse.y < sound_y + SOUND_H * LANES and p.x <= mouse.x < p.x + size.x:
                ed.add_sound(ed.lib_drag["path"], max(mouse_t, 0.0), int((mouse.y - sound_y) // SOUND_H))
            ed.lib_drag = None
    blocks = [("over", c, over_y, OVER_H - 2, i == ed.over_sel, "#8b9dc3") for i, c in enumerate(tl.overlays)]
    blocks += [("sound", c, sound_y + c.track * SOUND_H, SOUND_H - 2, i == ed.sound_sel, ("#6db48a", "#b48a6d", "#8a6db4")[c.track]) for i, c in enumerate(tl.sounds)]
    for n, name in enumerate(editor.SOUND_TRACKS):
        dl.add_rect_filled(imgui.ImVec2(p.x, sound_y + n * SOUND_H), imgui.ImVec2(p.x + size.x, sound_y + n * SOUND_H + SOUND_H - 2), imgui.get_color_u32(rgb(STRIP)))
        dl.add_text(imgui.ImVec2(p.x + 4, sound_y + n * SOUND_H + 2), imgui.get_color_u32(rgb(GREY)), name)
    hover_block = None
    for kind, c, y, h, chosen, color in blocks:
        x0, x1 = to_x(c.at), to_x(c.at + c.length)
        dl.add_rect_filled(imgui.ImVec2(x0, y), imgui.ImVec2(x1, y + h), imgui.get_color_u32(rgb(color, 0.75)))
        if kind == "sound":
            fi, fo = c.fade_in * pps, c.fade_out * pps  # the fade corners: drag them to shape the fade
            dl.add_triangle_filled(imgui.ImVec2(x0, y), imgui.ImVec2(x0 + fi, y), imgui.ImVec2(x0, y + h), imgui.get_color_u32(rgb("#000000", 0.35)))
            dl.add_triangle_filled(imgui.ImVec2(x1, y), imgui.ImVec2(x1 - fo, y), imgui.ImVec2(x1, y + h), imgui.get_color_u32(rgb("#000000", 0.35)))
        dl.add_rect(imgui.ImVec2(x0, y), imgui.ImVec2(x1, y + h), imgui.get_color_u32(rgb(LINK if chosen else BORDER)), 0.0, 2.0 if chosen else 1.0)
        dl.push_clip_rect(imgui.ImVec2(x0, y), imgui.ImVec2(x1, y + h), True)
        dl.add_text(imgui.ImVec2(x0 + 4, y + 2), imgui.get_color_u32(rgb("#ffffff")), c.name)
        dl.pop_clip_rect()
        if hovered and y <= mouse.y < y + h and x0 - 6 <= mouse.x <= x1 + 6:
            if kind == "sound" and mouse.y < y + 7 and abs(mouse.x - (x0 + fi)) < 7:
                part = "fade_in"
            elif kind == "sound" and mouse.y < y + 7 and abs(mouse.x - (x1 - fo)) < 7:
                part = "fade_out"
            elif abs(mouse.x - x0) < 6:
                part = "left"
            elif abs(mouse.x - x1) < 6:
                part = "right"
            else:
                part = "body"
            hover_block = (kind, c, part)
    for i, (c, a, b) in enumerate(lay):
        x0, x1 = to_x(a), to_x(b)
        draw_clip(app, dl, c, i, x0, x1, p.y, i == ed.sel)
        over = tl.overlap(i)
        if over:
            dl.add_rect_filled(imgui.ImVec2(to_x(b - over), lane_y), imgui.ImVec2(x1, lane_y + VIDEO_H), imgui.get_color_u32(rgb("#ffffff", 0.35)))
        if hovered and lane_y <= mouse.y < lane_y + VIDEO_H + WAVE_H + 2:
            if abs(mouse.x - x0) < 6:
                hover_edge = (i, "left")
            elif abs(mouse.x - x1) < 6:
                hover_edge = (i, "right")
    for e in tl.events:  # damage events and markers on the ruler
        dl.add_rect_filled(imgui.ImVec2(to_x(e["t"]), p.y + RULER_H - 5), imgui.ImVec2(max(to_x(e["t"] + e["d"]), to_x(e["t"]) + 3), p.y + RULER_H - 1),
                           imgui.get_color_u32(rgb("#e0a020")))
    for m in tl.markers:
        x = to_x(m["t"])
        dl.add_triangle_filled(imgui.ImVec2(x - 5, p.y + 11), imgui.ImVec2(x + 5, p.y + 11), imgui.ImVec2(x, p.y + 18), imgui.get_color_u32(rgb(GREEN)))
        if m["label"]:
            dl.add_text(imgui.ImVec2(x + 7, p.y + 1), imgui.get_color_u32(rgb(GREEN)), m["label"])
    px = to_x(ed.t)
    dl.add_line(imgui.ImVec2(px, p.y), imgui.ImVec2(px, p.y + size.y), imgui.get_color_u32(rgb(RED)), 2)
    dl.add_triangle_filled(imgui.ImVec2(px - 5, p.y), imgui.ImVec2(px + 5, p.y), imgui.ImVec2(px, p.y + 7), imgui.get_color_u32(rgb(RED)))
    dl.pop_clip_rect()
    if hover_edge or (ed.drag and ed.drag[0] in ("left", "right", "edge")) or (hover_block and hover_block[2] in ("left", "right")):
        imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ew)

    if hovered and imgui.is_mouse_clicked(imgui.MouseButton_.left):
        if mouse.y < p.y + RULER_H:
            ed.drag = ("seek",)
        elif hover_block:
            kind, c, part = hover_block
            items = tl.overlays if kind == "over" else tl.sounds
            if kind == "over":
                ed.over_sel, ed.sound_sel = items.index(c), None
            else:
                ed.sound_sel, ed.over_sel = items.index(c), None
            if part == "body":
                ed.drag = ("slide", c, mouse.x, c.at)
            elif part in ("fade_in", "fade_out"):
                ed.drag = ("fade", c, mouse.x, getattr(c, part), part)
            else:
                ed.drag = ("edge", c, mouse.x, part, c.start, c.end, c.at)
        elif hover_edge:
            i, side = hover_edge
            ed.sel, ed.over_sel, ed.sound_sel = i, None, None
            c = tl.clips[i]
            ed.drag = (side, i, mouse.x, c.start if side == "left" else c.end)
        else:
            i = next((k for k, (_, a, b) in enumerate(lay) if a <= mouse_t < b), None)
            if i is not None:
                ed.sel, ed.over_sel, ed.sound_sel = i, None, None
                app.save_name = tl.clips[i].preset_name
                ed.drag = ("move", i, mouse.x)
                ed.seek(mouse_t)
    if ed.drag:
        kind = ed.drag[0]
        if kind == "seek":
            ed.seek(mouse_t)
        elif kind == "slide":
            _, item, x_from, at = ed.drag
            item.at = max(0.0, at + (mouse.x - x_from) / pps)
            if isinstance(item, editor.Sound) and imgui.get_io().mouse_pos.y >= sound_y:
                item.track = int(min(max((mouse.y - sound_y) // SOUND_H, 0), LANES - 1))
        elif kind == "fade":
            _, item, x_from, value, part = ed.drag
            d = (mouse.x - x_from) / pps * (1 if part == "fade_in" else -1)
            setattr(item, part, min(max(value + d, 0.0), item.length))
        elif kind == "edge":
            _, item, x_from, side, start, end, at = ed.drag
            d = (mouse.x - x_from) / pps
            if side == "left":
                d = max(d, -start, -at)
                item.start, item.at = min(start + d, end - 0.05), at + min(d, end - 0.05 - start)
            else:
                item.end = max(min(end + d, item.info["duration"]), start + 0.05)
        elif kind in ("left", "right"):
            _, i, x_from, value = ed.drag
            target = value + (mouse.x - x_from) / pps
            tl.trim(i, start=target) if kind == "left" else tl.trim(i, end=target)
            ed.seek(ed.t)
        elif kind == "move":
            _, i, x_from = ed.drag
            if abs(mouse.x - x_from) > 8:
                j = next((k for k, (_, a, b) in enumerate(lay) if mouse_t < (a + b) / 2), len(lay) - 1)
                x = to_x(lay[j][1]) if j <= i else to_x(lay[j][2])
                dl.add_line(imgui.ImVec2(x, p.y + RULER_H), imgui.ImVec2(x, p.y + size.y), imgui.get_color_u32(rgb(BLUE)), 3)
                if imgui.is_mouse_released(imgui.MouseButton_.left) and j != i:
                    tl.move(i, j)
                    ed.sel = j
                    ed.seek(ed.t)
        if imgui.is_mouse_released(imgui.MouseButton_.left):
            ed.drag = None
    if hovered and imgui.get_io().mouse_wheel:
        ed.zoom = min(max(ed.zoom * 1.15 ** imgui.get_io().mouse_wheel, 1.0), 40.0)
    imgui.end()


def draw(app):
    w, h = app.wnd.size
    top_bar(app, w)
    caption(app, w, h)
    if app.editing:
        timeline(app, w, h)
    sidebar(app, w, h)
    if skin == "studio":
        if app.editing:
            media_pool(app, w, h)
        page_bar(app, w, h)
