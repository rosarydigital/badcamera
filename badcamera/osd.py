"""On-screen-display lettering, designed the way a character-generator ROM was: strokes on the chip's own coarse dot grid.

Glyphs are polylines on a 6x10 design grid. They're drawn with a square pen onto a grid of real chip dots, with no antialiasing,
so strokes are even and corners stay hard. Variants change only the pen and proportions, as different makers' chips did.
"""
import numpy as np

# Design grid: x 0..6, y 0..10 (0 is the top). "/" lifts the pen.
GLYPHS = {
    "0": "1 0,5 0,6 1,6 9,5 10,1 10,0 9,0 1,1 0",
    "1": "1 2,3 0,3 10/1 10,5 10",
    "2": "0 2,1 0,5 0,6 1,6 4,0 10,6 10",
    "3": "0 1,1 0,5 0,6 1,6 4,5 5,2 5/5 5,6 6,6 9,5 10,1 10,0 9",
    "4": "5 10,5 0,0 7,6 7",
    "5": "6 0,0 0,0 5,5 5,6 6,6 9,5 10,1 10,0 9",
    "6": "5 0,2 0,0 3,0 9,1 10,5 10,6 9,6 6,5 5,0 5",
    "7": "0 0,6 0,6 2,2 10",
    "8": "1 0,5 0,6 1,6 4,5 5,1 5,0 4,0 1,1 0/1 5,0 6,0 9,1 10,5 10,6 9,6 6,5 5",
    "9": "6 5,1 5,0 4,0 1,1 0,5 0,6 1,6 7,4 10,1 10",
    "A": "0 10,0 2,2 0,4 0,6 2,6 10/0 6,6 6",
    "B": "0 0,0 10,5 10,6 9,6 6,5 5,0 5/5 5,6 4,6 1,5 0,0 0",
    "C": "6 2,5 0,1 0,0 1,0 9,1 10,5 10,6 8",
    "D": "0 0,0 10,4 10,6 8,6 2,4 0,0 0",
    "E": "6 0,0 0,0 10,6 10/0 5,5 5",
    "F": "6 0,0 0,0 10/0 5,5 5",
    "G": "6 2,5 0,1 0,0 1,0 9,1 10,5 10,6 9,6 5,3 5",
    "H": "0 0,0 10/6 0,6 10/0 5,6 5",
    "I": "1 0,5 0/3 0,3 10/1 10,5 10",
    "J": "2 0,6 0/5 0,5 9,4 10,1 10,0 9,0 7",
    "K": "0 0,0 10/6 0,1 5,6 10",
    "L": "0 0,0 10,6 10",
    "M": "0 10,0 0,3 5,6 0,6 10",
    "N": "0 10,0 0,6 10,6 0",
    "O": "1 0,5 0,6 1,6 9,5 10,1 10,0 9,0 1,1 0",
    "P": "0 10,0 0,5 0,6 1,6 5,5 6,0 6",
    "Q": "1 0,5 0,6 1,6 9,5 10,1 10,0 9,0 1,1 0/3 7,6 10",
    "R": "0 10,0 0,5 0,6 1,6 4,5 5,0 5/2 5,6 10",
    "S": "6 2,5 0,1 0,0 1,0 4,1 5,5 5,6 6,6 9,5 10,1 10,0 8",
    "T": "0 0,6 0/3 0,3 10",
    "U": "0 0,0 9,1 10,5 10,6 9,6 0",
    "V": "0 0,0 6,3 10,6 6,6 0",
    "W": "0 0,0 10,3 6,6 10,6 0",
    "X": "0 0,6 10/6 0,0 10",
    "Y": "0 0,3 5,6 0/3 5,3 10",
    "Z": "0 0,6 0,0 10,6 10",
    ":": "3 3,3 3/3 7,3 7",
    ".": "3 10,3 10",
    ",": "3 9,3 10,2 11",
    "-": "1 5,5 5",
    "_": "0 10,6 10",
    "/": "6 0,0 10",
    "\\": "0 0,6 10",
    "'": "3 0,3 2",
    "\"": "2 0,2 2/4 0,4 2",
    "!": "3 0,3 7/3 10,3 10",
    "?": "0 2,1 0,5 0,6 1,6 3,3 6,3 7/3 10,3 10",
    "+": "3 2,3 8/0 5,6 5",
    "=": "1 3,5 3/1 7,5 7",
    "(": "4 0,2 2,2 8,4 10",
    ")": "2 0,4 2,4 8,2 10",
    "[": "4 0,2 0,2 10,4 10",
    "]": "2 0,4 0,4 10,2 10",
    "<": "5 1,1 5,5 9",
    ">": "1 1,5 5,1 9",
    "%": "0 10,6 0/0 0,2 0,2 2,0 2,0 0/4 8,6 8,6 10,4 10,4 8",
    "#": "2 0,2 10/4 0,4 10/0 3,6 3/0 7,6 7",
    "*": "3 2,3 8/0 3,6 7/6 3,0 7",
    "|": "3 0,3 10",
}
FILLED = {  # solid shapes, as polygons on the design grid
    "▶": [(0, 0), (6, 5), (0, 10)], "◀": [(6, 0), (0, 5), (6, 10)],
    "●": [(1.5, 1), (4.5, 1), (6, 3.5), (6, 6.5), (4.5, 9), (1.5, 9), (0, 6.5), (0, 3.5)],
    "■": [(0, 1), (6, 1), (6, 9), (0, 9)],
}
PAUSE = "Ⅱ"

# dots per design unit across and down, pen size in dots, and character advance in design units.
VARIANTS = {
    "vcr": dict(sx=2, sy=2, pen=(4, 3), advance=8.5),       # heavy deck OSD: wide strokes, bold and square
    "camcorder": dict(sx=2, sy=2, pen=(4, 2), advance=8.5),  # date generators: a lighter stroke
    "cctv": dict(sx=2, sy=2, pen=(4, 4), advance=8),        # multiplexer titles: tighter, squarer
}


def _line(grid, x0, y0, x1, y1, pen):
    n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    h, w = grid.shape
    for i in range(n):
        k = i / max(n - 1, 1)
        x, y = int(round(x0 + (x1 - x0) * k)), int(round(y0 + (y1 - y0) * k))
        grid[max(y, 0):min(y + pen[1], h), max(x, 0):min(x + pen[0], w)] = 1


def _fill(grid, pts):
    import cv2
    p = np.array([[round(x), round(y)] for x, y in pts], np.int32)
    cv2.fillPoly(grid, [p], 1)


def glyph(ch, variant):
    """One character as a binary dot grid."""
    v = VARIANTS[variant]
    sx, sy, pen = v["sx"], v["sy"], v["pen"]
    w, h = 6 * sx + pen[0], 11 * sy + pen[1]
    grid = np.zeros((h, w), np.uint8)
    ch = ch.upper() if ch.upper() in GLYPHS else ch
    if ch in FILLED:
        _fill(grid, [(x * sx + pen[0] / 2, y * sy + pen[1] / 2) for x, y in FILLED[ch]])
    elif ch == PAUSE:
        _line(grid, sx, 0, sx, 10 * sy, (pen[0] + 1, pen[1]))
        _line(grid, 4 * sx, 0, 4 * sx, 10 * sy, (pen[0] + 1, pen[1]))
    elif ch != " ":
        for stroke in GLYPHS.get(ch, GLYPHS["?"]).split("/"):
            pts = [tuple(float(a) for a in p.split()) for p in stroke.split(",")]
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                _line(grid, x0 * sx, y0 * sy, x1 * sx, y1 * sy, pen)
    return grid


def text(line, variant, tracking=0.0):
    """A line of text as a binary dot grid. Characters sit on fixed cells, like a display RAM."""
    v = VARIANTS[variant]
    cell = int(round((v["advance"] + tracking * 6) * v["sx"]))
    g0 = glyph("0", variant)
    out = np.zeros((g0.shape[0], max(1, cell * len(line) + g0.shape[1] - cell)), np.uint8)
    for i, ch in enumerate(line):
        g = glyph(ch, variant)
        out[:g.shape[0], i * cell:i * cell + g.shape[1]] = g
    return out
