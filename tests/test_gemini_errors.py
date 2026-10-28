import aiohttp
import httpx
import pytest
from google.genai import errors

from app.services.gemini import (
    is_retryable,
    outage_reason,
    retry_delay_seconds,
    to_domain_error,
)
from app.services.image_generator import (
    GenerationTemporaryError,
    GenerationUnavailableError,
    ImageGenerationError,
    OutageReason,
)


def _api_error(
    code: int,
    details: list[dict] | None = None,
    *,
    message: str = "x",
    status: str = "X",
) -> errors.APIError:
    return errors.APIError(
        code,
        {
            "error": {
                "code": code,
                "message": message,
                "status": status,
                "details": details or [],
            }
        },
    )


def _retry_info(delay: str) -> dict:
    return {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}


def _daily_quota() -> dict:
    return {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
        ],
    }


def test_retry_delay_parsed() -> None:
    assert retry_delay_seconds(_api_error(429, [_retry_info("65556s")])) == 65556.0
    assert retry_delay_seconds(_api_error(429)) is None


def test_short_rate_limit_is_retried() -> None:
    assert is_retryable(_api_error(429, [_retry_info("2s")]))
    assert is_retryable(_api_error(429))


def test_long_delay_is_not_retried() -> None:
    exc = _api_error(429, [_retry_info("65556s")])
    assert not is_retryable(exc)
    assert isinstance(to_domain_error(exc), GenerationUnavailableError)


def test_daily_quota_is_not_retried() -> None:
    exc = _api_error(429, [_daily_quota(), _retry_info("5s")])
    assert not is_retryable(exc)
    assert isinstance(to_domain_error(exc), GenerationUnavailableError)


def test_server_and_network_errors_are_retried() -> None:
    assert is_retryable(_api_error(503))
    assert is_retryable(TimeoutError())
    assert is_retryable(httpx.ConnectError("boom"))
    assert isinstance(to_domain_error(_api_error(503)), GenerationTemporaryError)


def test_auth_and_model_errors_need_attention() -> None:
    for code in (401, 403, 404):
        exc = _api_error(code)
        assert not is_retryable(exc)
        assert isinstance(to_domain_error(exc), GenerationUnavailableError)


REGION_MESSAGE = "User location is not supported for the API use."


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (
            _api_error(400, message=REGION_MESSAGE, status="FAILED_PRECONDITION"),
            OutageReason.REGION,
        ),
        (
            _api_error(
                400,
                message="Gemini API free tier is not available. Enable billing.",
                status="FAILED_PRECONDITION",
            ),
            OutageReason.BILLING,
        ),
        (
            _api_error(402, message="Prepayment credits are depleted"),
            OutageReason.BILLING,
        ),
        (
            _api_error(
                400,
                [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "API_KEY_INVALID",
                    }
                ],
                message="API key not valid. Please pass a valid API key.",
                status="INVALID_ARGUMENT",
            ),
            OutageReason.AUTH,
        ),
        (_api_error(401), OutageReason.AUTH),
        (_api_error(403, message="Permission denied"), OutageReason.AUTH),
        (_api_error(403, message="Billing account disabled"), OutageReason.BILLING),
        (_api_error(404), OutageReason.MODEL),
        (_api_error(429, [_daily_quota()]), OutageReason.QUOTA),
        (httpx.ConnectError("proxy refused"), OutageReason.NETWORK),
        (httpx.ProxyError("502 from proxy"), OutageReason.NETWORK),
        (aiohttp.ServerDisconnectedError(), OutageReason.NETWORK),
        (aiohttp.ClientOSError(104, "Connection reset by peer"), OutageReason.NETWORK),
    ],
)
def test_outage_reasons(exc: BaseException, reason: OutageReason) -> None:
    assert outage_reason(exc) is reason
    error = to_domain_error(exc)
    assert isinstance(error, GenerationUnavailableError)
    assert error.reason is reason
    assert error.detail


@pytest.mark.parametrize(
    "exc",
    [
        _api_error(400, status="INVALID_ARGUMENT"),
        _api_error(400, message="Something else", status="FAILED_PRECONDITION"),
        _api_error(429, [_retry_info("2s")]),
        _api_error(500),
        _api_error(503),
        TimeoutError(),
    ],
)
def test_single_task_errors_do_not_pause(exc: BaseException) -> None:
    assert outage_reason(exc) is None
    assert not isinstance(to_domain_error(exc), GenerationUnavailableError)


def test_network_errors_are_retried_inside_request_first() -> None:
    # Сначала несколько попыток в рамках запроса (переключение узла), и только
    # если не помогло — пауза для всех.
    assert is_retryable(aiohttp.ServerDisconnectedError())
    assert is_retryable(httpx.ConnectError("x"))


def test_detail_is_short_and_single_line() -> None:
    exc = _api_error(402, message="line one\n" + "x" * 2000)
    detail = to_domain_error(exc)
    assert isinstance(detail, GenerationUnavailableError)
    assert "\n" not in detail.detail
    assert len(detail.detail) <= 500
    assert detail.detail.startswith("HTTP 402")


def test_bad_request_is_generic() -> None:
    error = to_domain_error(_api_error(400))
    assert type(error) is ImageGenerationError
