"""De opdrachtregel van de agent (rpitest.agent): wachten op het testadres en foutafhandeling."""

import errno

import pytest

from rpitest.agent import __main__ as agent_cli


# ---------------------------------------------------------------- issue #22: wachten tot het adres bestaat

def test_the_agent_waits_until_the_test_address_exists():
    attempts, sleeps, messages = [], [], []

    def make(host, port):
        attempts.append((host, port))
        if len(attempts) < 3:
            raise OSError(errno.EADDRNOTAVAIL, "Cannot assign requested address")
        return "server"

    server = agent_cli.bind_when_available(make, "192.168.77.2", 8765, sleep=sleeps.append, log=messages.append)
    assert server == "server" and len(attempts) == 3 and sleeps == [2, 2]
    assert len(messages) == 1 and "192.168.77.2" in messages[0]  # één melding, geen spam bij elke poging


def test_other_bind_errors_are_not_retried():
    def make(host, port):
        raise OSError(errno.EADDRINUSE, "Address already in use")

    with pytest.raises(OSError) as exc:
        agent_cli.bind_when_available(make, "192.168.77.2", 8765, sleep=lambda s: pytest.fail("mag niet wachten"),
                                      log=lambda m: None)
    assert exc.value.errno == errno.EADDRINUSE


def test_main_reports_a_port_that_is_taken_instead_of_a_traceback(monkeypatch, capsys):
    class FakePort:
        chip_path = "/dev/gpiochip0"

        def close(self):
            pass

    monkeypatch.setattr(agent_cli.real, "GpiodPort", lambda chip: FakePort())
    monkeypatch.setattr(agent_cli, "LinuxOps", lambda: type("Ops", (), {"close": lambda self: None})())

    def taken(agent, host, port):
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(agent_cli, "make_server", taken)
    assert agent_cli.main(["--host", "127.0.0.1"]) == 2
    assert "kan niet luisteren" in capsys.readouterr().err
