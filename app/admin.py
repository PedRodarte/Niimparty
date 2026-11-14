"""Painel do organizador (/admin), protegido por PIN.

Rotas (todas em /admin/api, menos a página):
  GET    /admin                      página (web/admin.html)
  POST   /admin/api/login            {pin} -> cookie de sessão
  POST   /admin/api/logout
  GET    /admin/api/state            configuração, modelos, fila
  GET    /admin/api/templates/{id}.png  miniatura do modelo
  POST   /admin/api/preview          prévia ao vivo (não grava nada)
  PUT    /admin/api/config           salva modelo, textos, etiqueta e papel
  POST   /admin/api/logo             envia o logo     DELETE: remove
  POST   /admin/api/queue/pause      pausa            /resume: retoma
  GET    /admin/api/jobs             fotos do evento
  GET    /admin/api/jobs/{id}.png    etiqueta de uma foto
  POST   /admin/api/jobs/{id}/reprint
  DELETE /admin/api/jobs/{id}
  POST   /admin/api/jobs/delete-all
  GET    /admin/api/photos.zip       todas as fotos e etiquetas

As fotos e a configuração nunca saem deste computador; o painel só é
acessível na rede local, como a página dos convidados.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import hmac
import io
import json
import secrets
import tempfile
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageOps
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from . import config as C
from .i18n import load_locale
from .imaging import InvalidImage, load_image
from .printers import list_profiles, load_profile
from .queue import ACTIVE, PRINTING
from .renderer import paper_preview, placeholder_photo, render_label
from .templates import TemplateError, list_templates, load_template

if TYPE_CHECKING:
    from .main import Booth

COOKIE = "niimparty_admin"
SESSION_S = 12 * 3600
MAX_TRIES, LOCK_S = 5, 60
MAX_LOGO_MB = 5
EDITABLE = ("event", "template", "texts", "guest_name", "label", "paper")


class SettingsError(ValueError):
    def __init__(self, key: str, **kwargs: Any):
        super().__init__(key)
        self.key, self.kwargs = key, kwargs


def merge_settings(cfg: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Aplica o que veio do painel sobre a configuração atual, validando tudo."""
    new = copy.deepcopy(cfg)
    tid = str(body.get("template", cfg["template"]))
    if tid not in list_templates():
        raise SettingsError("adm_err_template")
    try:
        template = load_template(tid)
    except TemplateError as exc:
        raise SettingsError("adm_err_template_broken", detail=str(exc)) from exc
    new["template"] = tid

    event = body.get("event") or {}
    name = str(event.get("name", cfg["event"].get("name", ""))).strip()[:80]
    date = str(event.get("date", cfg["event"].get("date", "")) or "").strip()
    if date:
        try:
            date = dt.date.fromisoformat(date).isoformat()
        except ValueError as exc:
            raise SettingsError("adm_err_date") from exc
    new["event"] = {**cfg["event"], "name": name, "date": date}

    texts_in = body.get("texts")
    if texts_in is None:
        texts_in = cfg.get("texts") or {}
    texts = {}
    for spec in template.texts:
        if spec.id in texts_in:
            texts[spec.id] = str(texts_in[spec.id])[: spec.max_chars]
    new["texts"] = texts
    new["guest_name"] = bool(body.get("guest_name", cfg.get("guest_name"))) and template.guest_field.enabled

    profile = load_profile(cfg["printer"]["profile"])
    if template.label_mm:
        w, h = template.label_mm
    else:
        label = body.get("label") or cfg["label"]
        try:
            w, h = float(label["width_mm"]), float(label["height_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SettingsError("adm_err_label") from exc
        if not (5 <= w <= 120 and 5 <= h <= 300):
            raise SettingsError("adm_err_label")
    new["label"] = {"width_mm": w, "height_mm": h}

    paper = str(body.get("paper", cfg.get("paper", "photo")))
    if paper not in ("photo", "regular"):
        raise SettingsError("adm_err_paper")
    new["paper"] = paper if profile.grayscale else "regular"
    return new


def _png_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def admin_router(get_booth: Callable[[], "Booth"]) -> APIRouter:
    router = APIRouter()
    tries: dict[str, list[float]] = {}

    def strings(b: "Booth") -> dict[str, str]:
        return load_locale(b.lang)

    def err(status: int, key: str, b: "Booth", **kwargs: Any) -> JSONResponse:
        text = strings(b).get(key, key)
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
        return JSONResponse({"error": key, "message": text}, status_code=status)

    def require_admin(request: Request) -> "Booth":
        b = get_booth()
        token = request.cookies.get(COOKIE, "")
        expires = b.admin_sessions.get(token)
        if not token or not expires or expires < time.time():
            b.admin_sessions.pop(token, None)
            raise HTTPException(401, detail="adm_session_expired")
        return b

    # ------------------------------------------------------------ página e login

    @router.get("/admin", include_in_schema=False)
    async def admin_page():
        return FileResponse(C.WEB_DIR / "admin.html", headers={"Cache-Control": "no-cache"})

    @router.get("/admin/api/strings")
    async def admin_strings():
        b = get_booth()
        s = strings(b)
        keep = ("html_lang", "date_format", "error_", "adm_", "status_")
        return {"lang": b.lang, "strings": {k: v for k, v in s.items() if k.startswith(keep)}}

    @router.post("/admin/api/login")
    async def login(request: Request):
        b = get_booth()
        ip = request.client.host if request.client else "?"
        now = time.time()
        recent = [t for t in tries.get(ip, []) if now - t < LOCK_S]
        tries[ip] = recent
        if len(recent) >= MAX_TRIES:
            return err(429, "adm_locked", b, s=int(LOCK_S - (now - recent[0])) + 1)
        pin = b.admin_pin()
        if not pin:
            return err(503, "adm_no_pin", b)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        given = str(body.get("pin", ""))
        if not hmac.compare_digest(given.encode(), pin.encode()):
            recent.append(now)
            return err(401, "adm_wrong_pin", b)
        tries.pop(ip, None)
        for t, exp in list(b.admin_sessions.items()):
            if exp < now:
                b.admin_sessions.pop(t, None)
        token = secrets.token_urlsafe(24)
        b.admin_sessions[token] = now + SESSION_S
        res = JSONResponse({"ok": True})
        res.set_cookie(COOKIE, token, max_age=SESSION_S, httponly=True, samesite="strict", path="/admin")
        return res

    @router.post("/admin/api/logout")
    async def logout(request: Request):
        get_booth().admin_sessions.pop(request.cookies.get(COOKIE, ""), None)
        res = JSONResponse({"ok": True})
        res.delete_cookie(COOKIE, path="/admin")
        return res

    # ------------------------------------------------------------ estado

    def state_payload(b: "Booth") -> dict[str, Any]:
        templates = []
        for tid in list_templates():
            try:
                t = load_template(tid)
            except TemplateError:
                continue
            templates.append({
                "id": t.id, "name": t.name, "description": t.description,
                "texts": [{"id": s.id, "label": s.label or s.id, "default": s.default, "max_chars": s.max_chars}
                          for s in t.texts],
                "guest": t.guest_field.enabled,
                "label_mm": list(t.label_mm) if t.label_mm else None,
                "logo": bool(t.logo.get("enabled")),
                "thumb": f"/admin/api/templates/{t.id}.png",
            })
        p = b.profile
        q = b.queue
        cfg = b.cfg
        return {
            "config": {k: cfg.get(k) for k in EDITABLE},
            "templates": templates,
            "profile": {"id": p.id, "model": p.model, "status": p.status, "grayscale": p.grayscale,
                        "label_sizes": p.label_sizes_mm, "profiles": list_profiles()},
            "driver": cfg["printer"].get("driver", "mock"),
            "queue": {"paused": q.paused, "reason": q.pause_reason, "length": q.queue_length()},
            "logo": b.logo_path.is_file(),
            "url": C.public_url(cfg),
        }

    @router.get("/admin/api/state")
    async def state(b: "Booth" = Depends(require_admin)):
        return state_payload(b)

    @router.get("/admin/api/templates/{tid}.png")
    async def template_thumb(tid: str, b: "Booth" = Depends(require_admin)):
        if tid not in list_templates():
            raise HTTPException(404)
        path = load_template(tid, strict=False).preview_path
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png")

    # ------------------------------------------------------------ prévia e configuração

    @router.post("/admin/api/preview")
    async def preview(settings: str = Form("{}"), photo: UploadFile | None = File(None),
                      b: "Booth" = Depends(require_admin)):
        try:
            cfg = merge_settings(b.cfg, json.loads(settings or "{}"))
        except SettingsError as exc:
            return err(400, exc.key, b, **exc.kwargs)
        except json.JSONDecodeError:
            return err(400, "adm_err_label", b)
        img = None
        if photo is not None and photo.filename:
            data = await photo.read(16 * 1024 * 1024)
            try:
                img = await run_in_threadpool(load_image, data)
            except InvalidImage:
                return err(415, "error_not_image", b)

        def work() -> dict[str, Any]:
            template = load_template(cfg["template"])
            profile = load_profile(cfg["printer"]["profile"])
            g = template.guest_field
            sample_name = strings(b).get("adm_sample_guest", "Convidado")
            ctx = b.context(sample_name if cfg["guest_name"] else "", placeholder_logo=True,
                            cfg=cfg, template=template)
            label_mm = (cfg["label"]["width_mm"], cfg["label"]["height_mm"])
            src = img if img is not None else placeholder_photo((1200, 1500))
            res = render_label(template, src, ctx, label_mm, profile, cfg["paper"], bool(cfg.get("face_detect")))
            colors = template.preprinted.get("preview_colors") or [None]
            return {
                "images": [_png_data_url(paper_preview(res.image, template, c)) for c in colors],
                "warnings": res.warnings,
                "size_px": list(res.size_px),
                "guest_field": g.enabled,
                "config": {k: cfg.get(k) for k in EDITABLE},
            }

        return await run_in_threadpool(work)

    @router.put("/admin/api/config")
    async def save(request: Request, b: "Booth" = Depends(require_admin)):
        try:
            cfg = merge_settings(b.cfg, await request.json())
        except SettingsError as exc:
            return err(400, exc.key, b, **exc.kwargs)
        await run_in_threadpool(b.apply_config, cfg)
        return state_payload(b)

    @router.post("/admin/api/logo")
    async def upload_logo(logo: UploadFile = File(...), b: "Booth" = Depends(require_admin)):
        data = await logo.read(MAX_LOGO_MB * 1024 * 1024 + 1)
        if len(data) > MAX_LOGO_MB * 1024 * 1024:
            return err(413, "error_too_big", b, mb=MAX_LOGO_MB)
        try:
            img = await run_in_threadpool(load_image, data)
        except InvalidImage:
            return err(415, "error_not_image", b)

        def store() -> None:
            # fundo transparente vira branco; guarda em tons de cinza
            rgba = img.convert("RGBA")
            flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            flat.alpha_composite(rgba)
            gray = ImageOps.autocontrast(flat.convert("L"))
            gray.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            b.logo_path.parent.mkdir(parents=True, exist_ok=True)
            gray.save(b.logo_path)
            b._sample = None

        await run_in_threadpool(store)
        return {"ok": True}

    @router.delete("/admin/api/logo")
    async def delete_logo(b: "Booth" = Depends(require_admin)):
        b.logo_path.unlink(missing_ok=True)
        b._sample = None
        return {"ok": True}

    # ------------------------------------------------------------ fila e fotos

    @router.post("/admin/api/queue/pause")
    async def pause(b: "Booth" = Depends(require_admin)):
        b.queue.pause("manual")
        return state_payload(b)["queue"]

    @router.post("/admin/api/queue/resume")
    async def resume(b: "Booth" = Depends(require_admin)):
        b.queue.resume()
        return state_payload(b)["queue"]

    @router.get("/admin/api/jobs")
    async def jobs(b: "Booth" = Depends(require_admin)):
        q = b.queue
        items = []
        for j in q.list_jobs(limit=500, statuses=("queued", "printing", "done", "error")):
            items.append({
                "id": j.id, "status": j.status, "guest_name": j.guest_name or "",
                "created_at": j.created_at, "queued_at": j.queued_at, "error": j.error_code,
                "position": q.position(j.id), "attempts": j.attempts,
                "image": f"/admin/api/jobs/{j.id}.png",
            })
        return {"jobs": items, "queue": state_payload(b)["queue"]}

    @router.get("/admin/api/jobs/{job_id}.png")
    async def job_image(job_id: str, b: "Booth" = Depends(require_admin)):
        job = b.queue.get(job_id)
        path = Path(job.output_path or job.label_path) if job else None
        if not path or not path.is_file():
            raise HTTPException(404)
        if not b.template.preprinted:
            return FileResponse(path, media_type="image/png")

        def simulate() -> bytes:  # mesma cor de papel da prévia; o arquivo impresso não muda
            with Image.open(path) as im:
                buf = io.BytesIO()
                paper_preview(im, b.template).save(buf, "PNG")
                return buf.getvalue()

        return Response(await run_in_threadpool(simulate), media_type="image/png")

    @router.post("/admin/api/jobs/{job_id}/reprint")
    async def reprint(job_id: str, b: "Booth" = Depends(require_admin)):
        if b.queue.get(job_id) is None:
            raise HTTPException(404)
        b.queue.submit(job_id)
        return b.queue.status_payload(job_id)

    @router.delete("/admin/api/jobs/{job_id}")
    async def delete_job(job_id: str, b: "Booth" = Depends(require_admin)):
        job = b.queue.get(job_id)
        if job is None:
            raise HTTPException(404)
        if job.status == PRINTING:
            return err(409, "adm_err_printing", b)
        b.queue.delete(job_id)
        return {"ok": True}

    @router.post("/admin/api/jobs/delete-all")
    async def delete_all(b: "Booth" = Depends(require_admin)):
        n = 0
        for job in b.queue.list_jobs(limit=100_000):
            if job.status == PRINTING:
                continue
            b.queue.delete(job.id)
            n += 1
        # sobras soltas (ex.: etiquetas de prévia de antes de um reinício)
        for folder in (b.labels_dir, b.originals_dir):
            for f in folder.glob("*"):
                if f.is_file():
                    f.unlink(missing_ok=True)
        b._sample = None
        return {"deleted": n}

    @router.get("/admin/api/photos.zip")
    async def photos_zip(b: "Booth" = Depends(require_admin)):
        def build() -> Path:
            tmp = tempfile.NamedTemporaryFile(prefix="niimparty-", suffix=".zip", delete=False)
            tmp.close()
            with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as z:  # PNG/JPEG já são comprimidos
                for job in b.queue.list_jobs(limit=100_000, statuses=("done", "queued", "printing", "error")):
                    stamp = dt.datetime.fromtimestamp(job.created_at).strftime("%Y%m%d-%H%M%S")
                    who = "".join(ch for ch in (job.guest_name or "") if ch.isalnum() or ch in " -_").strip()
                    base = f"{stamp}_{job.id}" + (f"_{who}" if who else "")
                    if job.original_path and Path(job.original_path).is_file():
                        z.write(job.original_path, f"fotos/{base}.jpg")
                    label = job.output_path or job.label_path
                    if label and Path(label).is_file():
                        z.write(label, f"etiquetas/{base}.png")
            return Path(tmp.name)

        path = await run_in_threadpool(build)
        name = "niimparty-" + (C.slug(b.cfg["event"].get("name", "")) or "fotos") + ".zip"
        return FileResponse(path, media_type="application/zip", filename=name,
                            background=BackgroundTask(lambda: path.unlink(missing_ok=True)))

    return router


__all__ = ["admin_router", "merge_settings", "SettingsError", "ACTIVE"]
