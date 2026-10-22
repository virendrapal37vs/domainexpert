"""Fixed, single-day read-only history preview with transient owner credentials."""
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def fetch_preview(credentials):
    day = datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    base = dict(symbol="BHEL", exchange="NSE", interval="5m", date=str(day),
                timezone="Asia/Kolkata", trading_enabled=False)
    from broker.groww.api.auth_api import authenticate_broker
    from broker.groww.api.data import BrokerData
    try:
        token, _ = authenticate_broker(None, credentials=credentials)
        if not token:
            return dict(base, status="error", message="Groww authentication failed. Check today's key approval and your saved credentials.")
        frame = BrokerData(token).get_history("BHEL", "NSE", "5m", str(day), str(day))
        if len(frame) > 300:
            raise ValueError("Unexpected candle count")
        candles = []
        for row in frame.to_dict(orient="records"):
            clean = {}
            for field in ("timestamp", "open", "high", "low", "close", "volume"):
                value = row[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("Unexpected candle value")
                if field in ("timestamp", "volume"):
                    if value < 0 or int(value) != value:
                        raise ValueError("Unexpected integer value")
                    clean[field] = int(value)
                else:
                    clean[field] = float(value)
            candles.append(clean)
        return dict(base, status="success", count=len(candles), candles=candles,
                    message="Historical candles loaded. Trading remains disabled." if candles else
                    "No candles returned for this date; it may be a market holiday. Trading remains disabled.")
    except Exception:
        # Never expose raw broker errors, headers, credential values or tokens.
        return dict(base, status="error", message="History preview failed. Check Groww access and that the staging BHEL/NSE master contract is loaded.")
