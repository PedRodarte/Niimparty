import io

import numpy as np
import pytest
from PIL import Image

from app import imaging
from tests.conftest import make_photo


def test_rejects_non_image():
    with pytest.raises(imaging.InvalidImage):
        imaging.load_image(b"isto nao e uma foto, mesmo que se chame foto.jpg")


def test_rejects_empty():
    with pytest.raises(imaging.InvalidImage):
        imaging.load_image(b"")


def test_rejects_truncated_jpeg():
    data = make_photo()
    with pytest.raises(imaging.InvalidImage):
        imaging.load_image(data[: len(data) // 3])


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_accepts_common_formats(fmt):
    img = imaging.load_image(make_photo(fmt=fmt))
    assert img.mode == "RGB"
    assert img.size == (1200, 900)


def test_accepts_heic():
    pillow_heif = pytest.importorskip("pillow_heif")
    buf = io.BytesIO()
    try:
        Image.new("RGB", (64, 48), (200, 50, 50)).save(buf, "HEIF")
    except Exception:  # pragma: no cover - encoder ausente
        pytest.skip("encoder HEIF indisponível")
    img = imaging.load_image(buf.getvalue())
    assert img.size == (64, 48)
    assert pillow_heif  # silencia aviso


def test_transparent_png_gets_white_background():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    out = imaging.load_image(buf.getvalue())
    assert out.getpixel((5, 5)) == (255, 255, 255)


def test_exif_rotation_is_applied():
    img = Image.new("RGB", (200, 100), (10, 200, 10))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: girar 90° no sentido horário
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    out = imaging.load_image(buf.getvalue())
    assert out.size == (100, 200)


@pytest.mark.parametrize("aspect,expected", [("4:5", 0.8), ("1:1", 1.0), ("3:2", 1.5), ("full", None), (None, None)])
def test_parse_aspect(aspect, expected):
    assert imaging.parse_aspect(aspect) == expected


@pytest.mark.parametrize("size", [(1200, 900), (900, 1200), (500, 500)])
def test_crop_to_aspect(size):
    img = Image.new("RGB", size)
    out = imaging.crop_to_aspect(img, 0.8)
    assert abs(out.width / out.height - 0.8) < 0.01
    assert out.width <= size[0] and out.height <= size[1]


def test_crop_respects_focus():
    img = Image.new("L", (1000, 500), 0)
    img.paste(255, (900, 0, 1000, 500))  # faixa branca à direita
    out = imaging.crop_to_aspect(img, 1.0, focus=(0.95, 0.5))
    assert np.asarray(out)[:, -10:].mean() == 255


def test_clahe_increases_local_contrast():
    rng = np.random.default_rng(1)
    flat = (120 + rng.integers(0, 12, (200, 160))).astype(np.uint8)
    out = imaging.clahe(flat, 2.0)
    assert out.shape == flat.shape and out.dtype == np.uint8
    assert out.std() > flat.std() * 2


def test_gamma_brightens_midtones():
    arr = np.full((4, 4), 100, np.uint8)
    assert imaging.apply_gamma(arr, 0.8).mean() > 100


@pytest.mark.parametrize("method", ["atkinson", "floyd-steinberg"])
def test_dither_is_binary_and_keeps_tone(method):
    grad = np.tile(np.linspace(0, 255, 200, dtype=np.uint8), (60, 1))
    out = np.asarray(imaging.dither(Image.fromarray(grad, "L"), method))
    assert set(np.unique(out)) <= {0, 255}
    assert abs(out.mean() - grad.mean()) < 25


def test_dither_keeps_pure_black_and_white():
    img = Image.new("L", (50, 20), 255)
    img.paste(0, (0, 0, 25, 20))
    out = np.asarray(imaging.dither(img, "atkinson"))
    assert out[:, :25].max() == 0 and out[:, 25:].min() == 255


def test_process_photo_gray_and_dither():
    src = imaging.load_image(make_photo())
    gray = imaging.process_photo(src, (300, 375), {"output": "gray8"})
    assert gray.size == (300, 375) and gray.mode == "L"
    dith = imaging.process_photo(src, (300, 375), {"output": "dither", "dither": "atkinson"})
    assert set(np.unique(np.asarray(dith))) <= {0, 255}


def test_finalize_label_modes():
    img = Image.new("L", (10, 10), 200)
    assert imaging.finalize_label(img, "gray8").mode == "L"
    assert imaging.finalize_label(img, "dither").mode == "1"


def test_gray16_has_at_most_16_levels():
    ramp = Image.linear_gradient("L").resize((256, 64))
    out = imaging.finalize_label(ramp, "gray16")
    assert out.mode == "L"
    assert len(set(out.getdata())) <= 16
    assert out.getpixel((0, 0)) in (0, 255) and abs(out.getpixel((0, 63)) - 255) <= 17
