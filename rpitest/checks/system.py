from __future__ import annotations

from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status


def check_connect(ctx: Context) -> tuple[CheckResult, dict]:
    """Bereikt de testpi de agent op de DUT? Geeft ook de DUT-info terug voor in het rapport."""
    try:
        ctx.dut.call("ping")
        info = ctx.dut.call("info")
    except RpcError as exc:
        return CheckResult("connect", Status.FAIL, f"geen verbinding met de DUT: {exc}"), {}
    return CheckResult("connect", Status.PASS, f"verbonden met {info.get('model', '?')}", info), info
