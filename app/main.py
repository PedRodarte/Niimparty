"""Servidor FastAPI do Niimparty.

Rotas do convidado:
  GET  /                 página (web/index.html)
  GET  /api/info         textos do idioma, evento e campos do modelo
  GET  /api/sample.png   etiqueta de exemplo do modelo atual
  POST /upload           envia a foto -> devolve id e prévia
  GET  /preview/{id}.png prévia da etiqueta
  POST /print/{id}       coloca na fila
  GET  /status/{id}      eventos (SSE) com a posição na fila
  GET  /api/job/{id}     o mesmo status em JSON (para quando o SSE falha)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from starlette.concurrency import run_in_threadpool

from . import config as C
from .i18n import load_locale
from .imaging import InvalidImage, load_image
from .printers import Printer, load_profile, make_printer
from .queue import DONE, ERROR, PrintQueue
from .renderer import RenderContext, clean_guest_name, paper_preview, render_label
from .templates import Template, load_template

log = logging.getLogger("niimparty")

TERMINAL = (DONE, ERROR, "cancelled")


class Booth:
    """Estado do evento: configuração, modelo, perfil, impressora e fila."""

    def __init__(self, cfg: dict[str, Any], *, printer: Printer | None = None,
                 uploads_dir: Path = C.UPLOADS_DIR, output_dir: Path = C.OUTPUT_DIR,
                 data_dir: Path = C.DATA_DIR):
        self.cfg = cfg
        self.uploads_dir = uploads_dir
        self.labels_dir = uploads_dir / "labels"
        self.originals_dir = uploads_dir / "originals"
        for d in (self.labels_dir, self.originals_dir, output_dir, data_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.profile = load_profile(cfg["printer"]["profile"])
        self.template: Template = load_template(cfg["template"])
        self.printer = printer or make_printer(cfg["printer"]["driver"], self.profile, cfg["printer"])
        self.queue = PrintQueue(data_dir / "niimparty.db", output_dir, self.printer, cfg.get("copies", 1))
        self._sample: bytes | None = None

    @property
    def lang(self) -> str:
        return self.cfg.get("language", "pt-BR")

    @property
    def label_mm(self) -> tuple[float, float]:
        return float(self.cfg["label"]["width_mm"]), float(self.cfg["label"]["height_mm"])

    @property
    def guest_enabled(self) -> bool:
        return bool(self.cfg.get("guest_name")) and self.template.guest_field.enabled

    def context(self, guest_name: str = "", placeholder_logo: bool = False) -> RenderContext:
        logo = None
        logo_path = C.DATA_DIR / "logo.png"
        if self.template.logo.get("enabled") and logo_path.is_file():
            logo = Image.open(logo_path)
        return RenderContext(
            event=self.cfg["event"].get("name", ""),
            date=str(self.cfg["event"].get("date", "")),
            guest_name=guest_name,
            texts={k: str(v) for k, v in (self.cfg.get("texts") or {}).items()},
            guest_enabled=self.guest_enabled,
            date_format=load_locale(self.lang).get("date_format", "%d/%m/%Y"),
            logo=logo,
            placeholder_logo=placeholder_logo,
        )

    def render(self, photo: Image.Image | None, guest_name: str = "", placeholder_logo: bool = False):
        return render_label(self.template, photo, self.context(guest_name, placeholder_logo), self.label_mm,
                            self.profile, self.cfg.get("paper", "photo"), bool(self.cfg.get("face_detect")))

    def sample_png(self) -> bytes:
        if self._sample is None:
            sample_name = "Ana" if self.guest_enabled else ""
            result = self.render(None, sample_name, placeholder_logo=False)
            buf = io.BytesIO()
            paper_preview(result.image, self.template).save(buf, "PNG")
            self._sample = buf.getvalue()
        return self._sample


def _error(status: int, key: str, lang: str, **kwargs) -> JSONResponse:
    text = load_locale(lang).get(key, key)
    try:
        text = text.format(**kwargs)
    except (KeyError, IndexError):
        pass
    return JSONResponse({"error": key, "message": text}, status_code=status)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_app(cfg: dict[str, Any] | None = None, *, booth: Booth | None = None) -> FastAPI:
    cfg = cfg or C.load_config()
    state: dict[str, Booth] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        b = booth or Booth(cfg)
        state["booth"] = b
        app.state.booth = b
        await b.queue.start()
        try:
            yield
        finally:
            await b.queue.stop()

    app = FastAPI(title="Niimparty", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(C.WEB_DIR)), name="static")

    def B() -> Booth:
        return state["booth"]

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(C.WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/info")
    async def info():
        b = B()
        strings = load_locale(b.lang)
        g = b.template.guest_field
        return {
            "lang": b.lang,
            "strings": {k: v for k, v in strings.items() if not k.startswith(("wiz_", "run_", "plate_"))},
            "event": {"name": b.cfg["event"].get("name", ""), "date": b.cfg["event"].get("date", "")},
            "template": {"id": b.template.id, "name": b.template.name, "description": b.template.description},
            "guest": {"enabled": b.guest_enabled, "label": g.label or strings.get("your_name"),
                      "max_chars": g.max_chars},
            "max_upload_mb": b.cfg["limits"]["max_upload_mb"],
        }

    @app.get("/api/sample.png")
    async def sample():
        data = await run_in_threadpool(B().sample_png)
        return Response(data, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.post("/upload")
    async def upload(request: Request, photo: UploadFile = File(...), guest_name: str = Form("")):
        b = B()
        max_bytes = int(float(b.cfg["limits"]["max_upload_mb"]) * 1024 * 1024)
        chunks, size = [], 0
        while chunk := await photo.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                return _error(413, "error_too_big", b.lang, mb=b.cfg["limits"]["max_upload_mb"])
            chunks.append(chunk)
        data = b"".join(chunks)
        try:
            img = await run_in_threadpool(load_image, data)
        except InvalidImage:
            return _error(415, "error_not_image", b.lang)

        job_id = uuid.uuid4().hex[:12]
        name = clean_guest_name(guest_name, b.template.guest_field.max_chars) if b.guest_enabled else ""
        result = await run_in_threadpool(b.render, img, name)
        label_path = b.labels_dir / f"{job_id}.png"
        await run_in_threadpool(result.image.save, label_path)
        original_path = None
        if b.cfg.get("keep_originals", True):
            original_path = b.originals_dir / f"{job_id}.jpg"
            await run_in_threadpool(img.save, original_path, "JPEG", quality=92)
        b.queue.create_job(job_id, label_path, original_path, name, client_ip(request))
        return {"id": job_id, "preview": f"/preview/{job_id}.png", "warnings": result.warnings}

    @app.get("/preview/{job_id}.png")
    async def preview(job_id: str):
        job = B().queue.get(job_id)
        if not job or not Path(job.label_path).is_file():
            raise HTTPException(404)
        b = B()
        if not b.template.preprinted:
            return FileResponse(job.label_path, media_type="image/png")

        def simulate() -> bytes:  # moldura colorida só na tela; a impressora recebe o original
            with Image.open(job.label_path) as im:
                buf = io.BytesIO()
                paper_preview(im, b.template).save(buf, "PNG")
                return buf.getvalue()

        return Response(await run_in_threadpool(simulate), media_type="image/png")

    @app.post("/print/{job_id}")
    async def print_job(job_id: str, request: Request):
        b = B()
        job = b.queue.get(job_id)
        if not job:
            return _error(404, "error_expired", b.lang)
        if job.status == "preview":
            limits = b.cfg["limits"]
            n = int(limits["photos_per_device"])
            since = time.time() - float(limits["window_minutes"]) * 60
            if n > 0 and b.queue.submissions_since(client_ip(request), since) >= n:
                return _error(429, "error_rate_limit", b.lang, n=n)
        b.queue.submit(job_id)
        return b.queue.status_payload(job_id)

    @app.get("/api/job/{job_id}")
    async def job_status(job_id: str):
        payload = B().queue.status_payload(job_id)
        if payload is None:
            raise HTTPException(404)
        return payload

    @app.get("/status/{job_id}")
    async def status_stream(job_id: str, request: Request):
        q = B().queue
        if q.get(job_id) is None:
            raise HTTPException(404)

        async def events():
            last, last_sent = None, time.monotonic()
            while True:
                if await request.is_disconnected():
                    break
                payload = q.status_payload(job_id)
                if payload is None:
                    break
                if payload != last:
                    yield f"data: {json.dumps(payload)}\n\n"
                    last, last_sent = payload, time.monotonic()
                    if payload["status"] in TERMINAL:
                        break
                elif time.monotonic() - last_sent > 15:
                    yield ": keep-alive\n\n"
                    last_sent = time.monotonic()
                await asyncio.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
