import time

import pytest


class _FastTime:
    """Dezelfde `time`-module, maar `sleep` doet niets. Alleen aan de modules gekoppeld die in de praktijk
    seconden wachten (pollen, scans); een globale `time.sleep`-patch zou ook tests verstoren die zelf tijd meten."""

    def __getattr__(self, name):
        return getattr(time, name)

    @staticmethod
    def sleep(seconds):
        pass


@pytest.fixture(autouse=True)
def no_real_waiting(monkeypatch):
    for module in ("rpitest.checks.wifi", "rpitest.checks.power"):
        monkeypatch.setattr(f"{module}.time", _FastTime())
