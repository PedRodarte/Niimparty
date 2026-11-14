"""Pipeline da foto (Pillow + NumPy), igual para todos os modelos.

1. Corrige a rotação pela EXIF.
2. Converte HEIC/WebP/PNG com transparência para RGB.
3. Recorta para a proporção do modelo (centralizado; rosto, se o OpenCV existir).
4. Redimensiona para a resolução final com LANCZOS.
5. Escala de cinza, contraste local (CLAHE), gama e unsharp mask.
6. Saída: 8 bits (papel fotográfico) ou pontilhado 1 bit (etiqueta comum).
"""

from __future__ import annotations

import io
import logging
import warnings
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps

log = logging.getLogger("niimparty.imaging")

try:  # HEIC/HEIF (fotos de iPhone)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    log.warning("pillow-heif não instalado: fotos HEIC não serão aceitas")

Image.MAX_IMAGE_PIXELS = 80_000_000

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC", "AVIF", "MPO", "GIF", "BMP", "TIFF"}


class InvalidImage(ValueError):
    """O arquivo enviado não é uma imagem que conseguimos ler."""


# ---------------------------------------------------------------- leitura


def load_image(data: bytes) -> Image.Image:
    """Valida pelo conteúdo (não pela extensão) e devolve RGB já rotacionada."""
    if not data:
        raise InvalidImage("arquivo vazio")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            fmt = (probe.format or "").upper()
            probe.verify()
            img = Image.open(io.BytesIO(data))
            img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidImage("imagem grande demais") from exc
    except Exception as exc:  # Pillow levanta vários tipos
        raise InvalidImage("não é uma imagem válida") from exc
    if fmt not in ALLOWED_FORMATS:
        raise InvalidImage(f"formato não suportado: {fmt or 'desconhecido'}")
    img = ImageOps.exif_transpose(img)
    return to_rgb(img)


def to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


# ---------------------------------------------------------------- recorte


def parse_aspect(aspect: str | float | None) -> float | None:
    """'4:5' -> 0.8 (largura/altura). 'full' ou None -> None (ocupa o espaço todo)."""
    if aspect is None:
        return None
    if isinstance(aspect, (int, float)):
        return float(aspect)
    text = str(aspect).strip().lower()
    if text in ("full", "", "auto"):
        return None
    if ":" in text:
        a, b = text.split(":", 1)
        return float(a) / float(b)
    return float(text)


def detect_face_center(img: Image.Image) -> tuple[float, float] | None:
    """Centro (0..1) do maior rosto, se o OpenCV estiver instalado."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    try:
        small = img.copy()
        small.thumbnail((640, 640))
        gray = np.asarray(small.convert("L"))
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return ((x + w / 2) / small.width, (y + h / 2) / small.height)
    except Exception:  # pragma: no cover - nunca derrubar a pipeline por isso
        log.exception("detecção de rosto falhou")
        return None


def crop_to_aspect(img: Image.Image, aspect: float, focus: tuple[float, float] | None = None) -> Image.Image:
    """Recorta o maior retângulo com a proporção pedida, centrado em `focus`."""
    w, h = img.size
    fx, fy = focus or (0.5, 0.5)
    if w / h > aspect:  # mais larga: corta laterais
        new_w, new_h = round(h * aspect), h
    else:  # mais alta: corta em cima/embaixo
        new_w, new_h = w, round(w / aspect)
    left = min(max(round(fx * w - new_w / 2), 0), w - new_w)
    top = min(max(round(fy * h - new_h / 2), 0), h - new_h)
    return img.crop((left, top, left + new_w, top + new_h))


# ---------------------------------------------------------------- tons


def clahe(gray: np.ndarray, clip_limit: float = 2.0, tiles: int = 8) -> np.ndarray:
    """Equalização adaptativa de histograma com limite de contraste (CLAHE),
    com interpolação bilinear entre blocos. Entrada e saída uint8."""
    if clip_limit <= 0:
        return gray
    h, w = gray.shape
    ty = max(1, min(tiles, h // 8))
    tx = max(1, min(tiles, w // 8))
    th = -(-h // ty)
    tw = -(-w // tx)
    padded = np.pad(gray, ((0, th * ty - h), (0, tw * tx - w)), mode="reflect")
    blocks = padded.reshape(ty, th, tx, tw).transpose(0, 2, 1, 3).reshape(ty, tx, th * tw)

    maps = np.empty((ty, tx, 256), dtype=np.float32)
    limit = max(1.0, clip_limit * th * tw / 256.0)
    for i in range(ty):
        for j in range(tx):
            hist = np.bincount(blocks[i, j], minlength=256).astype(np.float32)
            excess = np.maximum(hist - limit, 0).sum()
            hist = np.minimum(hist, limit) + excess / 256.0
            cdf = np.cumsum(hist)
            maps[i, j] = (cdf - cdf[0]) / max(cdf[-1] - cdf[0], 1.0) * 255.0

    fy = np.clip((np.arange(h) + 0.5) / th - 0.5, 0, ty - 1)
    fx = np.clip((np.arange(w) + 0.5) / tw - 0.5, 0, tx - 1)
    y0 = np.floor(fy).astype(int)
    x0 = np.floor(fx).astype(int)
    y1 = np.minimum(y0 + 1, ty - 1)
    x1 = np.minimum(x0 + 1, tx - 1)
    wy = (fy - y0)[:, None].astype(np.float32)
    wx = (fx - x0)[None, :].astype(np.float32)

    Y0, Y1 = y0[:, None], y1[:, None]
    X0, X1 = x0[None, :], x1[None, :]
    top = maps[Y0, X0, gray] * (1 - wx) + maps[Y0, X1, gray] * wx
    bottom = maps[Y1, X0, gray] * (1 - wx) + maps[Y1, X1, gray] * wx
    out = top * (1 - wy) + bottom * wy
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def apply_gamma(gray: np.ndarray, gamma: float) -> np.ndarray:
    if gamma == 1.0:
        return gray
    lut = (np.power(np.arange(256) / 255.0, gamma) * 255.0 + 0.5).astype(np.uint8)
    return lut[gray]


def tone(img: Image.Image, settings: dict[str, Any]) -> Image.Image:
    """Cinza + CLAHE + gama + unsharp mask."""
    gray = np.asarray(img.convert("L"))
    gray = clahe(gray, float(settings.get("clahe_clip", 2.0)))
    gray = apply_gamma(gray, float(settings.get("gamma", 0.8)))
    out = Image.fromarray(gray, mode="L")
    percent = int(settings.get("sharpen_percent", 70))
    if percent > 0:
        out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=percent, threshold=2))
    return out


# ---------------------------------------------------------------- pontilhado


def dither_atkinson(img: Image.Image) -> Image.Image:
    """Pontilhado de Atkinson (espalha 6/8 do erro; preserva brancos e
    contraste, bom para impressão térmica). Devolve modo L com 0/255."""
    w, h = img.size
    src = np.asarray(img.convert("L"), dtype=np.float32)
    out = bytearray(w * h)
    rows = [src[y].tolist() for y in range(min(3, h))]
    for y in range(h):
        cur = rows[0]
        nxt = rows[1] if len(rows) > 1 else None
        nn = rows[2] if len(rows) > 2 else None
        base = y * w
        for x in range(w):
            old = cur[x]
            if old >= 128:
                out[base + x] = 255
                err = (old - 255.0) / 8.0
            else:
                err = old / 8.0
            if err:
                if x + 1 < w:
                    cur[x + 1] += err
                    if x + 2 < w:
                        cur[x + 2] += err
                if nxt is not None:
                    if x > 0:
                        nxt[x - 1] += err
                    nxt[x] += err
                    if x + 1 < w:
                        nxt[x + 1] += err
                if nn is not None:
                    nn[x] += err
        rows.pop(0)
        if y + 3 < h:
            rows.append(src[y + 3].tolist())
    return Image.frombytes("L", (w, h), bytes(out))


def dither(img: Image.Image, method: str = "atkinson") -> Image.Image:
    if method == "atkinson":
        return dither_atkinson(img)
    if method in ("floyd-steinberg", "floyd_steinberg", "fs"):
        return img.convert("L").convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    if method == "threshold":
        return img.convert("L").point(lambda v: 255 if v >= 128 else 0)
    raise ValueError(f"método de pontilhado desconhecido: {method}")


# ---------------------------------------------------------------- pipeline


def process_photo(
    img: Image.Image,
    size_px: tuple[int, int],
    settings: dict[str, Any],
    face_detect: bool = False,
) -> Image.Image:
    """Recorta, redimensiona e trata a foto para a caixa `size_px` (L, 8 bits
    ou já pontilhada em 0/255, conforme `settings['output']`)."""
    w, h = size_px
    focus = detect_face_center(img) if face_detect else None
    img = crop_to_aspect(img, w / h, focus)
    img = img.resize((w, h), Image.Resampling.LANCZOS, reducing_gap=3.0)
    img = tone(img, settings)
    if settings.get("output") == "dither":
        img = dither(img, settings.get("dither", "atkinson"))
    return img


def finalize_label(label: Image.Image, output: str) -> Image.Image:
    """Converte a etiqueta montada para o formato de saída da impressora."""
    gray = label.convert("L")
    if output == "gray16":
        # modo cinza das Niimbot com papel fotográfico: 16 níveis por ponto (4 bits),
        # o calor de cada ponto define o tom. Sem retícula.
        return gray.point(lambda v: round(v / 17) * 17)
    if output == "dither":
        # a foto já veio pontilhada; texto e ornamentos são limiarizados
        return gray.point(lambda v: 255 if v >= 128 else 0).convert("1", dither=Image.Dither.NONE)
    return gray
