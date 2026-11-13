import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_qr", ROOT / "tools" / "make_qr.py")
make_qr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_qr)


@pytest.mark.parametrize("raw,escaped", [
    ("simples", "simples"),
    ('a;b,c:d"e\\f', 'a\\;b\\,c\\:d\\"e\\\\f'),
])
def test_wifi_escape(raw, escaped):
    assert make_qr.wifi_escape(raw) == escaped


def test_wifi_payload_wpa():
    assert make_qr.wifi_payload("Festa", "senha;1") == "WIFI:T:WPA;S:Festa;P:senha\\;1;;"


def test_wifi_payload_open_network():
    assert make_qr.wifi_payload("Aberta", "") == "WIFI:T:nopass;S:Aberta;;"


def test_plate_pdf_is_a5(tmp_path):
    cfg = make_qr.C.deep_merge(make_qr.C.DEFAULTS, {"event": {"name": "Festa", "date": "2026-12-31"}})
    out = tmp_path / "placa.pdf"
    make_qr.draw_plate(out, cfg, "http://192.168.0.10:8000", ("Rede", "senha", "WPA"))
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    m = re.search(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", data)
    assert m and abs(float(m.group(1)) - 419.53) < 0.1 and abs(float(m.group(2)) - 595.28) < 0.1  # A5
