"""Interface comum das impressoras.

Todo driver recebe a etiqueta já pronta (PIL.Image no tamanho final, na
resolução do perfil) e cuida só de entregá-la à impressora. Trocar de
simulação para impressão real, ou de um modelo Niimbot para outro, muda
apenas o driver e o perfil.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

PROFILES_DIR = Path(__file__).resolve().parents[2] / "printers" / "profiles"


class PrinterError(Exception):
    """Falha de impressão. `code` vira uma mensagem simples para o convidado
    (ver locales/*.json, chaves "error_<code>")."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code  # no_paper | offline | busy | unknown
        self.detail = detail


@dataclass
class PrinterProfile:
    id: str
    model: str
    dpi: int
    printhead_mm: float
    label_widths_mm: list[float] = field(default_factory=list)
    label_sizes_mm: list[list[float]] = field(default_factory=list)
    density: dict[str, int] = field(default_factory=lambda: {"min": 1, "max": 5, "default": 3})
    grayscale: bool = False
    connection: list[str] = field(default_factory=list)
    status: str = "não testado"
    image: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def px_per_mm(self) -> float:
        return self.dpi / 25.4

    def image_settings(self, paper: str) -> dict[str, Any]:
        """Ajustes da pipeline para o papel. Se o perfil não aceita tons de
        cinza, força pontilhado mesmo em papel fotográfico."""
        defaults = {
            "clahe_clip": 2.0,
            "gamma": 0.8,
            "sharpen_percent": 70,
            "output": "gray16" if paper == "photo" else "dither",
            "dither": "atkinson",
        }
        settings = {**defaults, **self.image.get(paper, self.image.get("regular", {}))}
        if not self.grayscale:
            settings["output"] = "dither"
        return settings


def list_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))


def load_profile(profile_id: str, profiles_dir: Path = PROFILES_DIR) -> PrinterProfile:
    path = profiles_dir / f"{profile_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Perfil de impressora não encontrado: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f for f in PrinterProfile.__dataclass_fields__ if f not in ("id", "extra")}
    kwargs = {k: v for k, v in data.items() if k in known}
    extra = {k: v for k, v in data.items() if k not in known}
    return PrinterProfile(id=profile_id, extra=extra, **kwargs)


def to_feed_orientation(label: Image.Image, profile: PrinterProfile) -> Image.Image:
    """Gira a etiqueta para que a largura caiba na cabeça de impressão.

    O modelo é desenhado na orientação de leitura (retrato ou paisagem).
    A impressora imprime linhas ao longo da cabeça; se a largura da imagem
    passar da cabeça e a altura couber, giramos 90°.
    """
    head_px = round(profile.printhead_mm * profile.px_per_mm)
    w, h = label.size
    if w > head_px and h <= head_px:
        return label.rotate(90, expand=True)
    return label


class Printer(ABC):
    """Contrato de um driver de impressora."""

    name = "base"

    def __init__(self, profile: PrinterProfile, settings: dict[str, Any] | None = None):
        self.profile = profile
        self.settings = settings or {}

    @abstractmethod
    async def print_label(self, label: Image.Image, job_id: str, copies: int = 1) -> None:
        """Imprime a etiqueta. Levanta PrinterError em caso de falha."""

    async def check(self) -> dict[str, Any]:
        """Estado da impressora para o /admin. Drivers reais devem sobrescrever."""
        return {"ok": True, "driver": self.name, "model": self.profile.model}

    async def close(self) -> None:
        """Libera conexões (Bluetooth/USB/HTTP)."""
