"""One-shot Groww authentication + quote probe; no token persistence or order API.

Protocol: https://groww.in/trade-api/docs/curl
Quote: https://groww.in/trade-api/docs/curl/live-data
"""
import hashlib
import math
import time

import httpx

TOKEN_URL = "https://api.groww.in/v1/token/api/access"
QUOTE_URL = "https://api.groww.in/v1/live-data/quote"


def _failure(stage, http_status=None, reason="broker_rejected"):
    messages = {
        "broker_rejected": "Groww rejected this connection check.",
        "forbidden": "Groww returned 403 Access forbidden. Check API approval, subscription and allowed IP with Groww support.",
        "rate_limited": "Groww is limiting requests. Wait before trying again.",
        "network": "Could not reach Groww. Try again later.",
        "invalid_response": "Groww returned an unexpected response.",
        "inactive_token": "Groww returned an inactive token. Check today's API approval.",
    }
    if http_status == 403:
        reason = "forbidden"
    elif http_status == 429:
        reason = "rate_limited"
    return {"status": "error", "stage": stage, "http_status": http_status,
            "reason": reason, "message": messages[reason]}


def check_connection(api_key, api_secret, *, transport=None):
    """Use only the supplied owner's credentials; never consult environment keys.

    Fixed HTTPS destinations, no redirects, no automatic retries, no raw error
    bodies. The transient access token is used for ONE BHEL quote and discarded.
    A successful quote does not prove order permission or a future working feed.
    """
    stamp = str(int(time.time()))
    checksum = hashlib.sha256((api_secret + stamp).encode()).hexdigest()
    stage = "authentication"
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False,
                          trust_env=False, transport=transport) as client:
            response = client.post(TOKEN_URL, headers={
                "Authorization": f"Bearer {api_key}", "Accept": "application/json",
                "X-API-VERSION": "1.0",
            }, json={"key_type": "approval", "checksum": checksum, "timestamp": stamp})
            if response.status_code != 200:
                return _failure(stage, response.status_code)
            try:
                body = response.json()
            except ValueError:
                return _failure(stage, 200, "invalid_response")
            token = body.get("token") if isinstance(body, dict) else None
            if not isinstance(token, str) or not token or len(token) > 16384:
                return _failure(stage, 200, "invalid_response")
            if body.get("isActive") is False:
                return _failure(stage, 200, "inactive_token")
            stage = "quote"
            response = client.get(QUOTE_URL, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json",
                "X-API-VERSION": "1.0",
            }, params={"exchange": "NSE", "segment": "CASH", "trading_symbol": "BHEL"})
            if response.status_code != 200:
                return _failure(stage, response.status_code)
            try:
                body = response.json()
            except ValueError:
                return _failure(stage, 200, "invalid_response")
            if not isinstance(body, dict) or body.get("status") != "SUCCESS" or not isinstance(body.get("payload"), dict):
                return _failure(stage, 200, "invalid_response")
            price = body["payload"].get("last_price")
            if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
                return _failure(stage, 200, "invalid_response")
            return {"status": "success", "stage": "quote", "http_status": 200,
                    "message": "Groww authentication and BHEL quote check succeeded. Trading remains disabled."}
    except (httpx.HTTPError, ValueError):
        # Never return exception text: it may contain headers, URLs or credentials.
        return _failure(stage, reason="network")
