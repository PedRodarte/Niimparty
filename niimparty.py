"""Comando único do Niimparty (funciona igual no Windows, macOS e Linux).

    python niimparty.py run        # assistente na 1ª vez + servidor
    python niimparty.py setup      # refaz as perguntas
    python niimparty.py preview    # etiquetas de exemplo de todos os modelos
    python niimparty.py validate   # confere os modelos em templates/
    python niimparty.py qr         # placa A5 com os QR codes
    python niimparty.py test       # roda os testes
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):  # acentos no terminal do Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        pass


def cmd_run(args: argparse.Namespace) -> int:
    from app import config as C

    if not C.CONFIG_PATH.exists():
        from app.setup_wizard import run_wizard

        run_wizard()
    cfg = C.load_config()
    import uvicorn

    from app.i18n import t
    from app.main import create_app

    lang = cfg.get("language", "pt-BR")
    url = C.public_url(cfg)
    print()
    print("  " + t(lang, "run_open", url=url))
    print("  " + t(lang, "run_admin", url=url))
    print("  " + t(lang, "run_stop"))
    print()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    uvicorn.run(create_app(cfg), host=cfg["server"]["host"], port=int(cfg["server"]["port"]),
                log_level="warning")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    from app.setup_wizard import run_wizard

    run_wizard()
    return 0


def _tool(name: str, extra: list[str]) -> int:
    return subprocess.call([sys.executable, str(ROOT / "tools" / f"{name}.py"), *extra], cwd=ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="niimparty", description="Cabine de fotos para impressoras Niimbot")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="inicia o servidor (pergunta a configuração na 1ª vez)")
    sub.add_parser("setup", help="refaz as perguntas de configuração")
    for name, help_text in (("preview", "gera etiquetas de exemplo"), ("validate", "valida os modelos"),
                            ("qr", "gera a placa A5 com os QR codes")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("extra", nargs=argparse.REMAINDER)
    p = sub.add_parser("test", help="roda os testes (pytest)")
    p.add_argument("extra", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.command in (None, "run"):
        return cmd_run(args)
    if args.command == "setup":
        return cmd_setup(args)
    if args.command == "preview":
        return _tool("preview", args.extra)
    if args.command == "validate":
        return _tool("validate_template", args.extra)
    if args.command == "qr":
        return _tool("make_qr", args.extra)
    if args.command == "test":
        return subprocess.call([sys.executable, "-m", "pytest", *(args.extra or ["-q"])], cwd=ROOT)
    parser.print_help()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
