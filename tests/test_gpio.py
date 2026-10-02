import pytest

from rpitest.agent.client import LocalClient, RemoteGpioPort, RpcClient
from rpitest.agent.core import Agent
from rpitest.agent.server import make_server, serve_in_thread
from rpitest.checks import gpio
from rpitest.context import Context
from rpitest.gpio.mock import DUT, TESTER, MockWiring
from rpitest.models import Status
from rpitest.runner import CHECK_GROUPS, run_all

INFO = {"model": "Raspberry Pi 5 (mock)", "ram_mb": 8192, "serial": "MOCK0001"}


def make_ctx(*faults):
    wiring = MockWiring()
    for kind, *args in faults:
        wiring.add_fault(kind, *args)
    client = LocalClient(Agent(wiring.port(DUT), lambda: INFO))
    ctx = Context(wiring.port(TESTER), RemoteGpioPort(client), client, {})
    return ctx, wiring


def results_by_name(ctx):
    return {r.name: r for r in gpio.run(ctx)}


def test_healthy_pair_passes_without_contention():
    ctx, wiring = make_ctx()
    results = results_by_name(ctx)
    assert results["gpio.pulls"].status is Status.PASS
    assert results["gpio.drive"].status is Status.PASS
    assert wiring.contention == []  # de test mag nooit twee uitgangen tegen elkaar zetten


@pytest.mark.parametrize("value,fault", [(0, "stuck_low"), (1, "stuck_high")])
def test_dut_pin_stuck(value, fault):
    ctx, _ = make_ctx((fault, DUT, 9))
    results = results_by_name(ctx)
    assert results["gpio.drive"].status is Status.FAIL
    assert results["gpio.drive"].details["pins"][9] != "OK"
    assert "hangt vast" in " ".join(results["gpio.drive"].details["pins"][9])
    assert results["gpio.pulls"].status is Status.FAIL
    # alleen pin 9 is slecht
    bad = [p for p, v in results["gpio.drive"].details["pins"].items() if v != "OK"]
    assert bad == [9]


def test_bridge_between_neighbours():
    ctx, _ = make_ctx(("bridge", DUT, 5, 6))
    result = results_by_name(ctx)["gpio.drive"]
    assert result.status is Status.FAIL
    assert result.details["bridges"] == [[5, 6]]
    bad = sorted(p for p, v in result.details["pins"].items() if v != "OK")
    assert bad == [5, 6]


def test_open_connection_detected_in_both_directions():
    ctx, _ = make_ctx(("open", 7))
    result = results_by_name(ctx)["gpio.drive"]
    assert result.status is Status.FAIL
    assert "beide richtingen" in " ".join(result.details["pins"][7])
    assert [p for p, v in result.details["pins"].items() if v != "OK"] == [7]


def test_external_pullup_pins_are_not_false_positives():
    ctx, _ = make_ctx()
    result = results_by_name(ctx)["gpio.drive"]
    assert result.details["pins"][2] == "OK" and result.details["pins"][3] == "OK"


def test_stuck_pin_on_tester_shows_up_too():
    # een slechte testpi moet opvallen (wordt gebruikt voor de zelftest met een goede DUT)
    ctx, _ = make_ctx(("stuck_low", TESTER, 12))
    assert results_by_name(ctx)["gpio.drive"].status is Status.FAIL


def test_http_transport_roundtrip():
    wiring = MockWiring()
    server = make_server(Agent(wiring.port(DUT), lambda: INFO), "127.0.0.1", 0)
    serve_in_thread(server)
    try:
        client = RpcClient(f"http://127.0.0.1:{server.server_address[1]}")
        ctx = Context(wiring.port(TESTER), RemoteGpioPort(client), client, {})
        report = run_all(ctx, {"gpio": gpio.run})  # netwerk/wifi/bt hebben hier geen backend
        assert report.overall == "PASS"
        assert report.dut_info["serial"] == "MOCK0001"
    finally:
        server.shutdown()


def test_unreachable_dut_skips_everything_else():
    wiring = MockWiring()
    client = RpcClient("http://127.0.0.1:9", timeout=0.5)  # poort 9: niemand luistert
    ctx = Context(wiring.port(TESTER), RemoteGpioPort(client), client, {})
    report = run_all(ctx)
    statuses = {r.name: r.status for r in report.results}
    assert statuses == {"connect": Status.FAIL, **{name: Status.SKIP for name in CHECK_GROUPS}}
    assert report.overall == "FAIL"


def test_unknown_rpc_method_is_an_error():
    ctx, _ = make_ctx()
    with pytest.raises(Exception, match="onbekende methode"):
        ctx.dut.call("rm_rf")
