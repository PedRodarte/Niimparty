"""Renderizador: aplica um modelo à foto tratada e gera a etiqueta pronta.

Tudo é descrito em milímetros no template.yaml e convertido para pontos
pela resolução (dpi) do perfil da impressora, então o mesmo modelo serve
para 50 × 80, 50 × 30, 12 × 40 mm etc.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import imaging
from .printers.base import PrinterProfile
from .templates import ROOT, Template, TextSpec

log = logging.getLogger("niimparty.renderer")

FONTS_DIR = ROOT / "assets" / "fonts"
MIN_TEXT_MM = 2.5     # altura mínima de letra legível na impressão térmica
MIN_STROKE_MM = 0.3   # traço mínimo


@dataclass
class RenderContext:
    event: str = ""
    date: str = ""                 # AAAA-MM-DD
    guest_name: str = ""
    texts: dict[str, str] = field(default_factory=dict)  # sobrescreve defaults por id
    guest_enabled: bool = True      # o organizador quer pedir o nome?
    date_format: str = "%d/%m/%Y"
    logo: Image.Image | None = None
    placeholder_logo: bool = False  # desenha caixa "LOGO" quando não há logo (prévias)


@dataclass
class RenderResult:
    image: Image.Image
    warnings: list[str]
    photo_box: tuple[int, int, int, int]
    size_px: tuple[int, int]


# ------------------------------------------------------------ variáveis

_VAR = re.compile(r"\{(\w+)\}")


def template_vars(ctx: RenderContext) -> dict[str, str]:
    try:
        date = dt.date.fromisoformat(ctx.date) if ctx.date else dt.date.today()
        date_txt = date.strftime(ctx.date_format) if ctx.date else ""
    except ValueError:
        date, date_txt = dt.date.today(), ctx.date
    return {
        "ano": str(date.year),
        "year": str(date.year),
        "data": date_txt,
        "date": date_txt,
        "evento": ctx.event,
        "event": ctx.event,
        "nome": ctx.guest_name.strip(),
        "name": ctx.guest_name.strip(),
    }


def fill(text: str, variables: dict[str, str]) -> str:
    """Troca {variável}; deixa intactas as desconhecidas."""
    return _VAR.sub(lambda m: variables.get(m.group(1), m.group(0)), text)


def clean_guest_name(name: str, max_chars: int) -> str:
    name = re.sub(r"[\x00-\x1f\x7f]", "", name or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name[:max_chars]


# ------------------------------------------------------------ fontes


def resolve_font(name: str, template: Template | None = None) -> Path:
    candidates = []
    if template is not None:
        candidates += [template.fonts_dir / f"{name}.ttf", template.fonts_dir / f"{name}.otf"]
    candidates += [FONTS_DIR / f"{name}.ttf", FONTS_DIR / f"{name}.otf"]
    for path in candidates:
        if path.is_file():
            return path
    fallback = FONTS_DIR / "InterDisplay-Bold.ttf"
    log.warning("fonte %s não encontrada; usando %s", name, fallback.name)
    return fallback


@lru_cache(maxsize=256)
def _font(path: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, max(4, px))


@lru_cache(maxsize=64)
def _cap_ratio(path: str) -> float:
    """Altura da maiúscula 'H' em relação ao tamanho da fonte."""
    f = _font(path, 200)
    _, top, _, bottom = f.getbbox("H", anchor="ls")
    return max(0.3, (bottom - top) / 200)


def _text_width(text: str, font: ImageFont.FreeTypeFont, spacing_px: float) -> float:
    if not spacing_px:
        return font.getlength(text)
    return sum(font.getlength(c) for c in text) + spacing_px * max(0, len(text) - 1)


@dataclass
class Row:
    kind: str                # text | logo
    height: int
    text: str = ""
    spec: TextSpec | None = None
    font: ImageFont.FreeTypeFont | None = None
    cap_px: int = 0
    spacing_px: float = 0.0
    image: Image.Image | None = None
    align: str = "center"


# ------------------------------------------------------------ renderização


def label_size_px(template: Template, label_mm: tuple[float, float], profile: PrinterProfile) -> tuple[int, int]:
    a, b = sorted(label_mm)
    w_mm, h_mm = (a, b) if template.orientation == "portrait" else (b, a)
    ppmm = profile.px_per_mm
    return round(w_mm * ppmm), round(h_mm * ppmm)


def _make_text_row(spec: TextSpec, text: str, template: Template, ppmm: float, max_w: int,
                   warnings: list[str]) -> Row | None:
    if not text.strip():
        return None
    if spec.uppercase:
        text = text.upper()
    path = str(resolve_font(spec.font, template))
    ratio = _cap_ratio(path)
    spacing = spec.letter_spacing_mm * ppmm
    cap_px = spec.size_mm * ppmm
    px = round(cap_px / ratio)
    font = _font(path, px)
    width = _text_width(text, font, spacing)
    shrunk = False
    for _ in range(4):
        if width <= max_w:
            break
        px = max(4, int(px * max_w / width) - 1)
        font = _font(path, px)
        spacing *= 0.9
        width = _text_width(text, font, spacing)
        shrunk = True
    cap_px = px * ratio
    cap_mm = cap_px / ppmm
    if cap_mm + 1e-6 < MIN_TEXT_MM:
        why = "foi reduzido para caber" if shrunk else "é pequeno"
        warnings.append(f"texto '{spec.id}' {why}: letra com {cap_mm:.1f} mm (mínimo {MIN_TEXT_MM} mm)")
    stem = font.getbbox("l")
    stem_mm = (stem[2] - stem[0]) / ppmm
    if stem_mm + 1e-6 < MIN_STROKE_MM:
        warnings.append(f"texto '{spec.id}': traço da fonte com {stem_mm:.2f} mm (mínimo {MIN_STROKE_MM} mm)")
    return Row(kind="text", height=round(cap_px * 1.6), text=text, spec=spec, font=font,
               cap_px=round(cap_px), spacing_px=spacing, align=spec.align)


def _prepare_logo(logo: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Converte o logo do organizador para preto e branco e ajusta o tamanho."""
    img = imaging.to_rgb(ImageOps.exif_transpose(logo)).convert("L")
    img = ImageOps.autocontrast(img, cutoff=1)
    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    return img.point(lambda v: 255 if v >= 140 else 0)


def _placeholder_logo(w: int, h: int, ppmm: float) -> Image.Image:
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    lw = max(1, round(0.35 * ppmm))
    _dashed_rect(d, (0, 0, w - 1, h - 1), lw, round(1.5 * ppmm))
    font = _font(str(FONTS_DIR / "InterDisplay-Bold.ttf"), max(8, round(h * 0.45)))
    d.text((w / 2, h / 2), "LOGO", font=font, fill=0, anchor="mm")
    return img


def _dashed_rect(d: ImageDraw.ImageDraw, box, width: int, dash: int, gap: int | None = None,
                 dotted: bool = False) -> None:
    x0, y0, x1, y1 = box
    gap = gap if gap is not None else dash
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        length = max(abs(bx - ax), abs(by - ay))
        if length == 0:
            continue
        pos = 0
        while pos < length:
            end = min(pos + dash, length)
            sx = ax + (bx - ax) * pos / length
            sy = ay + (by - ay) * pos / length
            if dotted:
                r = width / 2 + 0.5
                d.ellipse((sx - r, sy - r, sx + r, sy + r), fill=0)
            else:
                ex = ax + (bx - ax) * end / length
                ey = ay + (by - ay) * end / length
                d.line((sx, sy, ex, ey), fill=0, width=width)
            pos += dash + gap


def _draw_frame(canvas: Image.Image, frame: dict[str, Any], ppmm: float, warnings: list[str]) -> None:
    border = float(frame.get("border_mm", 0))
    if border <= 0:
        return
    if border + 1e-6 < MIN_STROKE_MM:
        warnings.append(f"moldura com traço de {border} mm (mínimo {MIN_STROKE_MM} mm)")
    d = ImageDraw.Draw(canvas)
    inset = float(frame.get("inset_mm", 1)) * ppmm
    lw = max(1, round(border * ppmm))
    radius = round(float(frame.get("corner_radius_mm", 0)) * ppmm)
    w, h = canvas.size
    box = (round(inset), round(inset), round(w - 1 - inset), round(h - 1 - inset))
    style = frame.get("style", "solid")
    if style == "solid":
        d.rounded_rectangle(box, radius=radius, outline=0, width=lw)
    elif style == "double":
        d.rounded_rectangle(box, radius=radius, outline=0, width=lw)
        g = lw * 2 + round(0.4 * ppmm)
        inner = (box[0] + g, box[1] + g, box[2] - g, box[3] - g)
        d.rounded_rectangle(inner, radius=max(0, radius - g), outline=0, width=max(1, lw // 2 + 1))
    elif style == "dashed":
        _dashed_rect(d, box, lw, round(2 * ppmm), round(1.2 * ppmm))
    elif style == "dotted":
        _dashed_rect(d, box, lw, 0, round(1.0 * ppmm), dotted=True)


def _load_ornament(path: Path, width_px: int) -> Image.Image | None:
    """Devolve uma máscara de tinta (L: 255 = preto) do tamanho pedido."""
    if path.suffix.lower() == ".svg":
        try:
            import cairosvg  # type: ignore
        except ImportError:
            log.warning("SVG precisa do pacote cairosvg: %s", path.name)
            return None
        import io
        png = cairosvg.svg2png(url=str(path), output_width=width_px)
        img = Image.open(io.BytesIO(png))
    else:
        img = Image.open(path)
    img = img.convert("RGBA")
    ratio = width_px / img.width
    img = img.resize((width_px, max(1, round(img.height * ratio))), Image.Resampling.LANCZOS)
    lum = img.convert("L")
    alpha = img.getchannel("A")
    ink = Image.eval(lum, lambda v: 255 - v)
    return Image.composite(ink, Image.new("L", img.size, 0), alpha)


def _place(position: str, size: tuple[int, int], label: tuple[int, int],
           photo_box: tuple[int, int, int, int], offset: tuple[float, float], margin: float) -> tuple[int, int]:
    w, h = size
    W, H = label
    ox, oy = offset
    if position.startswith("photo-"):
        px0, py0, px1, py1 = photo_box
        corner = position[len("photo-"):]
        cx = px0 if "left" in corner else px1
        cy = py0 if "top" in corner else py1
        return round(cx - w / 2 + (ox if "left" in corner else -ox)), round(cy - h / 2 + (oy if "top" in corner else -oy))
    x = {"left": margin + ox, "right": W - margin - w - ox}.get(
        "left" if "left" in position else "right" if "right" in position else "center", (W - w) / 2 + ox)
    y = {"top": margin + oy, "bottom": H - margin - h - oy}.get(
        "top" if "top" in position else "bottom" if "bottom" in position else "middle", (H - h) / 2 + oy)
    return round(x), round(y)


def placeholder_photo(size: tuple[int, int] = (800, 1000)) -> Image.Image:
    """Foto genérica (sem pessoas reais) para prévias: céu, sol e silhueta."""
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line((0, y, w, y), fill=(int(120 + 110 * t), int(170 + 70 * t), int(230 - 20 * t)))
    d.ellipse((w * 0.62, h * 0.08, w * 0.88, h * 0.08 + w * 0.26), fill=(255, 236, 160))
    d.polygon([(0, h * 0.78), (w * 0.3, h * 0.6), (w * 0.55, h * 0.74), (w * 0.8, h * 0.58), (w, h * 0.7), (w, h), (0, h)],
              fill=(70, 120, 80))
    cx = w * 0.42
    d.ellipse((cx - w * 0.1, h * 0.36, cx + w * 0.1, h * 0.36 + w * 0.2), fill=(60, 45, 40))
    d.rounded_rectangle((cx - w * 0.17, h * 0.36 + w * 0.22, cx + w * 0.17, h * 1.05), radius=int(w * 0.12),
                        fill=(200, 70, 70))
    return img


def render_label(
    template: Template,
    photo: Image.Image | None,
    ctx: RenderContext,
    label_mm: tuple[float, float],
    profile: PrinterProfile,
    paper: str = "photo",
    face_detect: bool = False,
) -> RenderResult:
    """Monta a etiqueta final (modo L ou 1) na resolução da impressora."""
    warnings: list[str] = []
    ppmm = profile.px_per_mm
    W, H = label_size_px(template, label_mm, profile)
    canvas = Image.new("L", (W, H), 255)
    settings = profile.image_settings(paper)
    variables = template_vars(ctx)

    margin = float(template.photo.get("margin_mm", 2)) * ppmm
    frame = template.frame
    if float(frame.get("border_mm", 0)) > 0:
        frame_inner = (float(frame.get("inset_mm", 1)) + float(frame["border_mm"]) + 1.0) * ppmm
        if frame.get("style") == "double":
            frame_inner += (float(frame["border_mm"]) * 2 + 0.6) * ppmm
        margin = max(margin, frame_inner)
    cx0, cy0, cx1, cy1 = margin, margin, W - margin, H - margin
    content_w = cx1 - cx0
    landscape = template.orientation == "landscape"
    gap = round(1.2 * ppmm)

    aspect = imaging.parse_aspect(template.photo.get("aspect"))
    max_share = float(template.photo.get("max_share", 0.68))
    text_col_w = content_w
    landscape_box: tuple[int, int, int, int] | None = None
    if landscape:
        # no modo paisagem a foto ocupa a altura toda à esquerda; o texto vai à direita
        has_side = bool(template.texts) or template.guest_field.enabled or bool(template.logo.get("enabled"))
        content_h = cy1 - cy0
        ph = content_h
        pw = ph * aspect if aspect else content_w * max_share
        limit = content_w * max_share if has_side else content_w
        if pw > limit:
            pw = limit
            ph = pw / aspect if aspect else content_h
        py = cy0 + (content_h - ph) / 2
        px = cx0 if has_side else cx0 + (content_w - pw) / 2
        landscape_box = (round(px), round(py), round(px + pw), round(py + ph))
        text_col_w = cx1 - (landscape_box[2] + gap)

    # ---- linhas de texto e logo
    rows_top: list[Row] = []
    rows_bottom: list[Row] = []

    def add(row: Row | None, position: str) -> None:
        if row is not None:
            (rows_top if position == "top" else rows_bottom).append(row)

    logo_cfg = template.logo
    logo_row: Row | None = None
    if logo_cfg.get("enabled"):
        lh = round(float(logo_cfg.get("height_mm", 8)) * ppmm)
        logo_img = ctx.logo
        if logo_img is None and logo_cfg.get("file"):
            path = template.dir / str(logo_cfg["file"])
            if path.is_file():
                logo_img = Image.open(path)
        if logo_img is not None:
            img = _prepare_logo(logo_img, int(text_col_w), lh)
            logo_row = Row(kind="logo", height=img.height, image=img)
        elif ctx.placeholder_logo:
            img = _placeholder_logo(min(int(text_col_w), lh * 3), lh, ppmm)
            logo_row = Row(kind="logo", height=lh, image=img)
    if logo_row and logo_cfg.get("position") == "top":
        add(logo_row, "top")

    for spec in template.texts:
        raw = ctx.texts.get(spec.id, spec.default)
        text = fill(str(raw), variables)[: spec.max_chars]
        add(_make_text_row(spec, text, template, ppmm, int(text_col_w), warnings), spec.position)

    g = template.guest_field
    name = clean_guest_name(ctx.guest_name, g.max_chars)
    if g.enabled and ctx.guest_enabled and name:
        gspec = TextSpec(id="guest", font=g.font, size_mm=g.size_mm, align=g.align, position=g.position)
        add(_make_text_row(gspec, fill(g.format, {**variables, "nome": name, "name": name}), template, ppmm,
                           int(text_col_w), warnings), g.position)

    if logo_row and logo_cfg.get("position") != "top":
        add(logo_row, "bottom")

    def block_h(rows: list[Row]) -> int:
        return sum(r.height for r in rows) + round(0.3 * ppmm) * max(0, len(rows) - 1)

    top_h, bottom_h = block_h(rows_top), block_h(rows_bottom)

    # ---- posição da foto
    if not landscape:
        avail_top = cy0 + (top_h + gap if rows_top else 0)
        avail_bot = cy1 - (bottom_h + gap if rows_bottom else 0)
        avail_h = max(avail_bot - avail_top, 8 * ppmm)
        pw, ph = content_w, avail_h
        if aspect:
            ph = pw / aspect
            if ph > avail_h:
                ph, pw = avail_h, avail_h * aspect
        slack = avail_h - ph
        if rows_top and rows_bottom:
            py = avail_top + slack / 2
        elif rows_bottom:
            py = avail_top
        elif rows_top:
            py = avail_top + slack
        else:
            py = avail_top + slack / 2
        px = cx0 + (content_w - pw) / 2
        photo_box = (round(px), round(py), round(px + pw), round(py + ph))
        regions = {"top": (cy0, photo_box[1] - gap / 2), "bottom": (photo_box[3] + gap / 2, cy1)}
        col_x0, col_x1 = cx0, cx1
    else:
        assert landscape_box is not None
        photo_box = landscape_box
        col_x0, col_x1 = photo_box[2] + gap, cx1
        content_h = cy1 - cy0
        sep_tb = gap if rows_top and rows_bottom else 0
        total = top_h + bottom_h + sep_tb
        start = cy0 + max(0, (content_h - total) / 2)
        regions = {"top": (start, start + top_h),
                   "bottom": (start + top_h + sep_tb, start + total)}

    # ---- ornamentos sob a foto
    def draw_ornaments(layer: str) -> None:
        for orn in template.ornaments:
            if orn.layer != layer:
                continue
            mask = _load_ornament(template.dir / orn.file, max(1, round(orn.size_mm * ppmm)))
            if mask is None:
                warnings.append(f"ornamento {orn.file} não pôde ser carregado")
                continue
            xy = _place(orn.position, mask.size, (W, H), photo_box,
                        (orn.offset_mm[0] * ppmm, orn.offset_mm[1] * ppmm), round(1.0 * ppmm))
            canvas.paste(0, (*xy, xy[0] + mask.width, xy[1] + mask.height), mask)

    _draw_frame(canvas, frame, ppmm, warnings)
    draw_ornaments("under")

    # ---- foto
    pw_px, ph_px = photo_box[2] - photo_box[0], photo_box[3] - photo_box[1]
    src = photo if photo is not None else placeholder_photo((max(pw_px, 400), max(ph_px, 400)))
    processed = imaging.process_photo(src, (pw_px, ph_px), settings, face_detect=face_detect)
    radius = round(float(template.photo.get("corner_radius_mm", 0)) * ppmm)
    if radius:
        mask = Image.new("L", processed.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw_px - 1, ph_px - 1), radius=radius, fill=255)
        canvas.paste(processed, photo_box[:2], mask)
    else:
        canvas.paste(processed, photo_box[:2])
    border = float(template.photo.get("border_mm", 0))
    if border > 0:
        if border + 1e-6 < MIN_STROKE_MM:
            warnings.append(f"borda da foto com {border} mm (mínimo {MIN_STROKE_MM} mm)")
        ImageDraw.Draw(canvas).rounded_rectangle(photo_box, radius=radius, outline=0,
                                                 width=max(1, round(border * ppmm)))

    # ---- textos
    d = ImageDraw.Draw(canvas)
    sep = round(0.3 * ppmm)

    def draw_rows(rows: list[Row], region: tuple[float, float]) -> None:
        if not rows:
            return
        y0, y1 = region
        total = block_h(rows)
        y = y0 + max(0, (y1 - y0 - total) / 2)
        for row in rows:
            if row.kind == "logo" and row.image is not None:
                lw = row.image.width
                x = {"left": col_x0, "right": col_x1 - lw}.get(row.align, (col_x0 + col_x1 - lw) / 2)
                canvas.paste(row.image, (round(x), round(y)))
            elif row.font is not None:
                width = _text_width(row.text, row.font, row.spacing_px)
                x = {"left": col_x0, "right": col_x1 - width}.get(row.align, (col_x0 + col_x1 - width) / 2)
                baseline = y + row.cap_px * 1.25
                if row.spacing_px:
                    cx = x
                    for ch in row.text:
                        d.text((cx, baseline), ch, font=row.font, fill=0, anchor="ls")
                        cx += row.font.getlength(ch) + row.spacing_px
                else:
                    d.text((x, baseline), row.text, font=row.font, fill=0, anchor="ls")
            y += row.height + sep

    draw_rows(rows_top, regions["top"])
    draw_rows(rows_bottom, regions["bottom"])
    draw_ornaments("over")

    final = imaging.finalize_label(canvas, settings["output"])
    return RenderResult(image=final, warnings=_dedupe(warnings), photo_box=photo_box, size_px=(W, H))


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
