"""Gera etiquetas de exemplo de todos os modelos (ou de um só).

    python tools/preview.py                      # todos os modelos, tamanhos padrão
    python tools/preview.py natal                # só o modelo natal
    python tools/preview.py --photo minha.jpg    # usa uma foto sua
    python tools/preview.py --size 50x30 --paper regular --printer d110m

Saídas:
  templates/<modelo>/preview.png   miniatura usada no /admin (versionada)
  previews/<modelo>_<tamanho>_<papel>.png
  previews/todas.png               folha com todos os modelos lado a lado
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):  # acentos e símbolos no terminal do Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.imaging import load_image  # noqa: E402
from app.printers import load_profile  # noqa: E402
from app.renderer import FONTS_DIR, RenderContext, paper_preview, placeholder_photo, render_label  # noqa: E402
from app.templates import TemplateError, list_templates, load_template  # noqa: E402

OUT = ROOT / "previews"
DEFAULT_SET = [
    ("b2_pro", (50, 80), "photo"),
    ("b2_pro", (50, 80), "regular"),
    ("b2_pro", (50, 50), "photo"),
    ("b2_pro", (50, 30), "regular"),
    ("d110m", (12, 40), "regular"),
]
SAMPLE_DATE = "2026-12-24"


def parse_size(text: str) -> tuple[float, float]:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)[x×](\d+(?:\.\d+)?)", text.lower())
    if not m:
        raise argparse.ArgumentTypeError("use LARGURAxALTURA, por exemplo 50x80")
    return float(m.group(1)), float(m.group(2))


def context_for(tpl, date_format: str) -> RenderContext:
    ex = tpl.raw.get("example") or {}
    return RenderContext(
        event=str(ex.get("event", "Nome do Evento")),
        date=str(ex.get("date", SAMPLE_DATE)),
        guest_name=str(ex.get("guest", "Convidado")),
        guest_enabled=True,
        date_format=date_format,
        placeholder_logo=True,
    )


def sheet(images: list[tuple[str, Image.Image]], path: Path) -> None:
    """Junta as etiquetas numa folha, todas na mesma escala, com o nome embaixo."""
    if not images:
        return
    pad, caption = 40, 70
    font = ImageFont.truetype(str(FONTS_DIR / "InterDisplay-SemiBold.ttf"), 34)
    cell_h = max(im.height for _, im in images)
    width = sum(im.width for _, im in images) + pad * (len(images) + 1)
    out = Image.new("RGB", (width, cell_h + caption + pad * 2), (226, 222, 214))
    d = ImageDraw.Draw(out)
    x = pad
    for name, im in images:
        y = pad + (cell_h - im.height) // 2
        out.paste((0, 0, 0), (x + 6, y + 6, x + im.width + 6, y + im.height + 6))
        out.paste(im.convert("RGB"), (x, y))
        d.text((x + im.width / 2, pad + cell_h + 24), name, fill=(30, 30, 30), font=font, anchor="mt")
        x += im.width + pad
    out.save(path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("templates", nargs="*", help="modelos (padrão: todos)")
    p.add_argument("--photo", type=Path, help="foto para usar nas prévias")
    p.add_argument("--size", type=parse_size, help="tamanho da etiqueta, ex.: 50x30")
    p.add_argument("--paper", choices=["photo", "regular"], help="tipo de papel")
    p.add_argument("--printer", default=None, help="perfil da impressora (padrão: b2_pro)")
    p.add_argument("--lang-date", default="%d/%m/%Y", help="formato da data")
    args = p.parse_args(argv)

    names = args.templates or list_templates()
    combos = DEFAULT_SET
    if args.size or args.paper or args.printer:
        combos = [(args.printer or "b2_pro", args.size or (50, 80), args.paper or "photo")]

    photo = load_image(args.photo.read_bytes()) if args.photo else placeholder_photo((1600, 2000))
    OUT.mkdir(exist_ok=True)
    profiles = {}
    sheet_items: list[tuple[str, Image.Image]] = []
    failed = False

    for name in names:
        try:
            tpl = load_template(name)
        except TemplateError as exc:
            print(f"✗ {name}: {exc}")
            failed = True
            continue
        ctx = context_for(tpl, args.lang_date)
        print(f"• {tpl.name} ({name})")
        tpl_combos = combos
        if tpl.label_mm and combos is DEFAULT_SET:  # modelo feito para um tamanho só
            tpl_combos = [("b2_pro", tpl.label_mm, "photo"), ("b2_pro", tpl.label_mm, "regular")]
        for prof_id, size, paper in tpl_combos:
            profile = profiles.setdefault(prof_id, load_profile(prof_id))
            res = render_label(tpl, photo, ctx, size, profile, paper)
            tag = f"{size[0]:g}x{size[1]:g}"
            path = OUT / f"{name}_{tag}_{paper}_{prof_id}.png"
            shown = paper_preview(res.image, tpl)
            shown.save(path)
            note = "" if not res.warnings else "  ⚠ " + "; ".join(res.warnings)
            print(f"    {tag} {paper:<7} {prof_id:<7} -> {path.relative_to(ROOT)}{note}")
            if (prof_id, size, paper) == tpl_combos[0]:
                sheet_items.append((tpl.name, shown))
                if not args.photo and combos is DEFAULT_SET:
                    thumb = shown.copy()
                    thumb.thumbnail((360, 360), Image.Resampling.LANCZOS)
                    thumb.save(tpl.preview_path, optimize=True)

    sheet(sheet_items, OUT / "todas.png")
    print(f"\nFolha com todos: {(OUT / 'todas.png').relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
