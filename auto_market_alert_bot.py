# -*- coding: utf-8 -*-
import os
import time
import random
import requests
import threading
from datetime import datetime, timedelta
import pytz
import telebot
from flask import Flask

# ========== إعدادات عامة ==========
TOKEN       = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"  # توكن البوت
CHANNEL_ID  = "@kaaty320"                                       # قناة التلغرام
FINNHUB_KEY = "d3udq1hr01qi14apjtb0d3udq1hr01qi14apjtbg"        # مفتاح Finnhub

MARKET_MICS = {"XNAS", "XNYS", "XASE"}  # الأسواق المطلوبة
CHECK_INTERVAL_SEC = 60                 # مدة كل دورة فحص (ثواني)
UP_CHANGE_PCT = 5                       # الزخم: 5% أو أكثر
MIN_VOL_15M = 100_000                   # الحد الأدنى لحجم التداول
MIN_DOLLAR_15M = 200_000                # الحد الأدنى لقيمة التداول
REPEAT_COOLDOWN_S = 15 * 60             # مدة التبريد لمنع التكرار
TOP_N = 50                              # عدد الأسهم الأعلى زخماً
PRICE_FILTER = 0.4                      # تجاهل الأسهم أقل من 0.4$

US_TZ = pytz.timezone("US/Eastern")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
last_sent = {}
_daily_counts = {}

BASE = "https://finnhub.io/api/v1"

# ------------------- أدوات Finnhub -------------------
def fh_get_symbols_us():
    """جلب رموز الأسهم الأمريكية"""
    try:
        r = requests.get(f"{BASE}/stock/symbol", params={"exchange": "US", "token": FINNHUB_KEY}, timeout=20)
        r.raise_for_status()
        data = r.json()
        syms = [x["symbol"] for x in data if (x.get("mic", "").upper() in MARKET_MICS and x.get("symbol", "").isalpha() and len(x["symbol"]) <= 5)]
        return sorted(set(syms))
    except Exception as e:
        print("fh_get_symbols_us error:", e)
        return []

def fh_quote(symbol):
    """جلب بيانات السعر"""
    r = requests.get(f"{BASE}/quote", params={"symbol": symbol, "token": FINNHUB_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()

def fh_candles_1m(symbol, frm, to):
    """جلب الشموع الدقيقة"""
    r = requests.get(f"{BASE}/stock/candle", params={"symbol": symbol, "resolution": 1, "from": int(frm), "to": int(to), "token": FINNHUB_KEY}, timeout=20)
    r.raise_for_status()
    return r.json()

def fh_profile(symbol):
    """جلب الملف التعريفي للسهم"""
    try:
        r = requests.get(f"{BASE}/stock/profile2", params={"symbol": symbol, "token": FINNHUB_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def fh_metrics(symbol):
    """جلب المقاييس العامة"""
    try:
        r = requests.get(f"{BASE}/stock/metric", params={"symbol": symbol, "metric": "all", "token": FINNHUB_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

# ------------------- الأدوات -------------------
def compute_vol_15m(symbol, price):
    """حساب حجم التداول خلال آخر 15 دقيقة"""
    now = int(datetime.utcnow().timestamp())
    frm = now - 3600
    try:
        data = fh_candles_1m(symbol, frm, now)
        if data.get("s") != "ok":
            return False, 0, 0, {}
        vols = data.get("v", []) or []
        vol_15 = sum(vols[-15:])
        first_min = vols[-15] if len(vols) >= 15 else (vols[0] if vols else 0)
        avg_15 = (sum(vols) / len(vols)) * 15 if vols else 0
        return True, int(vol_15), int(first_min), {"avg_15m": avg_15}
    except Exception as e:
        print("compute_vol_15m error", symbol, e)
        return False, 0, 0, {}

def safe_num(x):
    try:
        return float(x)
    except:
        return None

def fmt_us_time():
    """إرجاع الوقت بتوقيت أمريكا"""
    try:
        return datetime.now(US_TZ).strftime("%I:%M:%S %p")
    except:
        return datetime.utcnow().strftime("%H:%M:%S")

def format_alert_ar(symbol, kind, count_today, dp, price, float_shares, market_cap, rel_vol, first_min_vol, dollar_15m):
    """تنسيق التنبيه باللغة العربية"""
    float_txt = f"{int(float_shares):,}" if float_shares else "—"
    market_txt = f"${int(market_cap):,}" if market_cap else "—"
    rel_txt = f"{rel_vol:.2f}X" if rel_vol is not None else "—"
    first_min_txt = f"{first_min_vol:,}" if first_min_vol else "—"
    dollar_txt = f"${int(dollar_15m):,}" if dollar_15m else "—"

    return (
        f"▪️ الرمز: 🇺🇸 {symbol}\n"
        f"▪️ نوع الحركة: {kind}\n"
        f"▪️ عدد مرات التنبيه اليوم: {count_today} مرة\n"
        f"▪️ نسبة الارتفاع: {dp:+.2f}%\n"
        f"▪️ السعر الحالي: {price:.3f} دولار\n"
        f"▪️ عدد الأسهم المتاحة للتداول: {float_txt}\n"
        f"▪️ القيمة السوقية: {market_txt}\n"
        f"▪️ الحجم النسبي: {rel_txt}\n"
        f"▪️ حجم أول دقيقة: {first_min_txt}\n"
        f"▪️ حجم السيولة: {dollar_txt}\n"
        f"🇺🇸 التوقيت الأمريكي: {fmt_us_time()}"
    )

def send_alert(symbol, kind, price, dp, vol_15m, first_min, dollar_15m, float_shares, market_cap, rel_vol):
    """إرسال التنبيه عبر التيليجرام"""
    today = datetime.utcnow().date().isoformat()
    key = f"{symbol}:{today}"
    _daily_counts[key] = _daily_counts.get(key, 0) + 1
    count_today = _daily_counts[key]
    msg = format_alert_ar(symbol, kind, count_today, dp, price, float_shares, market_cap, rel_vol, first_min, dollar_15m)
    try:
        bot.send_message(CHANNEL_ID, msg)
        print(f"[ALERT SENT] {symbol} dp={dp:.2f}% vol15={vol_15m}")
    except Exception as e:
        print("send_alert error", symbol, e)

# ------------------- الحلقة الرئيسية -------------------
def main_loop():
    """الحلقة الرئيسية لمراقبة الأسهم"""
    bot.send_message(CHANNEL_ID, "✅ البوت اشتغل الآن — مراقبة أعلى 50 سهم زخماً (اختبار)")
    symbols = fh_get_symbols_us() or ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT"]
    print(f"Loaded {len(symbols)} symbols.")
    while True:
        start = time.time()
        candidates = []

        sample = random.sample(symbols, 1200) if len(symbols) > 1200 else symbols
        for s in sample:
            try:
                q = fh_quote(s)
                price = safe_num(q.get("c"))
                dp = safe_num(q.get("dp"))
                if price is None or dp is None or price < PRICE_FILTER:
                    continue
                ok, vol_15, first_min, aux = compute_vol_15m(s, price)
                if not ok:
                    continue
                score = (dp or 0) * (vol_15 or 0)
                candidates.append({"symbol": s, "price": price, "dp": dp, "vol_15m": vol_15, "first_min": first_min, "aux": aux, "score": score})
            except Exception as e:
                print("scan error", s, e)

        top = sorted(candidates, key=lambda x: x["score"], reverse=True)[:TOP_N]
        print(f"Top {len(top)} ready...")

        for item in top:
            s = item["symbol"]
            price = item["price"]
            dp = item["dp"]
            vol_15m = item["vol_15m"]
            first_min = item["first_min"]
            aux = item["aux"] or {}
            avg_15m = aux.get("avg_15m") or 0
            dollar_15m = vol_15m * price
            rel_vol = (vol_15m / avg_15m) if avg_15m > 0 else None

            profile = fh_profile(s) or {}
            metrics = fh_metrics(s) or {}
            market_cap = profile.get("marketCapitalization") or (metrics.get("metric") or {}).get("marketCapitalization")
            float_shares = profile.get("shareOutstanding") or profile.get("floatShares") or (metrics.get("shareOutstanding") if isinstance(metrics, dict) else None)

            if dp >= UP_CHANGE_PCT and vol_15m >= MIN_VOL_15M and dollar_15m >= MIN_DOLLAR_15M:
                if time.time() - last_sent.get(s, 0) >= REPEAT_COOLDOWN_S:
                    kind = "اختراق" if dp > 6 else "زخم صعودي"
                    send_alert(s, kind, price, dp, vol_15m, first_min, dollar_15m, float_shares, market_cap, rel_vol)
                    last_sent[s] = time.time()

        sl = max(1, CHECK_INTERVAL_SEC - (time.time() - start))
        print(f"[Cycle end] sleep={sl:.1f}s")
        time.sleep(sl)

# ---------- Flask ----------
app = Flask(__name__)

@app.route("/")
def index():
    return "Auto market alert bot is running ✅"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

# ---------- التشغيل ----------
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("==> Service starting...")
    main_loop()
