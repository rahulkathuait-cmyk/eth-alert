"""
ETH Option Alert  (Delta Exchange India)
----------------------------------------
- ETH ka current price leta hai
- Current price se +/- RANGE_POINTS ke andar wale strikes ke Call aur Put options dekhta hai
- Agar 2 baje (IST) se pehle koi option price  PRICE_LIMIT ($0.20) se neeche jaaye -> ALERT
  (beep sound + screen popup + optional Telegram message mobile par)

Chalane ke liye:
    pip install requests
    python eth_option_alert.py
"""

import time
import datetime as dt
import requests

# ======================= SETTINGS (yahan badlo) =======================
RANGE_POINTS   = 30        # current ETH price se kitne point upar/neeche ke strikes dekhne hain
PRICE_LIMIT    = 0.20      # isse neeche price aaye to alert ($)
PRICE_TYPE     = "mark"    # "mark" = mark price, "ask" = best ask (buy price), "ltp" = last traded price
ALERT_START    = "00:00"   # IST - alert kab se shuru
ALERT_END      = "14:00"   # IST - 2 baje ke baad alert band
CHECK_EVERY    = 15        # har kitne second me check kare
ONLY_NEAREST_EXPIRY = True # True = sirf sabse nazdeek wali expiry (daily) ke options

# Mobile par alert chahiye to Telegram bot banao (@BotFather) aur yahan daalo, warna khaali chhod do
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID   = ""
# =====================================================================

API = "https://api.india.delta.exchange/v2/tickers"
HEADERS = {"Accept": "application/json", "User-Agent": "eth-option-alert/1.0"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def now_ist():
    return dt.datetime.now(IST)


def in_alert_window(t):
    start = dt.time.fromisoformat(ALERT_START)
    end = dt.time.fromisoformat(ALERT_END)
    return start <= t.time() < end


def expiry_from_symbol(sym):
    # C-ETH-2500-151026  -> 15-10-2026
    try:
        return dt.datetime.strptime(sym.split("-")[-1], "%d%m%y").date()
    except Exception:
        return None


def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def get_price(t):
    if PRICE_TYPE == "ask":
        return to_float((t.get("quotes") or {}).get("best_ask"))
    if PRICE_TYPE == "ltp":
        return to_float(t.get("close"))
    return to_float(t.get("mark_price"))


def fetch_options():
    r = requests.get(
        API,
        params={"contract_types": "call_options,put_options", "underlying_asset_symbols": "ETH"},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"API error: {data}")
    return data["result"]


def filter_options(tickers):
    """Current price ke +/- RANGE_POINTS wale options nikaalo."""
    spot = None
    for t in tickers:
        spot = to_float(t.get("spot_price"))
        if spot:
            break
    if not spot:
        raise RuntimeError("ETH spot price nahi mila")

    opts = [t for t in tickers if expiry_from_symbol(t.get("symbol", ""))]
    if ONLY_NEAREST_EXPIRY and opts:
        nearest = min(expiry_from_symbol(t["symbol"]) for t in opts)
        opts = [t for t in opts if expiry_from_symbol(t["symbol"]) == nearest]

    rows = []
    for t in opts:
        strike = to_float(t.get("strike_price"))
        if strike is None or abs(strike - spot) > RANGE_POINTS:
            continue
        rows.append({
            "symbol": t["symbol"],
            "type": "CALL" if t.get("contract_type") == "call_options" else "PUT",
            "strike": strike,
            "price": get_price(t),
        })
    rows.sort(key=lambda r: (r["strike"], r["type"]))
    return spot, rows


# ----------------------------- alerts --------------------------------
def beep():
    try:
        import winsound  # Windows
        for _ in range(3):
            winsound.Beep(1500, 400)
    except Exception:
        print("\a\a\a", end="", flush=True)


def popup(msg):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showwarning("ETH Option Alert", msg)
        root.destroy()
    except Exception:
        pass


def telegram(msg):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception as e:
        print("Telegram error:", e)


def send_alert(hits, spot):
    lines = [f"⚠️ ETH Option Alert  (ETH = ${spot:,.2f})"]
    for h in hits:
        lines.append(f"{h['type']} {h['strike']:.0f}  ->  ${h['price']:.2f}   ({h['symbol']})")
    msg = "\n".join(lines)
    print("\n" + "!" * 50 + "\n" + msg + "\n" + "!" * 50)
    telegram(msg)
    beep()
    popup(msg)


# ------------------------------ main ---------------------------------
def main():
    print(f"ETH option alert chalu. Range ±{RANGE_POINTS}, limit ${PRICE_LIMIT}, "
          f"time {ALERT_START}-{ALERT_END} IST, price = {PRICE_TYPE}\n")
    alerted = set()          # ek option ka alert ek hi baar (jab tak price wapas upar na jaaye)
    last_day = None

    while True:
        t = now_ist()
        if t.date() != last_day:
            alerted.clear()
            last_day = t.date()
        try:
            spot, rows = filter_options(fetch_options())
            print(f"[{t:%H:%M:%S}] ETH ${spot:,.2f} | ", end="")
            print("  ".join(f"{r['type'][0]}{r['strike']:.0f}=${r['price']:.2f}" for r in rows if r["price"] is not None)
                  or "range me koi strike nahi")

            hits = []
            for r in rows:
                if r["price"] is None:
                    continue
                if r["price"] < PRICE_LIMIT:
                    if r["symbol"] not in alerted and in_alert_window(t):
                        hits.append(r)
                        alerted.add(r["symbol"])
                else:
                    alerted.discard(r["symbol"])

            if hits:
                send_alert(hits, spot)
        except Exception as e:
            print(f"[{t:%H:%M:%S}] Error: {e}")

        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()