import httpx
import pytest

from mcp_client import failure_reason, unavailable


def status_error(code):
    request = httpx.Request("POST", "http://tools-vm/mcp")
    return httpx.HTTPStatusError("x", request=request, response=httpx.Response(code, request=request))


@pytest.mark.parametrize("exc,reason", [
    (status_error(401), "unauthorized"),
    (status_error(421), "host_not_allowed"),
    (status_error(502), "http_502"),
    (ExceptionGroup("tg", [status_error(401)]), "unauthorized"),
    (TimeoutError(), "timeout"),
    (httpx.ConnectError("refused"), "connection_failed"),
    (ValueError("bad json"), "invalid_response"),
    (RuntimeError("other"), "error_runtimeerror"),
])
def test_failures_get_short_fixed_reasons(exc, reason):
    assert failure_reason(exc) == reason


def test_unavailable_logs_the_reason_without_details(caplog):
    caplog.set_level("WARNING", logger="uvicorn.error")
    result = unavailable("web", "web_search", ExceptionGroup("tg", [status_error(401)]))
    assert result == {"error": "web_unavailable", "reason": "unauthorized"}
    assert '"reason": "unauthorized"' in caplog.text and "tools-vm" not in caplog.text
