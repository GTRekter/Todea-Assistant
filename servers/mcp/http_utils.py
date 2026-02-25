"""Shared HTTP utilities used by both fleet_agent and universe_agent."""
import json
from typing import Any, Dict, Mapping, Optional
from urllib import error as urllib_error
from urllib import parse, request as urllib_request


def _format_response(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=4)


def _format_url(url: str, params: Optional[Mapping[str, Any]]) -> str:
    if not params:
        return url
    query = parse.urlencode(params, doseq=True)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}"


def _decode_bytes(payload: bytes, encoding_header: Optional[str]) -> str:
    if not payload:
        return ""
    encoding = encoding_header or "utf-8"
    try:
        return payload.decode(encoding, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def request_json(
    method: str,
    url: str,
    *,
    payload: Optional[Mapping[str, Any]] = None,
    params: Optional[Mapping[str, Any]] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    full_url = _format_url(url, params)
    data: Optional[bytes] = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request_obj = urllib_request.Request(full_url, data=data, headers=headers, method=method.upper())
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout) as response:
            raw_body = response.read()
            if not raw_body:
                return {"detail": f"{method} {full_url} succeeded with no response body."}
            body_text = _decode_bytes(raw_body, response.headers.get_content_charset())
    except urllib_error.HTTPError as exc:
        detail_text = _decode_bytes(exc.read(), exc.headers.get_content_charset() if exc.headers else None)
        try:
            detail = json.loads(detail_text) if detail_text else None
        except ValueError:
            detail = detail_text or None
        return {
            "error": f"{method} {full_url} failed",
            "status": exc.code,
            "detail": detail or detail_text or exc.reason,
        }
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", None)
        return {
            "error": f"{method} {full_url} failed",
            "status": None,
            "detail": str(reason or exc),
        }
    try:
        return json.loads(body_text)
    except ValueError:
        return {"raw": body_text}
