from __future__ import annotations

from ..agent.client import RpcError
from ..context import Context
from ..models import CheckResult, Status


def check_connect(ctx: Context) -> tuple[CheckResult, dict]:
    """Bereikt de TEST-SERVER de agent op de TEST-CLIENT? Geeft ook de gegevens van de TEST-CLIENT terug voor in het rapport."""
    try:
        ctx.client.call("ping")
        info = ctx.client.call("info")
    except RpcError as exc:
        return CheckResult("connect", Status.FAIL, f"geen verbinding met de TEST-CLIENT: {exc}"), {}
    return CheckResult("connect", Status.PASS, f"verbonden met {info.get('model', '?')}", info), info
