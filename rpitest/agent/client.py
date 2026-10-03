from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterable

from ..gpio.ports import GpioPort
from .core import Agent


class RpcError(Exception):
    pass


class RpcClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._url = base_url.rstrip("/") + "/rpc"
        self._timeout = timeout
        # geen systeemproxy: het verkeer loopt over een rechtstreekse kabel
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method: str, _timeout: float | None = None, **params):
        """_timeout: seconden voor trage opdrachten (scan, iperf3, ...)."""
        request = urllib.request.Request(
            self._url,
            data=json.dumps({"method": method, "params": params}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=_timeout or self._timeout) as response:
                body = json.load(response)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RpcError(f"TEST-CLIENT niet bereikbaar: {exc}") from exc
        if "error" in body:
            raise RpcError(body["error"])
        return body["result"]


class LocalClient:
    """Zelfde interface als RpcClient, voor een agent in hetzelfde proces (mock/tests)."""

    def __init__(self, agent: Agent):
        self._agent = agent

    def call(self, method: str, _timeout: float | None = None, **params):
        try:
            return self._agent.dispatch(method, params)
        except Exception as exc:
            raise RpcError(f"{type(exc).__name__}: {exc}") from exc


class RemoteGpioPort(GpioPort):
    def __init__(self, client):
        self._client = client

    def set_input(self, pins: Iterable[int], pull: str) -> None:
        self._client.call("gpio_set_input", pins=list(pins), pull=pull)

    def drive(self, pin: int, value: int) -> None:
        self._client.call("gpio_drive", pin=pin, value=value)

    def read(self, pins: Iterable[int]) -> dict[int, int]:
        result = self._client.call("gpio_read", pins=list(pins))
        return {int(k): v for k, v in result.items()}
