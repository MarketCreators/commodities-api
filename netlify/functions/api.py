from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf
from datetime import datetime
from mangum import Mangum
import time

from threading import Lock


app = FastAPI(
    title="Commodities Price API",
    description="Live gold, silver, and crude oil prices scraped from Yahoo Finance",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

COMMODITIES = {
    "gold":      {"ticker": "GC=F", "name": "Gold",          "unit": "USD/oz"},
    "silver":    {"ticker": "SI=F", "name": "Silver",        "unit": "USD/oz"},
    "crude_oil": {"ticker": "CL=F", "name": "Crude Oil WTI", "unit": "USD/bbl"},
}

# ── Cache ────────────────────────────────────────────────────────────────────

CACHE_TTL = 60  # seconds before a cached price is considered stale


_cache: dict[str, dict] = {}   # { commodity_key: {data, fetched_at} }

_cache_lock = Lock()           # thread-safe writes


def cache_get(key: str) -> dict | None:

    entry = _cache.get(key)

    if entry and (time.time() - entry["fetched_at"]) < CACHE_TTL:

        return entry["data"]

    return None


def cache_set(key: str, data: dict):

    with _cache_lock:

        _cache[key] = {"data": data, "fetched_at": time.time()}


def cache_age(key: str) -> float | None:

    entry = _cache.get(key)

    if entry:

        return round(time.time() - entry["fetched_at"], 1)

    return None

# ─────────────────────────────────────────────────────────────────────────────


class CommodityPrice(BaseModel):
    commodity:   str
    ticker:      str
    name:        str
    price:       float
    change:      float
    change_pct:  float
    unit:        str
    currency:    str
    timestamp:   str
    cached:      bool   # true if this response came from cache

    cache_age_s: float | None  # seconds since last live fetch


def fetch_price(ticker_symbol: str) -> dict:
    ticker = yf.Ticker(ticker_symbol)
    info   = ticker.fast_info
    price  = info.last_price
    prev   = info.previous_close
    if price is None or prev is None:
        raise ValueError(f"No data returned for {ticker_symbol}")
    change     = round(price - prev, 4)
    change_pct = round((change / prev) * 100, 4)
    return {
        "price":      round(price, 2),
        "change":     change,
        "change_pct": change_pct,
        "timestamp":  datetime.utcnow().isoformat() + "Z",
    }

def get_commodity_data(key: str, meta: dict) -> tuple[dict, bool]:

    """Return (price_data, from_cache). Hits cache first, scrapes on miss."""

    cached_data = cache_get(key)

    if cached_data:

        return cached_data, True

    live_data = fetch_price(meta["ticker"])

    cache_set(key, live_data)

    return live_data, False


@app.get("/")
def root():
    return {
        "name":        "Commodities Price API",
        "version":     "1.0.0",
        "endpoints":   ["/prices", "/prices/{commodity}", "/cache/status"],
        "commodities": list(COMMODITIES.keys()),
        "cache_ttl_s": CACHE_TTL,

    }

@app.get("/prices", response_model=list[CommodityPrice])
def get_all_prices():
    results = []
    for key, meta in COMMODITIES.items():
        try:
            data, from_cache = get_commodity_data(key, meta)

            results.append(CommodityPrice(
                commodity    = key,
                ticker       = meta["ticker"],
                name         = meta["name"],
                unit         = meta["unit"],
                currency     = "USD",
                cached       = from_cache,

                cache_age_s  = cache_age(key),

                **data,
            ))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch {key}: {str(e)}")
    return results

@app.get("/prices/{commodity}", response_model=CommodityPrice)
def get_price(commodity: str):
    key = commodity.lower()
    if key not in COMMODITIES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown commodity '{commodity}'. Choose from: {list(COMMODITIES.keys())}"
        )
    meta = COMMODITIES[key]
    try:
        data, from_cache = get_commodity_data(key, meta)

    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return CommodityPrice(
        commodity    = key,
        ticker       = meta["ticker"],
        name         = meta["name"],
        unit         = meta["unit"],
        currency     = "USD",
        cached       = from_cache,

        cache_age_s  = cache_age(key),

        **data,
    )

@app.get("/cache/status")

def cache_status():

    """Inspect what's currently in cache — useful for debugging."""

    now = time.time()

    result = {}

    for key in COMMODITIES:

        entry = _cache.get(key)

        if entry:

            age = round(now - entry["fetched_at"], 1)

            result[key] = {

                "cached":     True,

                "age_s":      age,

                "expires_in": max(0, round(CACHE_TTL - age, 1)),

                "price":      entry["data"]["price"],

                "fetched_at": datetime.utcfromtimestamp(entry["fetched_at"]).isoformat() + "Z",

            }

        else:

            result[key] = {"cached": False}

    return result


# Netlify Functions entrypoint
handler = Mangum(app, lifespan="off")