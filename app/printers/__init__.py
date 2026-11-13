from .base import Printer, PrinterError, PrinterProfile, list_profiles, load_profile, to_feed_orientation

DRIVERS = ("mock", "niimblue", "manual")


def make_printer(driver: str, profile: PrinterProfile, settings: dict | None = None) -> Printer:
    if driver == "mock":
        from .mock import MockPrinter
        return MockPrinter(profile, settings)
    if driver == "niimblue":
        from .niimblue import NiimBluePrinter
        return NiimBluePrinter(profile, settings)
    if driver == "manual":
        from .manual import ManualPrinter
        return ManualPrinter(profile, settings)
    raise ValueError(f"Driver desconhecido: {driver} (use {', '.join(DRIVERS)})")


__all__ = ["DRIVERS", "Printer", "PrinterError", "PrinterProfile", "list_profiles",
           "load_profile", "make_printer", "to_feed_orientation"]
