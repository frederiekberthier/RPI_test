import pytest

from rpitest.agent.client import LocalClient, RemoteGpioPort, RpcClient
from rpitest.agent.core import Agent
from rpitest.agent.server import make_server, serve_in_thread
from rpitest.context import Context
from rpitest.gpio.mock import MockWiring
from rpitest.gpio.mock import CLIENT as GPIO_CLIENT, SERVER as GPIO_SERVER
from rpitest.models import Status
from rpitest.runner import run_all
from rpitest.system import mock as sysmock

INFO = {"model": "Raspberry Pi 5 (mock)", "ram_mb": 8192, "serial": "MOCK0001"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("rpitest.checks.wifi.time.sleep", lambda s: None)


def make_ctx(*faults):
    env = sysmock.MockEnv(faults)
    wiring = MockWiring()
    client = LocalClient(Agent(wiring.port(GPIO_CLIENT), lambda: INFO, env.ops(sysmock.CLIENT)))
    ctx = Context(wiring.port(GPIO_SERVER), RemoteGpioPort(client), client, {}, env.ops(sysmock.SERVER))
    return ctx, env


def statuses(ctx):
    return {r.name: r.status for r in run_all(ctx).results}


def test_healthy_system_passes_everything():
    ctx, env = make_ctx()
    report = run_all(ctx)
    assert report.overall == "PASS", [(r.name, r.summary) for r in report.results if r.status is not Status.PASS]
    assert not env.hotspot and not env.client_connected  # alles netjes opgeruimd
    assert not any(env.discoverable.values())


def test_all_names_present():
    ctx, _ = make_ctx()
    assert set(statuses(ctx)) >= {"net.link", "net.latency", "net.throughput", "net.errors", "wifi.radio",
                                  "wifi.2.4GHz", "wifi.5GHz", "bt.controller", "bt.receive", "bt.transmit"}


def test_slow_link_negotiation_fails():
    ctx, _ = make_ctx("eth_100")
    result = {r.name: r for r in run_all(ctx).results}["net.link"]
    assert result.status is Status.FAIL and "100 Mb/s" in result.summary


def test_packet_loss_fails():
    ctx, _ = make_ctx("eth_loss")
    assert statuses(ctx)["net.latency"] is Status.FAIL


def test_low_throughput_fails():
    ctx, _ = make_ctx("eth_slow")
    assert statuses(ctx)["net.throughput"] is Status.FAIL


def test_ethernet_errors_are_counted_as_delta():
    ctx, _ = make_ctx("eth_errors")
    assert statuses(ctx)["net.errors"] is Status.FAIL


def test_dead_5ghz_only_fails_5ghz():
    ctx, env = make_ctx("wifi_5g_dead")
    s = statuses(ctx)
    assert s["wifi.5GHz"] is Status.FAIL and s["wifi.2.4GHz"] is Status.PASS
    assert env.hotspot is None  # ook na een fout wordt de hotspot gestopt


def test_missing_wifi_fails_radio_and_skips_bands():
    ctx, _ = make_ctx("no_wifi")
    s = statuses(ctx)
    assert s["wifi.radio"] is Status.FAIL
    assert s["wifi.2.4GHz"] is Status.SKIP and s["wifi.5GHz"] is Status.SKIP


def test_weak_signal_warns():
    ctx, _ = make_ctx("wifi_weak")
    s = statuses(ctx)
    assert s["wifi.2.4GHz"] is Status.WARN


def test_server_without_wifi_skips_instead_of_blaming_the_client():
    ctx, _ = make_ctx("server_no_wifi")
    s = statuses(ctx)
    assert s["wifi"] is Status.SKIP and "wifi.radio" not in s


def test_missing_bluetooth_fails_controller():
    ctx, _ = make_ctx("no_bt")
    s = statuses(ctx)
    assert s["bt.controller"] is Status.FAIL and s["bt.receive"] is Status.SKIP


def test_receive_and_transmit_are_independent():
    ctx, _ = make_ctx("bt_client_rx_dead")
    s = statuses(ctx)
    assert s["bt.receive"] is Status.FAIL and s["bt.transmit"] is Status.PASS
    ctx, _ = make_ctx("bt_client_tx_dead")
    s = statuses(ctx)
    assert s["bt.receive"] is Status.PASS and s["bt.transmit"] is Status.FAIL


def test_server_without_bluetooth_skips():
    ctx, _ = make_ctx("server_no_bt")
    assert statuses(ctx)["bluetooth"] is Status.SKIP


def test_unknown_fault_name_is_rejected():
    with pytest.raises(ValueError):
        sysmock.MockEnv(["eth_kapot"])


def test_agent_validates_parameters():
    ctx, _ = make_ctx()
    for method, params in [
        ("net_ping", {"host": "8.8.8.8; reboot", "count": 5}),
        ("net_ping", {"host": "192.168.77.1", "count": 100000}),
        ("wifi_connect", {"ssid": "x" * 40, "password": "wachtwoord1"}),
        ("wifi_connect", {"ssid": "ok", "password": "kort"}),
        ("bt_scan", {"seconds": 5, "forget_mac": "niet-een-mac"}),
        ("bt_discoverable", {"enabled": "yes"}),
    ]:
        with pytest.raises(Exception, match="Error"):
            ctx.client.call(method, **params)


def test_agent_without_system_backend_says_so():
    wiring = MockWiring()
    client = LocalClient(Agent(wiring.port(GPIO_CLIENT), lambda: INFO))
    with pytest.raises(Exception, match="geen systeem-backend"):
        client.call("net_iface_info")


def test_full_run_over_http_with_slow_call_timeouts():
    env = sysmock.MockEnv()
    wiring = MockWiring()
    server = make_server(Agent(wiring.port(GPIO_CLIENT), lambda: INFO, env.ops(sysmock.CLIENT)), "127.0.0.1", 0)
    serve_in_thread(server)
    try:
        client = RpcClient(f"http://127.0.0.1:{server.server_address[1]}")
        ctx = Context(wiring.port(GPIO_SERVER), RemoteGpioPort(client), client, {}, env.ops(sysmock.SERVER))
        assert run_all(ctx).overall == "PASS"
    finally:
        server.shutdown()
