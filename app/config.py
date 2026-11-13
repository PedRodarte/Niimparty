"""Configuração (config.yaml + .env) e caminhos do projeto."""

from __future__ import annotations

import copy
import os
import socket
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"
UPLOADS_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "output"
DATA_DIR = ROOT / "data"
LOCALES_DIR = ROOT / "locales"
WEB_DIR = ROOT / "web"

DEFAULTS: dict[str, Any] = {
    "language": "pt-BR",
    "event": {"name": "", "date": ""},
    "template": "basico",
    "texts": {},
    "guest_name": False,
    "printer": {"profile": "b2_pro", "driver": "mock", "density": 3},
    "label": {"width_mm": 50, "height_mm": 80},
    "paper": "photo",
    "copies": 1,
    "server": {"host": "0.0.0.0", "port": 8000, "public_url": ""},
    "limits": {"photos_per_device": 3, "window_minutes": 10, "max_upload_mb": 15},
    "keep_originals": True,
    "face_detect": False,
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return deep_merge(DEFAULTS, data)


def save_config(cfg: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    header = "# Gerado pelo Niimparty. Pode editar à mão ou pelo /admin.\n"
    body = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
    path.write_text(header + body, encoding="utf-8")


def load_env(path: Path = ENV_PATH) -> None:
    load_dotenv(path, override=False)


def admin_pin() -> str:
    load_env()
    return os.environ.get("NIIMPARTY_ADMIN_PIN", "").strip()


def write_env(values: dict[str, str], path: Path = ENV_PATH) -> None:
    """Atualiza chaves do .env preservando as outras linhas."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in values:
            out.append(f"{key}={values[key]}")
            done.add(key)
        else:
            out.append(line)
    for key, value in values.items():
        if key not in done:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    for key, value in values.items():
        os.environ[key] = value


def lan_ip() -> str:
    """IP do computador na rede local (sem enviar nada pela rede)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def public_url(cfg: dict[str, Any]) -> str:
    url = (cfg.get("server") or {}).get("public_url") or ""
    if url:
        return url.rstrip("/")
    port = int(cfg["server"].get("port", 8000))
    return f"http://{lan_ip()}:{port}"
