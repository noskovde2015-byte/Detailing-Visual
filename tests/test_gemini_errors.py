import httpx
from google.genai import errors

from app.services.gemini import (
    is_retryable,
    retry_delay_seconds,
    to_domain_error,
)
from app.services.image_generator import (
    GenerationTemporaryError,
    GenerationUnavailableError,
    ImageGenerationError,
)


def _api_error(code: int, details: list[dict] | None = None) -> errors.APIError:
    return errors.APIError(
        code,
        {
            "error": {
                "code": code,
                "message": "x",
                "status": "X",
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


def test_bad_request_is_generic() -> None:
    error = to_domain_error(_api_error(400))
    assert type(error) is ImageGenerationError
