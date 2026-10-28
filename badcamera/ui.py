"""Control panel, styled like a 2012-era social site: flat blue top bar, white boxes, grey header strips, blue links."""
import random
import time
from pathlib import Path

from imgui_bundle import imgui

from . import presets
from .effects import REGISTRY, make

TOP_H, SIDE_W, MARGIN, PAD, CAPTION_H, LABEL_W = 38, 390, 14, 10, 62, 118


def rgb(h, a=1.0):
    return imgui.ImVec4(int(h[1:3], 16) / 255, int(h[3:5], 16) / 255, int(h[5:7], 16) / 255, a)


def gl_rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


BLUE, BLUE_DARK, BLUE_PALE, BLUE_TINT = "#3b5998", "#29487d", "#d8dfea", "#eceff5"
PAGE, BORDER, STRIP, TEXT, GREY, RED, GREEN = "#e9ebee", "#d3d6db", "#f6f7f9", "#1d2129", "#90949c", "#dd3c10", "#42b72a"

FONT = BOLD = None


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

    s = imgui.get_style()
    for a in ("window_rounding", "child_rounding", "frame_rounding", "popup_rounding", "scrollbar_rounding", "grab_rounding",
              "tab_rounding", "selectable_rounding", "menu_item_rounding", "image_rounding"):
        setattr(s, a, 0.0)
    s.window_border_size = s.child_border_size = s.popup_border_size = s.frame_border_size = 1.0
    s.window_padding, s.frame_padding = imgui.ImVec2(10, 10), imgui.ImVec2(6, 4)
    s.item_spacing, s.item_inner_spacing = imgui.ImVec2(6, 6), imgui.ImVec2(6, 4)
    s.scrollbar_size, s.grab_min_size, s.indent_spacing = 11.0, 9.0, 14.0
    C = imgui.Col_
    for col, h in {
        C.text: TEXT, C.text_disabled: GREY, C.window_bg: "#ffffff", C.child_bg: "#ffffff", C.popup_bg: "#ffffff",
        C.border: BORDER, C.frame_bg: "#ffffff", C.frame_bg_hovered: STRIP, C.frame_bg_active: BLUE_TINT,
        C.scrollbar_bg: STRIP, C.scrollbar_grab: "#c4cde0", C.scrollbar_grab_hovered: "#a9b5d1", C.scrollbar_grab_active: "#8b9dc3",
        C.check_mark: BLUE, C.slider_grab: "#6d84b4", C.slider_grab_active: BLUE,
        C.button: STRIP, C.button_hovered: PAGE, C.button_active: BLUE_PALE,
        C.header: BLUE_TINT, C.header_hovered: "#e1e6f0", C.header_active: BLUE_PALE,
        C.separator: "#dddfe2", C.text_selected_bg: BLUE_PALE, C.text_link: BLUE, C.nav_cursor: BLUE,
    }.items():
        s.set_color_(col, rgb(h))
    s.set_color_(C.border_shadow, rgb("#000000", 0.0))


def bold(text, color=TEXT, size=13):
    imgui.push_font(BOLD, size)
    imgui.text_colored(rgb(color), text)
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
    dl.add_rect_filled(a0, a1, imgui.get_color_u32(rgb(BLUE_TINT if imgui.is_item_hovered() else "#ffffff")))
    dl.add_rect(a0, a1, imgui.get_color_u32(rgb("#bdc7d8")))
    if v:
        s = a1.x - a0.x
        pts = [imgui.ImVec2(a0.x + s * 0.2, a0.y + s * 0.5), imgui.ImVec2(a0.x + s * 0.42, a0.y + s * 0.72), imgui.ImVec2(a0.x + s * 0.8, a0.y + s * 0.25)]
        dl.add_polyline(pts, imgui.get_color_u32(rgb(BLUE)), 2.0, 0)
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
    bold(title, "#4b4f56")
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


ACRONYMS = {"vhs": "VHS", "lut": "LUT", "jpeg": "JPEG", "lcd": "LCD", "hsv": "HSV"}


def pretty(name):
    return " ".join(ACRONYMS.get(w, w) for w in name.split("_")).capitalize() if name.split("_")[0] not in ACRONYMS \
        else " ".join(ACRONYMS.get(w, w) for w in name.split("_"))


def photo_rects(win, img):
    """Window-space (x, y, w, h) of the white photo box, the image inside it, and the caption strip."""
    ax, ay = MARGIN, TOP_H + MARGIN
    aw, ah = win[0] - SIDE_W - 3 * MARGIN, win[1] - TOP_H - 2 * MARGIN
    s = min((aw - 2 * PAD) / img[0], (ah - 2 * PAD - CAPTION_H) / img[1])
    iw, ih = int(img[0] * s), int(img[1] * s)
    bx = ax + (aw - iw - 2 * PAD) // 2
    box = (bx, ay, iw + 2 * PAD, ih + 2 * PAD + CAPTION_H)
    return box, (bx + PAD, ay + PAD, iw, ih), (bx + PAD, ay + PAD + ih, iw, CAPTION_H + PAD)


# ---- widgets ----

def param_widget(e, p):
    v, k = e.v[p.key], p.kind
    imgui.align_text_to_frame_padding()
    imgui.text_colored(rgb("#4b4f56"), pretty(p.key))
    imgui.same_line(LABEL_W)
    imgui.set_next_item_width(-1)
    label = f"##{p.key}"
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
    bold("Style", "#4b4f56")
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
        _, e.enabled = check("##on", e.enabled)
        imgui.same_line()
        imgui.push_font(BOLD, 13)
        imgui.push_style_color(imgui.Col_.text, rgb(BLUE if e.enabled else GREY))
        is_open = imgui.collapsing_header(f"{pretty(e.type)}###h")
        imgui.pop_style_color()
        imgui.pop_font()
        if is_open:
            imgui.indent()
            if e.error:
                imgui.text_colored(rgb(RED), e.error)
            style_row(app, e)
            for p in e.params:
                changed, val = param_widget(e, p)
                if changed:
                    e.v[p.key], e.error = val, None
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


def top_bar(app, w):
    imgui.set_next_window_pos(imgui.ImVec2(0, 0))
    imgui.set_next_window_size(imgui.ImVec2(w, TOP_H))
    imgui.push_style_color(imgui.Col_.window_bg, rgb(BLUE))
    imgui.push_style_color(imgui.Col_.border, rgb(BLUE_DARK))
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(MARGIN, 8))
    imgui.begin("##top", flags=FIXED | imgui.WindowFlags_.no_scrollbar)
    imgui.push_font(BOLD, 20)
    imgui.text_colored(rgb("#ffffff"), "badcamera")
    imgui.pop_font()

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
    imgui.same_line(w - MARGIN - imgui.calc_text_size(status).x - badge_w)
    imgui.set_cursor_pos_y(11)
    for text, color in badges:
        badge(text, color)
    imgui.text_colored(rgb(BLUE_PALE), status)
    imgui.end()
    imgui.pop_style_var()
    imgui.pop_style_color(2)


def caption(app, w, h):
    _, _, (cx, cy, cw, ch) = photo_rects((w, h), app.size if app.size[0] else (16, 9))
    imgui.set_next_window_pos(imgui.ImVec2(cx, cy))
    imgui.set_next_window_size(imgui.ImVec2(cw, ch))
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0, 8))
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
    imgui.begin("##caption", flags=FIXED | imgui.WindowFlags_.no_background | imgui.WindowFlags_.no_scrollbar)
    bold(app.presets[app.preset_i]["name"], BLUE, 15)
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
    if app.message:
        imgui.text_colored(rgb(GREY), app.message)
    elif not app.camtex:
        imgui.text_colored(rgb(GREY), "Waiting for the camera...")
    imgui.end()
    imgui.pop_style_var(2)


def sidebar(app, w, h):
    imgui.set_next_window_pos(imgui.ImVec2(w - SIDE_W - MARGIN, TOP_H + MARGIN))
    imgui.set_next_window_size(imgui.ImVec2(SIDE_W, h - TOP_H - 2 * MARGIN))
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(10, 0))
    imgui.begin("##side", flags=FIXED)

    section("Presets")
    imgui.begin_child("##presets", imgui.ImVec2(0, 190), imgui.ChildFlags_.borders)
    n_builtin = app.n_builtin
    for i, p in enumerate(app.presets):
        if i == n_builtin:
            imgui.dummy(imgui.ImVec2(0, 2))
            bold("YOUR PRESETS", GREY, 11)
        selected = i == app.preset_i
        imgui.push_style_color(imgui.Col_.text, rgb(TEXT if selected else BLUE))
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

    section("Effects")
    step_list(app)
    imgui.dummy(imgui.ImVec2(0, 2))
    types = sorted(REGISTRY)
    imgui.set_next_item_width(SIDE_W - 2 * 10 - 110)
    _, app.add_i = imgui.combo("##add", app.add_i, [pretty(t) for t in types])
    imgui.same_line()
    if blue_button("Add effect"):
        app.steps.append(make(types[app.add_i]))

    section("Keyboard")
    for keys, what in (("Left / Right", "change preset"), ("Space", "take photo"), ("R", "record video"),
                       ("V", "virtual cam on/off"), ("B", "show original"), ("F", "fullscreen")):
        bold(keys, "#4b4f56")
        imgui.same_line(LABEL_W)
        imgui.text_colored(rgb(GREY), what)
    imgui.dummy(imgui.ImVec2(0, 6))
    imgui.text_colored(rgb(GREY), "badcamera © 2026  ·  photos and videos go to captures/")
    imgui.dummy(imgui.ImVec2(0, 8))
    imgui.end()
    imgui.pop_style_var()


def draw(app):
    w, h = app.wnd.size
    top_bar(app, w)
    caption(app, w, h)
    sidebar(app, w, h)
