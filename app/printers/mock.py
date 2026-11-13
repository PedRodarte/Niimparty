"""MockPrinter: simula a impressão sem impressora.

A fila já salva cada etiqueta em output/ antes de chamar o driver; o mock
apenas espera o tempo de uma impressão real (padrão: 5 s) e, se pedido,
simula falta de papel para testar as mensagens de erro.
"""

from __future__ import annotations

import asyncio
import logging

from PIL import Image

from .base import Printer, PrinterError

log = logging.getLogger("niimparty.printer.mock")


class MockPrinter(Printer):
    name = "mock"

    def __init__(self, profile, settings=None):
        super().__init__(profile, settings)
        self.delay_s = float(self.settings.get("mock_delay_s", 5.0))
        self.fail_with: str | None = self.settings.get("mock_fail_with")
        self.printed: list[str] = []

    async def print_label(self, label: Image.Image, job_id: str, copies: int = 1) -> None:
        if self.fail_with:
            raise PrinterError(self.fail_with, "falha simulada pelo MockPrinter")
        for _ in range(max(1, copies)):
            await asyncio.sleep(self.delay_s)
        self.printed.append(job_id)
        log.info("Etiqueta %s 'impressa' (simulação, %dx%d px)", job_id, *label.size)
