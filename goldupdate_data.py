"""Builds data.json for the dashboard. Run daily (cron / GitHub Actions).
Setup: pip install requests ; set env FRED_KEY (free key at fred.stlouisfed.org)
Forecasts are not free anywhere reliable: fill FORECASTS by hand or swap in a
paid API (Trading Economics / FMP / Finnhub)."""
import os, json, datetime, requests

FRED = os.environ["FRED_KEY"]
# name: (FRED series, units, higher_is_bullish_for_gold, section, forecast, next_date)
INDICATORS = {
 "GDP Growth QoQ":   ("GDPC1",   "pca", False, "Economic growth", 3.2,  "Dec 20"),
 "CPI YoY":          ("CPIAUCSL","pc1", False, "Inflation",       3.7,  "Dec 10"),
 "PPI YoY":          ("PPIACO",  "pc1", False, "Inflation",       5.3,  "Dec 12"),
 "PCE YoY":          ("PCEPI",   "pc1", False, "Inflation",       3.1,  "Nov 28"),
 "Non-Farm Payroll": ("PAYEMS",  "chg", False, "Jobs market",     65,   "Dec 05"),
 "Unemployment Rate":("UNRATE",  "lin", True,  "Jobs market",     4.2,  "Dec 05"),
 "Weekly Jobless Claims":("ICSA","lin", True,  "Jobs market",     196000,"Nov 20"),
 "JOLTS Job Openings":("JTSJOL", "lin", False, "Jobs market",     7150, "Dec 02"),
}

def fred(series, units):
    r = requests.get("https://api.stlouisfed.org/fred/series/observations", params={
        "series_id": series, "api_key": FRED, "file_type": "json",
        "units": units, "sort_order": "desc", "limit": 5}, timeout=30).json()
    vals = [float(o["value"]) for o in r["observations"] if o["value"] != "."]
    return vals[0]

def signal(actual, forecast, higher_bullish):
    if actual == forecast: return "Neutral", 0
    up = actual > forecast
    bull = up if higher_bullish else not up
    return ("Bullish", 1) if bull else ("Bearish", -1)

def label(s, n):
    r = s / max(n, 1)
    return ("Very Bullish" if r > .6 else "Bullish" if r > .2 else
            "Very Bearish" if r < -.6 else "Bearish" if r < -.2 else "Neutral")

sections, macro = {}, 0
for name, (sid, units, hb, sec, fc, date) in INDICATORS.items():
    try: act = fred(sid, units)
    except Exception as e: print("skip", name, e); continue
    sig, pts = signal(act, fc, hb); macro += pts
    sections.setdefault(sec, {"rows": [], "pts": 0})
    sections[sec]["rows"].append({"name": name, "signal": sig, "actual": round(act, 2),
        "forecast": fc, "surprise": round(act - fc, 2), "date": date})
    sections[sec]["pts"] += pts

# 2yr yield vs its 21-day average
y = requests.get("https://api.stlouisfed.org/fred/series/observations", params={
    "series_id": "DGS2", "api_key": FRED, "file_type": "json",
    "sort_order": "desc", "limit": 30}, timeout=30).json()["observations"]
y = [float(o["value"]) for o in y if o["value"] != "."]
sma = sum(y[:21]) / len(y[:21])
ysig, ypts = ("Bullish", 1) if y[0] < sma else ("Bearish", -1)
macro += ypts

# COT: gold non-commercial net positioning (CFTC legacy report)
c = requests.get("https://publicreporting.cftc.gov/resource/6dca-aqww.json", params={
    "$where": "market_and_exchange_names like 'GOLD - COMMODITY EXCHANGE%'",
    "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 2}, timeout=30).json()
def pct(d):
    l, s = float(d["noncomm_positions_long_all"]), float(d["noncomm_positions_short_all"])
    return l / (l + s) * 100
cot = {"long": round(pct(c[0]), 2), "short": round(100 - pct(c[0]), 2),
       "change": round(pct(c[0]) - pct(c[1]), 2), "date": c[0]["report_date_as_yyyy_mm_dd"][:10]}
cot_pts = (1 if cot["long"] > 50 else -1) + (1 if cot["change"] > 0 else -1)

total = macro + cot_pts
out = {"symbol": "GOLD", "updated": datetime.datetime.utcnow().isoformat() + "Z",
       "overall": label(total, 14), "scores": {"total": total, "macro": macro, "technical": 0, "sentiment": 0},
       "cot": cot, "yield2y": {"signal": ysig, "latest": y[0], "sma21": round(sma, 2)},
       "sections": [{"title": k, "label": label(v["pts"], len(v["rows"])), "rows": v["rows"]}
                    for k, v in sections.items()]}
json.dump(out, open("data.json", "w"), indent=1)
print("data.json written, total score", total)
