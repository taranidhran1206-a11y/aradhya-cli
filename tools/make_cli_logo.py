import json, sys
import numpy as np
from PIL import Image, ImageDraw
SRC = sys.argv[1]  # usage: python tools/make_cli_logo.py logo.png 16 20 24
src = Image.open(SRC).convert("RGBA")
bb = src.getbbox(); src = src.crop(bb)
def cells(W, frame=True, thr=0.42):
    H = W + W % 2
    a = np.asarray(src).astype(float)
    h, w = a.shape[:2]
    # drop the thin rounded frame (it's redrawn crisply): keep only what's inside an inset rounded rect
    keepm = Image.new("L", (w, h)); ins = int(w * 0.035)
    ImageDraw.Draw(keepm).rounded_rectangle((ins, ins, w - ins - 1, h - ins - 1), int(w * 0.10), fill=255)
    a[np.asarray(keepm) == 0] = 0
    a[..., 3] = np.where(a[..., 3] < 140, 0, a[..., 3])         # drop the soft glow that washes her out
    a[a[..., 3] == 0] = 0
    fig = Image.fromarray(a.astype(np.uint8), "RGBA"); fig = fig.crop(fig.getbbox())
    from PIL import ImageEnhance
    rgb_only = ImageEnhance.Color(fig.convert("RGB")).enhance(1.35); rgb_only = ImageEnhance.Contrast(rgb_only).enhance(1.1)
    fig = Image.merge("RGBA", (*rgb_only.split(), fig.split()[3]))
    S = W * 8; canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    box = int(S * 0.80); fw, fh = fig.size; k = box / max(fw, fh)
    fig = fig.resize((int(fw * k), int(fh * k)), Image.LANCZOS)
    canvas.paste(fig, ((S - fig.width) // 2, (S - fig.height) // 2 + int(S * 0.01)), fig)
    c = np.asarray(canvas).astype(float); al2 = c[..., 3:] / 255
    pm = Image.fromarray(np.dstack([c[..., :3] * al2, al2 * 255]).astype(np.uint8), "RGBA").resize((W, H), Image.BOX)
    p = np.asarray(pm).astype(float); A = p[..., 3] / 255
    rgb = np.clip(np.where(A[..., None] > 0, p[..., :3] / np.maximum(A[..., None], 1e-3), 0), 0, 255).astype(int)
    keep = A > thr
    if frame:  # 1-px rounded frame, gold on the left → white → blue on the right, like the logo
        R = int(W * 8 * 0.18)
        outer = Image.new("L", (W * 8, H * 8)); ImageDraw.Draw(outer).rounded_rectangle((0, 0, W*8-1, H*8-1), R, fill=255)
        inn = Image.new("L", (W * 8, H * 8)); ImageDraw.Draw(inn).rounded_rectangle((8, 8, W*8-9, H*8-9), R - 8, fill=255)
        ring = (np.asarray(outer.resize((W, H), Image.BOX)) > 127) & (np.asarray(inn.resize((W, H), Image.BOX)) < 128)
        gold, white, blue = np.array([196, 160, 96]), np.array([226, 224, 214]), np.array([74, 150, 214])
        for y in range(H):
            for x in range(W):
                if ring[y, x]:
                    f = x / (W - 1)
                    rgb[y, x] = gold + (white - gold) * (f / .5) if f < .5 else white + (blue - white) * ((f - .5) / .5)
                    keep[y, x] = True
    rows = []
    for y in range(0, H, 2):
        rows.append([(tuple(int(v) for v in rgb[y, x]) if keep[y, x] else None,
                      tuple(int(v) for v in rgb[y + 1, x]) if y + 1 < H and keep[y + 1, x] else None) for x in range(W)])
    return rows
def ans(rows):
    out = []
    for r in rows:
        s = ""
        for t, b in r:
            if not t and not b: s += " "
            elif t and b: s += f"\x1b[38;2;{t[0]};{t[1]};{t[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m▀\x1b[0m"
            elif t: s += f"\x1b[38;2;{t[0]};{t[1]};{t[2]}m▀\x1b[0m"
            else: s += f"\x1b[38;2;{b[0]};{b[1]};{b[2]}m▄\x1b[0m"
        out.append(s)
    return "\n".join(out)
if __name__ == "__main__":
    for W in map(int, sys.argv[2:]):
        r = cells(W); open(f"/tmp/x{W}.ans", "w").write(ans(r)); json.dump(r, open(f"/tmp/x{W}.json", "w"))
