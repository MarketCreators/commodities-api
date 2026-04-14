from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf
from datetime import datetime
from mangum import Mangum


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

class CommodityPrice(BaseModel):
    commodity:  str
    ticker:     str
    name:       str
    price:      float
    change:     float
    change_pct: float
    unit:       str
    currency:   str
    timestamp:  str

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
    }

@app.get("/")
def root():
    return {
        "name":      "Commodities Price API",
        "version":   "1.0.0",
        "endpoints": ["/prices", "/prices/{commodity}"],
        "commodities": list(COMMODITIES.keys()),
    }

@app.get("/prices", response_model=list[CommodityPrice])
def get_all_prices():
    results = []
    for key, meta in COMMODITIES.items():
        try:
            data = fetch_price(meta["ticker"])
            results.append(CommodityPrice(
                commodity  = key,
                ticker     = meta["ticker"],
                name       = meta["name"],
                unit       = meta["unit"],
                currency   = "USD",
                timestamp  = datetime.utcnow().isoformat() + "Z",
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
        data = fetch_price(meta["ticker"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return CommodityPrice(
        commodity  = key,
        ticker     = meta["ticker"],
        name       = meta["name"],
        unit       = meta["unit"],
        currency   = "USD",
        timestamp  = datetime.utcnow().isoformat() + "Z",
        **data,
    )

# Netlify Functions entrypoint

handler = Mangum(app, lifespan="off")