"""NiimBluePrinter: impressão automática via niimblue-node (STUB).

Ainda não implementado: depende do teste de viabilidade da fase 3.

Plano de implementação
----------------------
- O niimblue-node (CLI da biblioteca comunitária niimbluelib) expõe um
  servidor REST local que conversa com a impressora por Bluetooth ou USB.
  Referência: https://printers.niim.blue/other/third-party-software/
- Configuração esperada em config.yaml::

      printer:
        driver: niimblue
        niimblue_url: http://127.0.0.1:5000
        transport: usb          # usb | bluetooth
        address: COM5           # porta serial ou endereço Bluetooth

- `print_label` deve:
  1. girar a etiqueta com `to_feed_orientation` para caber na cabeça;
  2. converter para PNG (1 bit ou 8 bits, conforme o perfil e o papel);
  3. enviar ao endpoint de impressão com densidade, quantidade de cópias,
     modelo (`niimblue_model` do perfil) e tipo de etiqueta;
  4. traduzir erros do niimblue em `PrinterError` com os códigos
     `no_paper`, `offline`, `busy` ou `unknown`.
- `check` deve consultar o status (conectada, papel, bateria).
"""

from __future__ import annotations

from PIL import Image

from .base import Printer, PrinterError


class NiimBluePrinter(Printer):
    name = "niimblue"

    async def print_label(self, label: Image.Image, job_id: str, copies: int = 1) -> None:
        raise PrinterError(
            "offline",
            "NiimBluePrinter ainda não foi implementado (fase 3). Use driver: mock ou manual.",
        )

    async def check(self):
        return {"ok": False, "driver": self.name, "model": self.profile.model,
                "detail": "driver ainda não implementado"}
