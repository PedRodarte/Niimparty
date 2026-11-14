"""Gera a placa A5 (PDF) para pôr ao lado da impressora.

    python tools/make_qr.py
    python tools/make_qr.py --url http://192.168.0.50:8000 --ssid MinhaRede
    python tools/make_qr.py --no-wifi

A placa traz:
  1. QR code do Wi-Fi (o celular conecta sozinho);
  2. QR code da página da cabine;
  3. o nome do evento e uma etiqueta de exemplo com o modelo escolhido.

O nome e a senha do Wi-Fi vêm do .env (WIFI_SSID, WIFI_PASSWORD, WIFI_SECURITY).
Se faltarem, o script pergunta e grava no .env. O PDF vai para output/,
que nunca vai para o Git (ele contém a senha do Wi-Fi).
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):  # acentos no terminal do Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import qrcode  # noqa: E402
from PIL import Image  # noqa: E402
from reportlab.lib.pagesizes import A5  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen import canvas as pdfcanvas  # noqa: E402

from app import config as C  # noqa: E402
from app.i18n import load_locale  # noqa: E402
from app.printers import load_profile  # noqa: E402
from app.renderer import FONTS_DIR, RenderContext, paper_preview, placeholder_photo, render_label  # noqa: E402
from app.templates import load_template  # noqa: E402


# ------------------------------------------------------------ Wi-Fi


def wifi_escape(value: str) -> str:
    """Escapa \\ ; , : " conforme o formato WIFI: dos QR codes."""
    return re.sub(r'([\\;,:"])', r"\\\1", value)


def wifi_payload(ssid: str, password: str, security: str = "WPA", hidden: bool = False) -> str:
    security = (security or "WPA").upper()
    if not password:
        security = "nopass"
    parts = [f"T:{security}", f"S:{wifi_escape(ssid)}"]
    if password:
        parts.append(f"P:{wifi_escape(password)}")
    if hidden:
        parts.append("H:true")
    return "WIFI:" + ";".join(parts) + ";;"


def current_ssid() -> str:
    """Rede Wi-Fi atual do computador (só o nome; nunca a senha)."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True,
                                 timeout=5, encoding="utf-8", errors="replace").stdout
            m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.MULTILINE)
        elif sys.platform == "darwin":
            out = subprocess.run(["networksetup", "-getairportnetwork", "en0"], capture_output=True, text=True,
                                 timeout=5).stdout
            m = re.search(r"Network:\s*(.+)$", out)
        else:
            out = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"(.+)", out)
        return m.group(1).strip() if m else ""
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------ desenho


def qr_image(data: str) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2, box_size=12)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")


def _reader(img: Image.Image) -> ImageReader:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return ImageReader(buf)


def register_fonts() -> None:
    for name in ("InterDisplay-Bold", "InterDisplay-SemiBold", "InterDisplay-Regular", "InterDisplay-Black"):
        try:
            pdfmetrics.getFont(name)
        except KeyError:
            pdfmetrics.registerFont(TTFont(name, str(FONTS_DIR / f"{name}.ttf")))


def fit_font(c, text: str, font: str, size: float, max_w: float) -> float:
    while size > 6 and c.stringWidth(text, font, size) > max_w:
        size -= 0.5
    return size


def sample_label(cfg: dict) -> Image.Image:
    template = load_template(cfg["template"])
    profile = load_profile(cfg["printer"]["profile"])
    lang = cfg.get("language", "pt-BR")
    ctx = RenderContext(
        event=cfg["event"].get("name", ""),
        date=str(cfg["event"].get("date", "")),
        guest_name="Convidado" if cfg.get("guest_name") else "",
        texts={k: str(v) for k, v in (cfg.get("texts") or {}).items()},
        guest_enabled=bool(cfg.get("guest_name")),
        date_format=load_locale(lang).get("date_format", "%d/%m/%Y"),
        placeholder_logo=False,
    )
    label_mm = (float(cfg["label"]["width_mm"]), float(cfg["label"]["height_mm"]))
    res = render_label(template, placeholder_photo((1200, 1500)), ctx, label_mm, profile, cfg.get("paper", "photo"))
    return paper_preview(res.image, template)


def draw_plate(path: Path, cfg: dict, url: str, wifi: tuple[str, str, str] | None) -> None:
    S = load_locale(cfg.get("language", "pt-BR"))
    register_fonts()
    W, H = A5
    c = pdfcanvas.Canvas(str(path), pagesize=A5)
    c.setTitle(cfg["event"].get("name") or "Niimparty")
    m = 12 * mm

    # cabeçalho
    title = cfg["event"].get("name") or S.get("page_title", "Niimparty")
    size = fit_font(c, title, "InterDisplay-Black", 26, W - 2 * m)
    c.setFont("InterDisplay-Black", size)
    c.drawCentredString(W / 2, H - m - size * 0.8, title)
    c.setFont("InterDisplay-Regular", 11)
    c.drawCentredString(W / 2, H - m - size - 14, S.get("welcome", ""))

    # etiqueta de exemplo
    label = sample_label(cfg)
    top = H - m - size - 26
    qr_block_h = 82 * mm
    avail_h = top - (m + qr_block_h) - 6 * mm
    lw, lh = label.size
    scale = min((W - 2 * m) * 0.6 / lw, avail_h / lh)
    dw, dh = lw * scale, lh * scale
    lx, ly = (W - dw) / 2, top - dh - 2 * mm
    c.setFillGray(0.15)
    c.roundRect(lx + 1.2 * mm, ly - 1.2 * mm, dw, dh, 2 * mm, stroke=0, fill=1)
    c.drawImage(_reader(label), lx, ly, dw, dh)
    c.setStrokeGray(0.6)
    c.setLineWidth(0.5)
    c.rect(lx, ly, dw, dh, stroke=1, fill=0)

    # QR codes
    blocks = []
    if wifi:
        ssid, password, security = wifi
        lines = [f"{S.get('plate_network', 'Rede')}: {ssid}"]
        if password:
            lines.append(f"{S.get('plate_password', 'Senha')}: {password}")
        blocks.append((S.get("plate_step_wifi", "1."), wifi_payload(ssid, password, security), lines))
    step_page = S.get("plate_step_page", "2.")
    if not wifi:
        step_page = re.sub(r"^\s*2\.\s*", "", step_page)
    blocks.append((step_page, url, [url.replace("http://", "").replace("https://", "")]))

    qr_size = 52 * mm
    col_w = (W - 2 * m) / len(blocks)
    base_y = m + 14 * mm
    for i, (heading, data, lines) in enumerate(blocks):
        cx = m + col_w * (i + 0.5)
        c.setFillGray(0)
        c.setFont("InterDisplay-Bold", 13)
        c.drawCentredString(cx, base_y + qr_size + 6 * mm, heading)
        c.drawImage(_reader(qr_image(data)), cx - qr_size / 2, base_y + 2 * mm, qr_size, qr_size)
        for j, line in enumerate(lines):
            fs = fit_font(c, line, "InterDisplay-SemiBold", 10, col_w - 4 * mm)
            c.setFont("InterDisplay-SemiBold", fs)
            c.drawCentredString(cx, base_y - 3 * mm - j * 12, line)

    # rodapé
    c.setFont("InterDisplay-Regular", 9)
    c.setFillGray(0.35)
    c.drawCentredString(W / 2, m - 2 * mm, S.get("plate_scan", "") + " · " + S.get("plate_footer", ""))
    c.showPage()
    c.save()


# ------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", help="endereço da página (padrão: IP deste computador)")
    p.add_argument("--ssid", help="nome da rede Wi-Fi")
    p.add_argument("--password", help="senha do Wi-Fi (melhor deixar no .env)")
    p.add_argument("--security", default=None, help="WPA (padrão), WEP ou nopass")
    p.add_argument("--no-wifi", action="store_true", help="só o QR da página")
    p.add_argument("--out", type=Path, default=C.OUTPUT_DIR / "placa-qr.pdf")
    args = p.parse_args(argv)

    cfg = C.load_config()
    C.load_env()
    S = load_locale(cfg.get("language", "pt-BR"))
    url = args.url or C.public_url(cfg)

    wifi = None
    if not args.no_wifi:
        ssid = args.ssid or os.environ.get("WIFI_SSID", "").strip()
        password = args.password if args.password is not None else os.environ.get("WIFI_PASSWORD", "")
        security = args.security or os.environ.get("WIFI_SECURITY", "WPA") or "WPA"
        if not ssid and sys.stdin.isatty():
            detected = current_ssid()
            hint = f" [{detected}]" if detected else ""
            ssid = input(f"{S['plate_ask_ssid']}{hint}: ").strip() or detected
            if ssid:
                password = input(f"{S['plate_ask_password']}: ").strip()
                C.write_env({"WIFI_SSID": ssid, "WIFI_PASSWORD": password, "WIFI_SECURITY": security})
        if ssid:
            wifi = (ssid, password, security)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    draw_plate(args.out, cfg, url, wifi)
    print(S.get("plate_saved", "{path}").format(path=args.out))
    if url.startswith("http://127.") or "localhost" in url:
        print("Atenção: o endereço é local (127.0.0.1); os celulares não vão abrir. Use --url com o IP da rede.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
