"""ManualPrinter: entrega a etiqueta pronta numa pasta (STUB).

Para quando o modelo de impressora não é suportado pelas bibliotecas da
comunidade. Alguém abre o PNG pelo app oficial da Niimbot e imprime.

Plano de implementação
----------------------
- Configuração em config.yaml::

      printer:
        driver: manual
        manual_dir: output/manual   # pasta sincronizada com o celular, por exemplo

- `print_label` deve gravar `<manual_dir>/<timestamp>_<job_id>.png` já
  girada com `to_feed_orientation` e marcar o trabalho como concluído.
  Opcionalmente, esperar alguém confirmar no /admin que a etiqueta saiu.
"""

from __future__ import annotations

from PIL import Image

from .base import Printer, PrinterError


class ManualPrinter(Printer):
    name = "manual"

    async def print_label(self, label: Image.Image, job_id: str, copies: int = 1) -> None:
        raise PrinterError("offline", "ManualPrinter ainda não foi implementado. Use driver: mock.")
