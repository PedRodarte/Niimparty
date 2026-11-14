import numpy as np
import pytest
import yaml
from PIL import Image

from app import renderer
from app.renderer import RenderContext, fill, render_label, template_vars
from app.templates import TemplateError, list_templates, load_template, parse_template


def ctx(**kw):
    base = dict(event="Festa Teste", date="2026-12-31", guest_name="")
    base.update(kw)
    return RenderContext(**base)


def test_variables_are_filled():
    v = template_vars(ctx(guest_name="Ana"))
    assert fill("{evento} {ano} {data} {nome}", v) == "Festa Teste 2026 31/12/2026 Ana"


def test_unknown_variables_are_kept():
    assert fill("Oi {desconhecida}", template_vars(ctx())) == "Oi {desconhecida}"


def test_date_format_follows_locale():
    v = template_vars(ctx(date_format="%m/%d/%Y"))
    assert v["data"] == "12/31/2026"


def test_label_size_matches_profile_resolution(basico, b2):
    res = render_label(basico, None, ctx(), (50, 80), b2, "photo")
    assert res.image.size == (591, 945)  # 50 × 80 mm a 300 dpi
    assert res.image.mode == "L"


def test_label_size_order_does_not_matter(basico, b2):
    a = render_label(basico, None, ctx(), (80, 50), b2, "photo")
    assert a.image.size == (591, 945)  # retrato sempre fica em pé


def test_landscape_template_swaps_dimensions(basico, b2):
    basico.orientation = "landscape"
    res = render_label(basico, None, ctx(), (50, 80), b2, "photo")
    assert res.image.size == (945, 591)
    x0, y0, x1, y1 = res.photo_box
    assert x1 < 945 * 0.75  # foto à esquerda, texto à direita


def test_regular_paper_outputs_1bit(basico, b2):
    res = render_label(basico, None, ctx(), (50, 80), b2, "regular")
    assert res.image.mode == "1"


def test_printer_without_grayscale_forces_dither(basico, d110m):
    res = render_label(basico, None, ctx(), (12, 40), d110m, "photo")
    assert res.image.mode == "1"
    assert res.image.size == (320, 96)  # 12 × 40 mm a 203 dpi, tira deitada


def test_photo_box_has_template_aspect(basico, b2):
    res = render_label(basico, None, ctx(), (50, 80), b2, "photo")
    x0, y0, x1, y1 = res.photo_box
    assert abs((x1 - x0) / (y1 - y0) - 0.8) < 0.01


def test_guest_name_only_when_enabled(basico, b2):
    without = render_label(basico, None, ctx(guest_name="Ana", guest_enabled=False), (50, 80), b2, "photo")
    with_name = render_label(basico, None, ctx(guest_name="Ana", guest_enabled=True), (50, 80), b2, "photo")
    assert np.asarray(without.image).tolist() != np.asarray(with_name.image).tolist()
    # sem nome digitado, nada muda mesmo com o campo ligado
    empty = render_label(basico, None, ctx(guest_name="  ", guest_enabled=True), (50, 80), b2, "photo")
    assert np.array_equal(np.asarray(empty.image), np.asarray(without.image))


def test_text_override_from_config(basico, b2):
    a = render_label(basico, None, ctx(), (50, 80), b2, "photo")
    b = render_label(basico, None, ctx(texts={"title": "Outro texto"}), (50, 80), b2, "photo")
    assert not np.array_equal(np.asarray(a.image), np.asarray(b.image))


def test_tiny_label_warns_about_legibility(basico, d110m):
    res = render_label(basico, None, ctx(guest_name="Ana"), (12, 20), d110m, "regular")
    assert any("mínimo 2.5 mm" in w for w in res.warnings)


def test_normal_label_has_no_warnings(basico, b2):
    res = render_label(basico, None, ctx(guest_name="Ana"), (50, 80), b2, "photo")
    assert res.warnings == []


def test_real_photo_is_used(basico, b2):
    black = Image.new("RGB", (800, 1000), (0, 0, 0))
    res = render_label(basico, black, ctx(), (50, 80), b2, "regular")
    x0, y0, x1, y1 = res.photo_box
    inner = np.asarray(res.image.convert("L"))[y0 + 20:y1 - 20, x0 + 20:x1 - 20]
    assert inner.mean() < 40


def test_guest_name_is_sanitized():
    assert renderer.clean_guest_name("  Ana\n\t  Maria\x00 ", 24) == "Ana Maria"
    assert len(renderer.clean_guest_name("x" * 100, 24)) == 24


# ------------------------------------------------------------ modelos


def test_all_bundled_templates_are_valid(b2):
    names = list_templates()
    assert "basico" in names
    for name in names:
        tpl = load_template(name)  # strict: levanta erro se inválido
        res = render_label(tpl, None, ctx(guest_name="Ana"), (50, 80), b2, "photo")
        assert res.image.size in ((591, 945), (945, 591))


def test_template_validation_reports_errors(tmp_path):
    data = {
        "name": "Ruim",
        "orientation": "diagonal",
        "photo": {"aspect": "x:y"},
        "texts": [{"id": "a"}, {"id": "a"}, {"default": "sem id"}],
        "guest_field": {"enabled": True, "format": "sem variavel"},
        "ornaments": [{"file": "ornaments/nao-existe.png", "position": "meio"}],
    }
    _, errors = parse_template(data, "ruim", tmp_path)
    text = " | ".join(errors)
    for expected in ("orientation", "photo.aspect", "repetido", "precisa ter um 'id'", "{nome}",
                     "não encontrado", "position inválida"):
        assert expected in text


def test_load_template_strict_raises(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "template.yaml").write_text(yaml.safe_dump({"orientation": "torta"}), encoding="utf-8")
    with pytest.raises(TemplateError):
        load_template("x", templates_dir=tmp_path)


def test_elongated_label_uses_landscape_strip(basico, d110m):
    res = render_label(basico, None, ctx(), (12, 40), d110m, "regular")
    w, h = res.image.size
    assert w > h * 3
    x0, y0, x1, y1 = res.photo_box
    assert x1 < w / 2  # foto à esquerda, texto à direita


def test_text_scales_down_on_smaller_labels(basico, b2):
    big = render_label(basico, None, ctx(guest_name="Ana"), (50, 80), b2, "photo")
    small = render_label(basico, None, ctx(guest_name="Ana"), (30, 50), b2, "photo")
    # na etiqueta menor a foto continua ocupando boa parte da altura
    for res in (big, small):
        x0, y0, x1, y1 = res.photo_box
        assert (y1 - y0) / res.image.height > 0.5


# ------------------------------------------------------------ etiqueta com moldura já impressa


def test_preprinted_template_fixed_layout(b2):
    from app.renderer import paper_preview
    from app.templates import load_template

    tpl = load_template("moldura-colorida-54x66")
    assert tpl.fixed_layout and tpl.label_mm == (54.0, 66.0)
    ctx = RenderContext(event="Festa", date="2026-12-24", guest_name="Convidado", guest_enabled=True)
    res = render_label(tpl, None, ctx, (54, 66), b2, "photo")
    ppmm = b2.px_per_mm
    x, y, w, h = tpl.photo["box_mm"]
    assert res.photo_box == (round(x * ppmm), round(y * ppmm), round((x + w) * ppmm), round((y + h) * ppmm))
    assert res.warnings == []
    # nada é impresso na moldura colorida (fora da janela e da faixa de texto)
    img = res.image.convert("L")
    assert img.getpixel((round(2 * ppmm), round(2 * ppmm))) == 255
    # a prévia pinta a moldura com a cor do papel, mas não muda a imagem enviada à impressora
    shown = paper_preview(res.image, tpl)
    assert shown.getpixel((round(2 * ppmm), round(2 * ppmm))) != (255, 255, 255)
    assert res.image.mode in ("L", "1")


def test_preprinted_template_merges_rows(b2):
    from app.templates import load_template

    tpl = load_template("moldura-colorida-54x66")
    ctx = RenderContext(event="Festa", date="2026-12-24", guest_name="Leo", guest_enabled=True)
    res = render_label(tpl, None, ctx, (54, 66), b2, "photo")
    assert not any("pequeno" in w for w in res.warnings)


def test_box_outside_label_is_an_error(tmp_path):
    from app.templates import parse_template

    _, errors = parse_template({"label_mm": [54, 66], "photo": {"box_mm": [10, 10, 50, 40]}}, "x", tmp_path)
    assert any("passa da borda" in e for e in errors)
