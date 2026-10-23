"""One fresh BHEL quote for staging simulations; no broker order API."""
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo


def fetch_quote(credentials):
    from broker.groww.api.auth_api import authenticate_broker
    from broker.groww.api.rate_limiter import groww_request
    from utils.httpx_client import get_httpx_client
    try:
        token, _ = authenticate_broker(None, credentials=credentials)
        if not token:
            return None, "Groww authentication failed. Check today's approval and your saved credentials."
        response = groww_request(get_httpx_client(), "GET", "https://api.groww.in/v1/live-data/quote", "live",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "X-API-VERSION": "1.0"},
            params={"exchange": "NSE", "segment": "CASH", "trading_symbol": "BHEL"}, timeout=15)
        body = response.json()
        if response.status_code != 200 or not isinstance(body, dict) or body.get("status") != "SUCCESS":
            raise ValueError("Quote refused")
        payload = body.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("ohlc"), dict):
            raise ValueError("Invalid quote")
        price, stamp = payload.get("last_price"), payload.get("last_trade_time")
        low, high = payload["ohlc"].get("low"), payload["ohlc"].get("high")
        for value in (price, stamp, low, high):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid quote value")
        # Groww quote timestamps are epoch seconds. Never substitute receipt time.
        age = time.time() - stamp
        if age < -5 or age > 120:
            return None, "Quote is older than 2 minutes or its clock is invalid. No paper order placed; try during market hours."
        if not low <= price <= high:
            raise ValueError("Incoherent quote")
        return dict(ltp=float(price), low=float(low), high=float(high),
                    last_trade_time=int(stamp), source="Groww BHEL/NSE", age_seconds=max(0, int(age)),
                    traded_at_ist=datetime.fromtimestamp(stamp, ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y %H:%M:%S IST')), None
    except Exception:
        return None, "Could not obtain a valid Groww BHEL quote. No paper order placed."
