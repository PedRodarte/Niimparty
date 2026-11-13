"""Fila de impressão: asyncio + SQLite.

- O SQLite guarda cada trabalho (sobrevive a reinícios do servidor).
- Um asyncio.Queue acorda o trabalhador quando algo entra na fila; a ordem
  real vem do banco (`queued_at`), o que permite pausar, reimprimir e
  devolver um trabalho para a frente da fila quando a impressora falha.
- Antes de chamar o driver, a etiqueta final é salva em output/ com data e hora.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .printers import Printer, PrinterError

log = logging.getLogger("niimparty.queue")

PREVIEW, QUEUED, PRINTING, DONE, ERROR, CANCELLED = "preview", "queued", "printing", "done", "error", "cancelled"
ACTIVE = (QUEUED, PRINTING)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    queued_at REAL,
    finished_at REAL,
    status TEXT NOT NULL,
    label_path TEXT NOT NULL,
    original_path TEXT,
    output_path TEXT,
    guest_name TEXT,
    client_ip TEXT,
    copies INTEGER NOT NULL DEFAULT 1,
    error_code TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, queued_at);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class Job:
    id: str
    created_at: float
    queued_at: float | None
    finished_at: float | None
    status: str
    label_path: str
    original_path: str | None
    output_path: str | None
    guest_name: str | None
    client_ip: str | None
    copies: int
    error_code: str | None
    attempts: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class PrintQueue:
    def __init__(self, db_path: Path, output_dir: Path, printer: Printer, copies: int = 1):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = output_dir
        self.printer = printer
        self.copies = max(1, int(copies))
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._wake: asyncio.Queue[str] | None = None
        self._running: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self.pause_reason: str | None = self._get_state("pause_reason")

    # -------------------------------------------------------------- SQL

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, params)

    def _get_state(self, key: str) -> str | None:
        row = self._exec("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_state(self, key: str, value: str | None) -> None:
        if value is None:
            self._exec("DELETE FROM state WHERE key=?", (key,))
        else:
            self._exec("INSERT OR REPLACE INTO state(key, value) VALUES(?, ?)", (key, value))

    # -------------------------------------------------------------- trabalhos

    def create_job(self, job_id: str, label_path: Path, original_path: Path | None = None,
                   guest_name: str = "", client_ip: str = "") -> Job:
        self._exec(
            "INSERT INTO jobs(id, created_at, status, label_path, original_path, guest_name, client_ip, copies)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, time.time(), PREVIEW, str(label_path), str(original_path) if original_path else None,
             guest_name, client_ip, self.copies),
        )
        return self.get(job_id)  # type: ignore[return-value]

    def get(self, job_id: str) -> Job | None:
        row = self._exec("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return Job(**dict(row)) if row else None

    def list_jobs(self, limit: int = 200, statuses: tuple[str, ...] | None = None) -> list[Job]:
        if statuses:
            marks = ",".join("?" * len(statuses))
            rows = self._exec(f"SELECT * FROM jobs WHERE status IN ({marks}) ORDER BY created_at DESC LIMIT ?",
                              (*statuses, limit)).fetchall()
        else:
            rows = self._exec("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [Job(**dict(r)) for r in rows]

    def position(self, job_id: str) -> int | None:
        """1 = é a próxima (ou está imprimindo). None = fora da fila."""
        job = self.get(job_id)
        if not job or job.status not in ACTIVE or job.queued_at is None:
            return None
        row = self._exec(
            "SELECT COUNT(*) AS n FROM jobs WHERE status IN (?, ?) AND (queued_at < ? OR (queued_at = ? AND id <= ?))",
            (QUEUED, PRINTING, job.queued_at, job.queued_at, job.id),
        ).fetchone()
        return int(row["n"])

    def queue_length(self) -> int:
        return int(self._exec("SELECT COUNT(*) AS n FROM jobs WHERE status IN (?, ?)", ACTIVE).fetchone()["n"])

    def submissions_since(self, client_ip: str, since: float) -> int:
        row = self._exec(
            "SELECT COUNT(*) AS n FROM jobs WHERE client_ip=? AND queued_at IS NOT NULL AND queued_at >= ?",
            (client_ip, since),
        ).fetchone()
        return int(row["n"])

    def submit(self, job_id: str) -> int:
        """Coloca um trabalho em prévia (ou já impresso, para reimprimir) na fila."""
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in ACTIVE:
            return self.position(job_id) or 1
        self._exec("UPDATE jobs SET status=?, queued_at=?, error_code=NULL, finished_at=NULL WHERE id=?",
                   (QUEUED, time.time(), job_id))
        self._notify(job_id)
        return self.position(job_id) or 1

    def cancel(self, job_id: str) -> None:
        self._exec("UPDATE jobs SET status=? WHERE id=? AND status IN (?, ?)", (CANCELLED, job_id, PREVIEW, QUEUED))

    def delete(self, job_id: str) -> None:
        job = self.get(job_id)
        if not job:
            return
        for p in (job.label_path, job.original_path, job.output_path):
            if p:
                Path(p).unlink(missing_ok=True)
        self._exec("DELETE FROM jobs WHERE id=?", (job_id,))

    # -------------------------------------------------------------- pausa

    @property
    def paused(self) -> bool:
        return self.pause_reason is not None

    def pause(self, reason: str = "manual") -> None:
        self.pause_reason = reason
        self._set_state("pause_reason", reason)
        if self._running:
            self._running.clear()

    def resume(self) -> None:
        self.pause_reason = None
        self._set_state("pause_reason", None)
        if self._running:
            self._running.set()
        self._notify("resume")

    # -------------------------------------------------------------- trabalhador

    def _notify(self, token: str) -> None:
        if self._wake is not None:
            self._wake.put_nowait(token)

    def _next_job(self) -> Job | None:
        row = self._exec("SELECT * FROM jobs WHERE status=? ORDER BY queued_at, id LIMIT 1", (QUEUED,)).fetchone()
        return Job(**dict(row)) if row else None

    async def start(self) -> None:
        self._wake = asyncio.Queue()
        self._running = asyncio.Event()
        if not self.paused:
            self._running.set()
        # trabalhos interrompidos por um reinício voltam para a fila
        self._exec("UPDATE jobs SET status=? WHERE status=?", (QUEUED, PRINTING))
        self._task = asyncio.create_task(self._worker(), name="niimparty-print-worker")
        self._notify("start")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.printer.close()

    def close(self) -> None:
        self._db.close()

    async def _worker(self) -> None:
        assert self._wake is not None and self._running is not None
        while True:
            await self._running.wait()
            job = self._next_job()
            if job is None:
                await self._wake.get()
                continue
            await self._print(job)

    async def _print(self, job: Job) -> None:
        self._exec("UPDATE jobs SET status=?, attempts=attempts+1 WHERE id=?", (PRINTING, job.id))
        try:
            label = await asyncio.to_thread(Image.open, job.label_path)
            label.load()
            out = job.output_path
            if not out:
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                out = str(self.output_dir / f"{stamp}_{job.id}.png")
                await asyncio.to_thread(label.save, out)
                self._exec("UPDATE jobs SET output_path=? WHERE id=?", (out, job.id))
            await self.printer.print_label(label, job.id, job.copies)
        except PrinterError as exc:
            log.warning("impressora falhou no trabalho %s: %s", job.id, exc)
            # o trabalho continua na frente da fila; a fila pausa até o organizador resolver
            self._exec("UPDATE jobs SET status=?, error_code=? WHERE id=?", (QUEUED, exc.code, job.id))
            self.pause(exc.code)
            return
        except asyncio.CancelledError:
            self._exec("UPDATE jobs SET status=? WHERE id=?", (QUEUED, job.id))
            raise
        except Exception:
            log.exception("erro inesperado no trabalho %s", job.id)
            self._exec("UPDATE jobs SET status=?, error_code=?, finished_at=? WHERE id=?",
                       (ERROR, "unknown", time.time(), job.id))
            return
        self._exec("UPDATE jobs SET status=?, error_code=NULL, finished_at=? WHERE id=?", (DONE, time.time(), job.id))
        log.info("trabalho %s concluído -> %s", job.id, out)

    # -------------------------------------------------------------- status

    def status_payload(self, job_id: str) -> dict[str, Any] | None:
        job = self.get(job_id)
        if not job:
            return None
        return {
            "id": job.id,
            "status": job.status,
            "position": self.position(job_id),
            "error": job.error_code,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
        }
