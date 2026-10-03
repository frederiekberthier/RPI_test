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


# ---------------------------------------------------------------- issue #21: begrensde aanvragen

def _agent_server():
    import threading

    from rpitest.agent.core import Agent
    from rpitest.agent.server import make_server
    from rpitest.gpio.mock import CLIENT, MockWiring
    server = make_server(Agent(MockWiring().port(CLIENT), lambda: {"model": "mock"}), "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _post(server, body=b"", headers=None, timeout=15):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=timeout)
    try:
        conn.putrequest("POST", "/rpc")
        for key, value in {"Content-Length": str(len(body)), **(headers or {})}.items():
            conn.putheader(key, value)
        conn.endheaders(body)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_the_agent_still_answers_a_normal_call():
    server = _agent_server()
    try:
        status, body = _post(server, b'{"method": "ping", "params": {}}')
        assert status == 200 and b"pong" in body
    finally:
        server.shutdown()
        server.server_close()


def test_the_agent_refuses_oversized_and_invalid_lengths():
    import time

    from rpitest.agent.server import MAX_BODY
    server = _agent_server()
    try:
        status, body = _post(server, b"x" * (MAX_BODY + 1000))
        assert status == 413 and b"te groot" in body
        started = time.monotonic()  # beweert 4 GB maar stuurt niets: geen eindeloos wachten of alloceren
        status, _ = _post(server, b"", {"Content-Length": "4000000000"})
        assert status == 413 and time.monotonic() - started < 10
        assert _post(server, b"", {"Content-Length": "-5"})[0] == 400
        assert _post(server, b"", {"Content-Length": "abc"})[0] == 400
        assert _post(server, b'{"method": "ping", "params": {}}')[0] == 200  # de server leeft nog
    finally:
        server.shutdown()
        server.server_close()
