import math
import sys
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UPM = 1000
CAP = 700
S = 128
H = S / 2
RAD = 42
SB = 56
B = H
T = CAP - H
M = 350
D = 200


def loop(*pts):
    return ("loop", pts)


def glyphs():
    g = {}

    def w(W):
        return H, W - H, W / 2

    L, R, C = w(600)
    g["A"] = (600, [[(L, 0), (L, T - D), (L + D, T), (R, T), (R, 0)], [(L, 300), (R, 300)]])
    L, R, C = w(580)
    g["B"] = (580, [loop((L, M), (L, T), (R - 50, T), (R - 50, M)), loop((L, B), (L, M), (R, M), (R, B))])
    L, R, C = w(560)
    g["C"] = (560, [[(560, T), (L, T), (L, B), (560, B)]])
    L, R, C = w(590)
    g["D"] = (590, [loop((L, B), (L, T), (R - 150, T), (R, T - 150), (R, B))])
    L, R, C = w(540)
    g["E"] = (540, [[(540, T), (L, T), (L, B), (540, B)], [(L, M), (490, M)]])
    g["F"] = (540, [[(540, T), (L, T), (L, 0)], [(L, M), (490, M)]])
    L, R, C = w(590)
    g["G"] = (590, [[(590, T), (L, T), (L, B), (R, B), (R, 320), (C + 20, 320)]])
    g["H"] = (590, [[(L, 0), (L, CAP)], [(R, 0), (R, CAP)], [(L, M), (R, M)]])
    L, R, C = w(440)
    g["I"] = (440, [[(0, T), (440, T)], [(0, B), (440, B)], [(C, B), (C, T)]])
    L, R, C = w(540)
    g["J"] = (540, [[(R, CAP), (R, B), (L, B), (L, 260)]])
    L, R, C = w(600)
    g["K"] = (600, [[(L, 0), (L, CAP)], [(L, M), (260, M), (505, CAP)], [(L, M), (260, M), (505, 0)]])
    L, R, C = w(540)
    g["L"] = (540, [[(L, CAP), (L, B), (540, B)]])
    L, R, C = w(720)
    g["M"] = (720, [[(L, 0), (L, T - D), (L + D, T), (R, T), (R, 0)], [(C, T), (C, 0)]])
    L, R, C = w(600)
    g["N"] = (600, [[(L, 0), (L, T - D), (L + D, T), (R, T), (R, 0)]])
    g["O"] = (600, [loop((L, B), (L, T), (R, T), (R, B))])
    g["Q"] = (600, [loop((L, B), (L, T), (R, T), (R, B)), [(R, B), (R, -120)]])
    L, R, C = w(580)
    g["P"] = (580, [[(L, 0), (L, T), (R, T), (R, 320), (L, 320)]])
    L, R, C = w(590)
    g["R"] = (590, [[(L, 0), (L, T), (R, T), (R, 330), (L, 330)], [(C, 330), (R, 0)]])
    L, R, C = w(580)
    g["S"] = (580, [[(580, T), (L, T), (L, M), (R, M), (R, B), (0, B)]])
    L, R, C = w(600)
    g["T"] = (600, [[(0, T), (600, T)], [(C, T), (C, 0)]])
    L, R, C = w(590)
    g["U"] = (590, [[(L, CAP), (L, B), (R, B), (R, CAP)]])
    L, R, C = w(600)
    g["V"] = (600, [[(L, CAP), (L, 330), (C, 92), (R, 330), (R, CAP)]])
    L, R, C = w(740)
    g["W"] = (740, [[(L, CAP), (L, B), (R, B), (R, CAP)], [(C, B), (C, 420)]])
    g["X"] = (600, [[(80, CAP), (520, 0)], [(520, CAP), (80, 0)]])
    L, R, C = w(600)
    g["Y"] = (600, [[(L, CAP), (L, M + 10), (R, M + 10), (R, CAP)], [(C, M + 10), (C, 0)]])
    L, R, C = w(580)
    g["Z"] = (580, [[(0, T), (R, T), (L, B), (580, B)]])

    N = 560
    L, R, C = w(N)
    g["zero"] = (N, [loop((L, B), (L, T - 150), (L + 150, T), (R, T), (R, B))])
    g["one"] = (N, [[(110, T), (C, T), (C, B)], [(100, B), (460, B)]])
    g["two"] = (N, [[(0, T), (R, T), (R, M), (L, M), (L, B), (N, B)]])
    g["three"] = (N, [[(0, T), (R, T), (R, B), (0, B)], [(180, M), (R, M)]])
    g["four"] = (N, [[(L, CAP), (L, 300), (N, 300)], [(R - 20, 560), (R - 20, 0)]])
    g["five"] = (N, [[(N, T), (L, T), (L, M + 20), (R, M + 20), (R, B), (0, B)]])
    g["six"] = (N, [[(N, T), (L, T), (L, B), (R, B), (R, M), (L, M)]])
    g["seven"] = (N, [[(0, T), (R, T), (R, 440), (200, 0)]])
    g["eight"] = (N, [loop((L + 20, M), (L + 20, T), (R - 20, T), (R - 20, M)), loop((L, B), (L, M), (R, M), (R, B))])
    g["nine"] = (N, [[(R, M), (L, M), (L, T), (R, T), (R, B), (0, B)]])

    g["period"] = (128, [[(H, 0), (H, S)]])
    g["comma"] = (128, [[(H, S), (H, -100)]])
    g["colon"] = (128, [[(H, 0), (H, S)], [(H, 380), (H, 380 + S)]])
    g["hyphen"] = (340, [[(0, M), (340, M)]])
    g["slash"] = (440, [[(70, 0), (370, CAP)]])
    g["quotesingle"] = (128, [[(H, CAP), (H, 500)]])
    g["exclam"] = (128, [[(H, CAP), (H, 230)], [(H, 0), (H, S)]])
    g["question"] = (540, [[(0, T), (476, T), (476, 380), (270, 380), (270, 230)], [(270, 0), (270, S)]])
    g["plus"] = (440, [[(0, M), (440, M)], [(220, M - 200), (220, M + 200)]])
    g["periodcentered"] = (128, [[(H, M - H), (H, M + H)]])
    g["space"] = (190, [])
    g[".notdef"] = (500, [loop((H, B), (H, T), (500 - H, T), (500 - H, B))])
    return g


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, k):
    return (a[0] * k, a[1] * k)


def unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l)


def left(u):
    return (-u[1], u[0])


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def rnd(p):
    return (int(round(p[0])), int(round(p[1])))


def area(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2


def cut_for(e, u, W):
    if (e[1] <= 0 or e[1] >= CAP) and abs(u[1]) > 1e-6:
        return (1, e[1])
    if (e[0] <= 0 or e[0] >= W) and abs(u[0]) > 1e-6:
        return (0, e[0])
    return None


def apply_cut(p, u, cut):
    if not cut:
        return p
    ax, val = cut
    t = (val - p[ax]) / u[ax]
    return add(p, mul(u, t))


def intersect(p, u, q, v):
    d = cross(u, v)
    t = cross(sub(q, p), v) / d
    return add(p, mul(u, t))


def outline(W, strokes):
    contours = []
    for st in strokes:
        closed = isinstance(st, tuple) and st[0] == "loop"
        pts = list(st[1] if closed else st)
        n = len(pts)
        segs = [(pts[i], pts[(i + 1) % n]) for i in range(n if closed else n - 1)]
        for i, (p, q) in enumerate(segs):
            u = unit(sub(q, p))
            nl = left(u)
            a, b2, c, d = add(p, mul(nl, H)), add(q, mul(nl, H)), sub(q, mul(nl, H)), sub(p, mul(nl, H))
            if not closed and i == 0:
                cut = cut_for(p, u, W)
                a, d = apply_cut(a, u, cut), apply_cut(d, u, cut)
            if not closed and i == len(segs) - 1:
                cut = cut_for(q, u, W)
                b2, c = apply_cut(b2, u, cut), apply_cut(c, u, cut)
            contours.append([("on", rnd(x)) for x in (a, b2, c, d)])
        joints = range(n) if closed else range(1, n - 1)
        for j in joints:
            b = pts[j]
            u1 = unit(sub(b, pts[j - 1]))
            u2 = unit(sub(pts[(j + 1) % n], b))
            cr = cross(u1, u2)
            if abs(cr) < 1e-9:
                continue
            side = -1 if cr > 0 else 1
            o1 = add(b, mul(left(u1), H * side))
            o2 = add(b, mul(left(u2), H * side))
            mp = intersect(o1, u1, o2, u2)
            t = math.hypot(*sub(mp, o1))
            e1 = add(sub(o1, mul(u1, H * 0.75)), mul(left(u1), -side * 2))
            e2 = add(add(o2, mul(u2, H * 0.75)), mul(left(u2), -side * 2))
            head = [("on", rnd(b)), ("on", rnd(e1)), ("on", rnd(o1))]
            tail = [("on", rnd(o2)), ("on", rnd(e2))]
            if t > 1.3 * H:
                contours.append(head + tail)
                continue
            c = min(RAD, t - 3)
            if c < 4:
                contours.append(head + [("on", rnd(mp))] + tail)
                continue
            p1 = sub(mp, mul(u1, c))
            p2 = add(mp, mul(u2, c))
            contours.append(head + [("on", rnd(p1)), ("off", rnd(mp)), ("on", rnd(p2))] + tail)
    fixed = []
    for ct in contours:
        if area([p for _, p in ct]) > 0:
            ct = [ct[0]] + ct[1:][::-1]
        fixed.append(ct)
    return fixed


def draw(contours):
    pen = TTGlyphPen(None)
    xs = []
    for ct in contours:
        pts = [(k, (p[0] + SB, p[1])) for k, p in ct]
        xs += [p[0] for _, p in pts]
        pen.moveTo(pts[0][1])
        i = 1
        while i < len(pts):
            k, p = pts[i]
            if k == "off":
                nxt = pts[(i + 1) % len(pts)][1]
                pen.qCurveTo(p, nxt)
                i += 2
            else:
                pen.lineTo(p)
                i += 1
        pen.closePath()
    return pen.glyph(), (min(xs) if xs else 0)


def build(out):
    defs = glyphs()
    order = [".notdef", "space"] + [k for k in defs if k not in (".notdef", "space")]
    glyf, metrics = {}, {}
    for name in order:
        W, strokes = defs[name]
        g, xmin = draw(outline(W, strokes))
        glyf[name] = g
        metrics[name] = (int(W + 2 * SB), int(xmin))
    names = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
             "period": ".", "comma": ",", "colon": ":", "hyphen": "-", "slash": "/", "quotesingle": "'", "exclam": "!", "question": "?",
             "plus": "+", "periodcentered": "·", "space": " "}
    cmap = {}
    for name in order:
        if len(name) == 1 and name.isalpha():
            cmap[ord(name)] = name
            cmap[ord(name.lower())] = name
        elif name in names:
            cmap[ord(names[name])] = name
    cmap[0x00A0] = "space"
    cmap[0x2013] = "hyphen"
    cmap[0x2019] = "quotesingle"
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyf)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=860, descent=-240)
    fb.setupNameTable({"familyName": "Asset Display", "styleName": "Regular", "uniqueFontIdentifier": "AssetDisplay-Regular", "fullName": "Asset Display", "psName": "AssetDisplay-Regular", "version": "Version 1.000", "licenseDescription": "MIT"})
    fb.setupOS2(sTypoAscender=860, sTypoDescender=-240, sTypoLineGap=0, usWinAscent=900, usWinDescent=260, sxHeight=CAP, sCapHeight=CAP, achVendID="CAA ", fsType=0)
    fb.setupPost()
    fb.setupHead(unitsPerEm=UPM)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fb.save(out)
    return out


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "ui" / "fonts" / "asset-display.ttf")))
