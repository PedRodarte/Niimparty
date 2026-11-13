"""Confere se um modelo está correto, sem precisar rodar a cabine.

    python tools/validate_template.py              # todos os modelos
    python tools/validate_template.py meu-modelo   # só um
    python tools/validate_template.py --size 50x30 meu-modelo

Verifica:
  - sintaxe do template.yaml e campos obrigatórios
  - arquivos de ornamento e fontes
  - regras de legibilidade da impressão térmica (letra >= 2,5 mm, traço >= 0,3 mm)
    em todos os tamanhos de etiqueta testados

Sai com código 1 se algum modelo tiver erro (avisos não contam como erro).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):  # acentos e símbolos no terminal do Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml  # noqa: E402

from app.printers import load_profile  # noqa: E402
from app.renderer import FONTS_DIR, RenderContext, render_label  # noqa: E402
from app.templates import TEMPLATES_DIR, list_templates, parse_template  # noqa: E402

DEFAULT_SIZES = [(50, 80), (50, 50), (50, 30)]


def font_exists(name: str, template_dir: Path) -> bool:
    for base in (template_dir / "fonts", FONTS_DIR):
        if (base / f"{name}.ttf").is_file() or (base / f"{name}.otf").is_file():
            return True
    return False


def check(name: str, sizes, profile) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    directory = TEMPLATES_DIR / name
    path = directory / "template.yaml"
    if not path.is_file():
        return [f"não achei {path}"], []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"erro de sintaxe no YAML: {exc}"], []
    try:
        tpl, errs = parse_template(data, name, directory)
    except Exception as exc:  # noqa: BLE001
        return [str(exc)], []
    errors += errs
    if "name" not in (data or {}):
        warnings.append("sem 'name': o nome da pasta será usado")

    fonts = {t.font for t in tpl.texts}
    if tpl.guest_field.enabled:
        fonts.add(tpl.guest_field.font)
    for font in sorted(fonts):
        if not font_exists(font, directory):
            errors.append(f"fonte não encontrada: {font} (coloque {font}.ttf em {name}/fonts/ ou assets/fonts/)")

    if not errors:
        ex = (data or {}).get("example") or {}
        ctx = RenderContext(event=str(ex.get("event", "Nome do Evento")), date="2026-12-24",
                            guest_name=str(ex.get("guest", "Convidada")), placeholder_logo=True)
        for size in sizes:
            try:
                res = render_label(tpl, None, ctx, size, profile, "photo")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"falhou ao montar {size[0]:g}x{size[1]:g}: {exc}")
                continue
            for w in res.warnings:
                warnings.append(f"{size[0]:g}x{size[1]:g} mm: {w}")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("templates", nargs="*")
    p.add_argument("--size", action="append", help="tamanho extra para testar, ex.: 50x30 (pode repetir)")
    p.add_argument("--printer", default="b2_pro")
    args = p.parse_args(argv)

    sizes = DEFAULT_SIZES
    if args.size:
        sizes = [tuple(float(v) for v in s.lower().split("x")) for s in args.size]
    profile = load_profile(args.printer)
    names = args.templates or list_templates()
    bad = 0
    for name in names:
        errors, warnings = check(name, sizes, profile)
        mark = "✗" if errors else ("!" if warnings else "✓")
        print(f"{mark} {name}")
        for e in errors:
            print(f"    erro:  {e}")
        for w in warnings:
            print(f"    aviso: {w}")
        bad += bool(errors)
    print(f"\n{len(names) - bad} de {len(names)} modelo(s) sem erros.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
