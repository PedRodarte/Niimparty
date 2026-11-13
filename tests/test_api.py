"""Fluxo completo pela API: upload -> prévia -> fila -> PNG em output/."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import Booth, create_app
from app.printers.mock import MockPrinter
from tests.conftest import make_photo


@pytest.fixture
def client(tmp_path, test_cfg, b2):
    booth = Booth(test_cfg, printer=MockPrinter(b2, {"mock_delay_s": 0}),
                  uploads_dir=tmp_path / "uploads", output_dir=tmp_path / "output", data_dir=tmp_path / "data")
    app = create_app(test_cfg, booth=booth)
    with TestClient(app) as c:
        c.booth = booth
        c.tmp = tmp_path
        yield c


def wait_done(client, job_id, timeout=10):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        st = client.get(f"/api/job/{job_id}").json()
        if st["status"] == "done":
            return st
        time.sleep(0.05)
    raise AssertionError(st)


def test_page_and_info(client):
    assert client.get("/").status_code == 200
    info = client.get("/api/info").json()
    assert info["event"]["name"] == "Festa Teste"
    assert info["guest"]["enabled"] is True
    assert "take_photo" in info["strings"]
    assert not any(k.startswith("wiz_") for k in info["strings"])
    sample = client.get("/api/sample.png")
    assert sample.status_code == 200 and sample.headers["content-type"] == "image/png"


def test_full_flow_under_5_seconds(client):
    start = time.monotonic()
    res = client.post("/upload", files={"photo": ("x.jpg", make_photo(), "image/jpeg")},
                      data={"guest_name": "Ana"})
    assert res.status_code == 200, res.text
    job = res.json()
    assert client.get(job["preview"]).status_code == 200
    st = client.post(f"/print/{job['id']}").json()
    assert st["status"] in ("queued", "printing", "done")
    wait_done(client, job["id"])
    elapsed = time.monotonic() - start
    outputs = list((client.tmp / "output").glob("*.png"))
    assert len(outputs) == 1
    assert elapsed < 5
    assert (client.tmp / "uploads" / "originals" / f"{job['id']}.jpg").exists()


def test_status_stream_reports_done(client):
    job = client.post("/upload", files={"photo": ("x.jpg", make_photo(), "image/jpeg")}).json()
    client.post(f"/print/{job['id']}")
    wait_done(client, job["id"])
    with client.stream("GET", f"/status/{job['id']}") as stream:
        body = "".join(chunk for chunk in stream.iter_text())
    assert '"status": "done"' in body


def test_rejects_fake_image_by_content(client):
    res = client.post("/upload", files={"photo": ("foto.jpg", b"<html>nao sou foto</html>", "image/jpeg")})
    assert res.status_code == 415
    assert "não é uma foto" in res.json()["message"]


def test_rejects_too_big(client):
    big = b"\xff\xd8" + b"0" * (2 * 1024 * 1024)
    res = client.post("/upload", files={"photo": ("x.jpg", big, "image/jpeg")})
    assert res.status_code == 413


def test_rate_limit_per_device(client):
    ids = []
    for _ in range(4):
        r = client.post("/upload", files={"photo": ("x.png", make_photo(fmt="PNG"), "image/png")})
        ids.append(r.json()["id"])
    for jid in ids[:3]:
        assert client.post(f"/print/{jid}").status_code == 200
    res = client.post(f"/print/{ids[3]}")
    assert res.status_code == 429
    assert "3 fotos" in res.json()["message"]


def test_unknown_job(client):
    assert client.post("/print/naoexiste").status_code == 404
    assert client.get("/api/job/naoexiste").status_code == 404
