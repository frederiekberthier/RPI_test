import pytest


@pytest.fixture(autouse=True)
def no_real_waiting(monkeypatch):
    """De checks wachten in de praktijk seconden (pollen, scans); in tests niet."""
    monkeypatch.setattr("rpitest.checks.wifi.time.sleep", lambda s: None)
    monkeypatch.setattr("rpitest.checks.power.time.sleep", lambda s: None)
