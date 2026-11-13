import io
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config as C  # noqa: E402
from app.printers import load_profile  # noqa: E402
from app.printers.mock import MockPrinter  # noqa: E402
from app.templates import load_template  # noqa: E402


@pytest.fixture
def b2():
    return load_profile("b2_pro")


@pytest.fixture
def d110m():
    return load_profile("d110m")


@pytest.fixture
def basico():
    return load_template("basico")


def make_photo(size=(1200, 900), fmt="JPEG", color=(180, 120, 90), **save_kwargs) -> bytes:
    img = Image.new("RGB", size, color)
    # um pouco de detalhe para a pipeline ter o que tratar
    for x in range(0, size[0], 40):
        for y in range(0, size[1], 40):
            img.putpixel((x, y), (20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, fmt, **save_kwargs)
    return buf.getvalue()


@pytest.fixture
def photo_bytes():
    return make_photo()


@pytest.fixture
def mock_printer(b2):
    return MockPrinter(b2, {"mock_delay_s": 0})


@pytest.fixture
def test_cfg():
    cfg = C.deep_merge(C.DEFAULTS, {
        "event": {"name": "Festa Teste", "date": "2026-12-31"},
        "template": "basico",
        "guest_name": True,
        "printer": {"profile": "b2_pro", "driver": "mock", "mock_delay_s": 0},
        "limits": {"photos_per_device": 3, "window_minutes": 10, "max_upload_mb": 1},
    })
    return cfg
