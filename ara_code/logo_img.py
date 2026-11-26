"""Draw the real logo image in terminals that can show pictures; everything else uses the block art.

Protocols:  kitty (Kitty, Ghostty) · iterm (iTerm2, WezTerm) · sixel (any terminal that says it supports it:
Windows Terminal 1.22+, Termux, VS Code with images on, foot, mlterm, xterm -ti vt340, Konsole, mintty…).
Override with ARA_LOGO=kitty|iterm|sixel|blocks|off; setup also asks once whether the picture showed up.
"""
import base64
import io
import os
import sys
from pathlib import Path

LOGO_PNG = Path(__file__).parent / "assets" / "logo.png"


def preference():
    """ARA_LOGO, else what setup saved after asking whether the picture showed up ('picture' / 'blocks' / 'off')."""
    forced = os.environ.get("ARA_LOGO", "").strip().lower()
    if forced:
        return forced
    try:
        from .engines import load_config
        return (load_config().get("logo") or "").lower()
    except Exception:
        return ""


def detect():
    """How to draw her logo here: kitty, iterm or sixel pictures, or block art. It asks the terminal itself (one
    round trip) whether it can draw sixel pictures and how big a character is, so it behaves the same on Windows
    Terminal, Termux, VS Code, foot, mlterm, xterm, Konsole…"""
    from . import termcaps
    pref = preference()
    if pref in ("kitty", "iterm", "sixel", "blocks", "off", "probe"):
        return pref
    if pref == "text":
        return "blocks"
    if not (sys.stdout.isatty() and sys.stdin.isatty()) or termcaps.plain_symbols():
        return "blocks"
    env = os.environ
    if not termcaps.in_multiplexer():  # tmux/screen hide the outer terminal's picture support
        prog = env.get("TERM_PROGRAM", "")
        if env.get("KITTY_WINDOW_ID") or env.get("TERM", "") in ("xterm-kitty", "xterm-ghostty") or prog == "ghostty":
            return "kitty"
        if prog in ("iTerm.app", "WezTerm") or env.get("LC_TERMINAL") == "iTerm2":
            return "iterm"
    caps = termcaps.probe()
    if caps["sixel"] and cell_pixels():
        return "sixel"
    return "blocks"


def cell_pixels():
    """Size of one character cell in pixels, so a sixel picture fills exactly the space kept for it.
    ARA_CELL_PX=WxH overrides; otherwise the terminal's own answer; Windows Terminal falls back to its default font."""
    v = os.environ.get("ARA_CELL_PX", "").lower()
    if "x" in v:
        try:
            w, h = v.split("x")
            return int(w), int(h)
        except ValueError:
            pass
    from . import termcaps
    cell = termcaps.probe()["cell"]
    if cell:
        return cell
    return (10, 21) if os.environ.get("WT_SESSION") else None


def _png_bytes():
    return LOGO_PNG.read_bytes()


def kitty(cols, rows):
    data = base64.b64encode(_png_bytes()).decode()
    out, first = [], True
    for i in range(0, len(data), 4096):
        chunk, more = data[i:i + 4096], int(i + 4096 < len(data))
        ctrl = f"a=T,f=100,c={cols},r={rows},C=1,q=2,m={more}" if first else f"m={more}"
        out.append(f"\x1b_G{ctrl};{chunk}\x1b\\")
        first = False
    return "".join(out)


def iterm(cols, rows):
    data = base64.b64encode(_png_bytes()).decode()
    return (f"\x1b]1337;File=inline=1;width={cols};height={rows};preserveAspectRatio=1;"
            f"size={len(_png_bytes())}:{data}\a")


def sixel(cols, rows):
    from PIL import Image
    cw, ch = cell_pixels() or (10, 21)
    im = Image.open(LOGO_PNG).convert("RGBA")
    side = int(min(cols * cw, rows * ch) * 0.94)  # a little slack if the cell-size guess is off
    side -= side % 6
    im = im.resize((side, side), Image.LANCZOS)
    return encode_sixel(im)


def encode_sixel(im):
    """RGBA PIL image → sixel string. Transparent pixels stay transparent (P2=1)."""
    from PIL import Image
    w, h = im.size
    alpha = im.getchannel("A").load()
    rgb = Image.new("RGB", im.size, (0, 0, 0))
    rgb.paste(im, mask=im.getchannel("A"))
    pal = rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    px = pal.load()
    palette = pal.getpalette()[:255 * 3]
    out = io.StringIO()
    out.write(f"\x1bP0;1;0q\"1;1;{w};{h}")
    used = sorted({px[x, y] for y in range(h) for x in range(w) if alpha[x, y] >= 128})
    for c in used:
        r, g, b = palette[c * 3:c * 3 + 3]
        out.write(f"#{c};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}")
    for band in range(0, h, 6):
        colors = {}
        for x in range(w):
            for dy in range(6):
                y = band + dy
                if y < h and alpha[x, y] >= 128:
                    colors.setdefault(px[x, y], [0] * w)[x] |= 1 << dy
        first = True
        for c, bits in colors.items():
            if not first:
                out.write("$")  # back to the start of this band
            first = False
            out.write(f"#{c}")
            run_ch, run_n = None, 0
            for v in bits:
                ch = chr(63 + v)
                if ch == run_ch:
                    run_n += 1
                    continue
                if run_ch is not None:
                    out.write(f"!{run_n}{run_ch}" if run_n > 3 else run_ch * run_n)
                run_ch, run_n = ch, 1
            if run_ch is not None and run_ch != "?":
                out.write(f"!{run_n}{run_ch}" if run_n > 3 else run_ch * run_n)
        out.write("-")
    out.write("\x1b\\")
    return out.getvalue()


def render(kind, cols, rows):
    """Escape sequence that draws the logo in a cols×rows cell box at the cursor, or '' if not possible."""
    try:
        if kind == "kitty":
            return kitty(cols, rows)
        if kind == "iterm":
            return iterm(cols, rows)
        if kind == "sixel":
            return sixel(cols, rows)
        if kind == "probe":  # test pattern for checking placement (ARA_LOGO=probe)
            line = "\x1b[45m" + "#" * cols + "\x1b[0m"
            return (f"\x1b[{cols}D\x1b[1B").join([line] * rows)
    except Exception:
        return ""
    return ""
