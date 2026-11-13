"""Leitura e validação dos modelos de etiqueta (templates/<nome>/template.yaml).

Um modelo é só uma pasta com YAML e imagens; nada de Python. Este módulo
lê o YAML, aplica os valores padrão e aponta erros em linguagem simples.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates"

ORIENTATIONS = ("portrait", "landscape")
ASPECTS_HINT = '"1:1", "4:5", "3:2", "3:4", "2:3" ou "full"'
ALIGNS = ("left", "center", "right")
TEXT_POSITIONS = ("top", "bottom")
CORNER_POSITIONS = (
    "top-left", "top-right", "bottom-left", "bottom-right",
    "top", "bottom", "left", "right",
    "photo-top-left", "photo-top-right", "photo-bottom-left", "photo-bottom-right",
)
FRAME_STYLES = ("solid", "dashed", "double", "dotted")

DEFAULT_FONT = "InterDisplay-Bold"


class TemplateError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class TextSpec:
    id: str
    default: str = ""
    label: str = ""
    font: str = DEFAULT_FONT
    size_mm: float = 3.5
    align: str = "center"
    position: str = "bottom"
    max_chars: int = 40
    uppercase: bool = False
    letter_spacing_mm: float = 0.0


@dataclass
class GuestField:
    enabled: bool = False
    label: str = ""
    format: str = "{nome}"
    max_chars: int = 24
    font: str = "InterDisplay-SemiBold"
    size_mm: float = 3.0
    align: str = "center"
    position: str = "bottom"


@dataclass
class Ornament:
    file: str
    position: str = "bottom-right"
    size_mm: float = 8.0
    offset_mm: tuple[float, float] = (0.0, 0.0)
    layer: str = "over"  # over | under


@dataclass
class Template:
    id: str
    dir: Path
    name: str
    description: str = ""
    orientation: str = "portrait"
    photo: dict[str, Any] = field(default_factory=dict)
    texts: list[TextSpec] = field(default_factory=list)
    guest_field: GuestField = field(default_factory=GuestField)
    ornaments: list[Ornament] = field(default_factory=list)
    frame: dict[str, Any] = field(default_factory=dict)
    logo: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def fonts_dir(self) -> Path:
        return self.dir / "fonts"

    @property
    def preview_path(self) -> Path:
        return self.dir / "preview.png"

    @property
    def text_ids(self) -> list[str]:
        return [t.id for t in self.texts]


def list_templates(templates_dir: Path = TEMPLATES_DIR) -> list[str]:
    return sorted(p.name for p in templates_dir.iterdir() if (p / "template.yaml").is_file())


def _num(value: Any, name: str, errors: list[str], minimum: float = 0.0) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        errors.append(f"'{name}' precisa ser um número (recebido: {value!r})")
        return minimum
    if num < minimum:
        errors.append(f"'{name}' não pode ser menor que {minimum} (recebido: {num})")
    return num


def parse_template(data: dict[str, Any], template_id: str, directory: Path) -> tuple[Template, list[str]]:
    """Converte o YAML em Template. Devolve (template, erros)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        raise TemplateError(["o template.yaml está vazio ou não é um mapa de chaves"])

    name = str(data.get("name") or template_id)
    orientation = str(data.get("orientation", "portrait"))
    if orientation not in ORIENTATIONS:
        errors.append(f"orientation deve ser portrait ou landscape (recebido: {orientation})")

    photo = {"aspect": "4:5", "margin_mm": 2.0, "border_mm": 0.0, "corner_radius_mm": 0.0,
             "max_share": 0.68, **(data.get("photo") or {})}
    for key in ("margin_mm", "border_mm", "corner_radius_mm"):
        photo[key] = _num(photo[key], f"photo.{key}", errors)
    from .imaging import parse_aspect  # import tardio: evita ciclo

    try:
        parse_aspect(photo["aspect"])
    except (ValueError, ZeroDivisionError):
        errors.append(f"photo.aspect inválido: {photo['aspect']!r}; use {ASPECTS_HINT}")

    texts: list[TextSpec] = []
    seen: set[str] = set()
    for i, raw in enumerate(data.get("texts") or []):
        if not isinstance(raw, dict) or "id" not in raw:
            errors.append(f"texts[{i}] precisa ter um 'id'")
            continue
        tid = str(raw["id"])
        if tid in seen:
            errors.append(f"id de texto repetido: {tid}")
        seen.add(tid)
        spec = TextSpec(
            id=tid,
            default=str(raw.get("default", "")),
            label=str(raw.get("label", tid)),
            font=str(raw.get("font", DEFAULT_FONT)),
            size_mm=_num(raw.get("size_mm", 3.5), f"texts.{tid}.size_mm", errors, 0.5),
            align=str(raw.get("align", "center")),
            position=str(raw.get("position", "bottom")),
            max_chars=int(raw.get("max_chars", 40)),
            uppercase=bool(raw.get("uppercase", False)),
            letter_spacing_mm=_num(raw.get("letter_spacing_mm", 0), f"texts.{tid}.letter_spacing_mm", errors),
        )
        if spec.align not in ALIGNS:
            errors.append(f"texts.{tid}.align deve ser left, center ou right")
        if spec.position not in TEXT_POSITIONS:
            errors.append(f"texts.{tid}.position deve ser top ou bottom")
        texts.append(spec)

    graw = data.get("guest_field") or {}
    guest = GuestField(
        enabled=bool(graw.get("enabled", False)),
        label=str(graw.get("label", "")),
        format=str(graw.get("format", "{nome}")),
        max_chars=int(graw.get("max_chars", 24)),
        font=str(graw.get("font", "InterDisplay-SemiBold")),
        size_mm=_num(graw.get("size_mm", 3.0), "guest_field.size_mm", errors, 0.5),
        align=str(graw.get("align", "center")),
        position=str(graw.get("position", "bottom")),
    )
    if guest.enabled and "{nome}" not in guest.format:
        errors.append("guest_field.format precisa conter {nome}")

    ornaments: list[Ornament] = []
    for i, raw in enumerate(data.get("ornaments") or []):
        if not isinstance(raw, dict) or "file" not in raw:
            errors.append(f"ornaments[{i}] precisa ter 'file'")
            continue
        pos = str(raw.get("position", "bottom-right"))
        if pos not in CORNER_POSITIONS:
            errors.append(f"ornaments[{i}].position inválida: {pos} (use {', '.join(CORNER_POSITIONS)})")
        off = raw.get("offset_mm", [0, 0])
        if isinstance(off, (int, float)):
            off = [off, off]
        orn = Ornament(
            file=str(raw["file"]),
            position=pos,
            size_mm=_num(raw.get("size_mm", 8), f"ornaments[{i}].size_mm", errors, 1),
            offset_mm=(float(off[0]), float(off[1])),
            layer=str(raw.get("layer", "over")),
        )
        path = directory / orn.file
        if not path.is_file():
            errors.append(f"ornamento não encontrado: {orn.file}")
        elif path.suffix.lower() not in (".png", ".svg"):
            errors.append(f"ornamento deve ser PNG ou SVG: {orn.file}")
        ornaments.append(orn)

    frame = {"border_mm": 0.0, "inset_mm": 1.0, "corner_radius_mm": 0.0, "style": "solid",
             **(data.get("frame") or {})}
    for key in ("border_mm", "inset_mm", "corner_radius_mm"):
        frame[key] = _num(frame[key], f"frame.{key}", errors)
    if frame["style"] not in FRAME_STYLES:
        errors.append(f"frame.style deve ser um de: {', '.join(FRAME_STYLES)}")

    logo = {"enabled": False, "position": "bottom", "height_mm": 8.0, "file": "", **(data.get("logo") or {})}
    logo["height_mm"] = _num(logo["height_mm"], "logo.height_mm", errors, 1)
    if logo["position"] not in ("top", "bottom"):
        errors.append("logo.position deve ser top ou bottom")

    tpl = Template(
        id=template_id, dir=directory, name=name, description=str(data.get("description", "")),
        orientation=orientation, photo=photo, texts=texts, guest_field=guest,
        ornaments=ornaments, frame=frame, logo=logo, raw=data,
    )
    return tpl, errors


def load_template(template_id: str, templates_dir: Path = TEMPLATES_DIR, strict: bool = True) -> Template:
    directory = templates_dir / template_id
    path = directory / "template.yaml"
    if not path.is_file():
        raise TemplateError([f"modelo não encontrado: {path}"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TemplateError([f"erro de sintaxe no YAML: {exc}"]) from exc
    tpl, errors = parse_template(data, template_id, directory)
    if errors and strict:
        raise TemplateError(errors)
    return tpl
