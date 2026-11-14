"""Painel /admin: PIN, prévia ao vivo, salvar configuração, fila e fotos."""

import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import Booth, create_app
from app.printers.mock import MockPrinter
from tests.conftest import make_photo

PIN = "4321"


@pytest.fixture
def client(tmp_path, test_cfg, b2):
    booth = Booth(test_cfg, printer=MockPrinter(b2, {"mock_delay_s": 0}),
                  uploads_dir=tmp_path / "uploads", output_dir=tmp_path / "output", data_dir=tmp_path / "data",
                  config_path=tmp_path / "config.yaml", admin_pin=PIN)
    app = create_app(test_cfg, booth=booth)
    with TestClient(app) as c:
        c.booth = booth
        c.tmp = tmp_path
        yield c


def login(client, pin=PIN):
    return client.post("/admin/api/login", json={"pin": pin})


def printed_job(client, name="Ana"):
    job = client.post("/upload", files={"photo": ("x.jpg", make_photo(), "image/jpeg")},
                      data={"guest_name": name}).json()
    client.post(f"/print/{job['id']}")
    start = time.monotonic()
    while client.get(f"/api/job/{job['id']}").json()["status"] != "done":
        assert time.monotonic() - start < 10
        time.sleep(0.05)
    return job["id"]


def test_admin_page_and_strings_are_public(client):
    assert client.get("/admin").status_code == 200
    strings = client.get("/admin/api/strings").json()["strings"]
    assert "adm_title" in strings and not any(k.startswith("wiz_") for k in strings)


def test_api_requires_pin(client):
    assert client.get("/admin/api/state").status_code == 401
    assert client.post("/admin/api/queue/pause").status_code == 401
    assert client.get("/admin/api/photos.zip").status_code == 401


def test_wrong_pin_and_lockout(client):
    for _ in range(5):
        assert login(client, "0000").status_code == 401
    res = login(client, PIN)  # mesmo com o PIN certo, espera o bloqueio passar
    assert res.status_code == 429


def test_login_sets_session(client):
    res = login(client)
    assert res.status_code == 200
    assert "httponly" in res.headers["set-cookie"].lower()
    st = client.get("/admin/api/state").json()
    assert st["config"]["template"] == "basico"
    assert any(t["id"] == "moldura-colorida-54x66" and t["label_mm"] == [54, 66] for t in st["templates"])
    client.post("/admin/api/logout")
    assert client.get("/admin/api/state").status_code == 401


def test_live_preview_does_not_save(client):
    login(client)
    settings = {"template": "natal", "event": {"name": "Ceia", "date": "2026-12-24"}, "texts": {}}
    res = client.post("/admin/api/preview", data={"settings": json.dumps(settings)})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["images"][0].startswith("data:image/png;base64,")
    assert client.booth.cfg["template"] == "basico"
    assert not (client.tmp / "config.yaml").exists()


def test_preview_with_test_photo(client):
    login(client)
    res = client.post("/admin/api/preview", data={"settings": "{}"},
                      files={"photo": ("t.jpg", make_photo(), "image/jpeg")})
    assert res.status_code == 200
    bad = client.post("/admin/api/preview", data={"settings": "{}"},
                      files={"photo": ("t.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 415


def test_preprinted_preview_has_one_image_per_paper_color(client):
    login(client)
    res = client.post("/admin/api/preview",
                      data={"settings": json.dumps({"template": "moldura-colorida-54x66"})}).json()
    assert len(res["images"]) == 3
    assert res["config"]["label"] == {"width_mm": 54.0, "height_mm": 66.0}  # tamanho do modelo


def test_save_config_applies_and_persists(client):
    login(client)
    body = {"template": "aniversario", "event": {"name": "Aniversário da Lia", "date": "2027-03-05"},
            "texts": {"title": "Lia 7 anos", "inexistente": "x"}, "guest_name": False,
            "label": {"width_mm": 50, "height_mm": 50}, "paper": "regular"}
    res = client.put("/admin/api/config", json=body)
    assert res.status_code == 200, res.text
    cfg = client.booth.cfg
    assert cfg["template"] == "aniversario" and cfg["event"]["name"] == "Aniversário da Lia"
    assert "inexistente" not in cfg["texts"]
    assert cfg["label"] == {"width_mm": 50.0, "height_mm": 50.0} and cfg["paper"] == "regular"
    assert "Aniversário da Lia" in (client.tmp / "config.yaml").read_text(encoding="utf-8")
    # a página dos convidados já usa o modelo novo
    assert client.get("/api/info").json()["template"]["id"] == "aniversario"


@pytest.mark.parametrize("body,error", [
    ({"template": "nao-existe"}, "adm_err_template"),
    ({"event": {"date": "31/12/2026"}}, "adm_err_date"),
    ({"label": {"width_mm": 1, "height_mm": 80}}, "adm_err_label"),
    ({"paper": "glossy"}, "adm_err_paper"),
])
def test_save_config_validation(client, body, error):
    login(client)
    res = client.put("/admin/api/config", json=body)
    assert res.status_code == 400 and res.json()["error"] == error


def test_logo_upload_and_remove(client):
    login(client)
    res = client.post("/admin/api/logo", files={"logo": ("l.png", make_photo(fmt="PNG"), "image/png")})
    assert res.status_code == 200
    assert client.booth.logo_path.is_file()
    assert client.get("/admin/api/state").json()["logo"] is True
    client.delete("/admin/api/logo")
    assert not client.booth.logo_path.exists()


def test_pause_resume(client):
    login(client)
    assert client.post("/admin/api/queue/pause").json()["paused"] is True
    assert client.get("/api/job/x").status_code == 404
    assert client.post("/admin/api/queue/resume").json()["paused"] is False


def test_jobs_reprint_delete(client):
    login(client)
    job_id = printed_job(client)
    jobs = client.get("/admin/api/jobs").json()["jobs"]
    assert [j["id"] for j in jobs] == [job_id] and jobs[0]["status"] == "done"
    assert client.get(f"/admin/api/jobs/{job_id}.png").status_code == 200
    assert client.post(f"/admin/api/jobs/{job_id}/reprint").json()["status"] in ("queued", "printing", "done")
    start = time.monotonic()
    while client.get(f"/api/job/{job_id}").json()["status"] != "done":
        assert time.monotonic() - start < 10
        time.sleep(0.05)
    assert len(client.booth.printer.printed) == 2
    assert client.delete(f"/admin/api/jobs/{job_id}").status_code == 200
    assert client.get("/admin/api/jobs").json()["jobs"] == []
    assert list((client.tmp / "output").glob("*.png")) == []


def test_zip_and_delete_all(client):
    login(client)
    printed_job(client, "Ana")
    printed_job(client, "Leo")
    res = client.get("/admin/api/photos.zip")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
    assert len([n for n in names if n.startswith("fotos/")]) == 2
    assert len([n for n in names if n.startswith("etiquetas/")]) == 2
    assert any(n.endswith("_Ana.jpg") for n in names)
    assert client.post("/admin/api/jobs/delete-all").json()["deleted"] == 2
    assert not any((client.tmp / "uploads").rglob("*.*"))
    assert not any((client.tmp / "output").glob("*.png"))
