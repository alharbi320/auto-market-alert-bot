# -*- coding: utf-8 -*-
import os
import time
import random
import threading
import requests
import pytz
from datetime import datetime, timedelta
import telebot
from flask import Flask

# ========= الإعدادات العامة =========
TOKEN       = os.getenv("BOT_TOKEN", "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU")
CHANNEL_ID  = os.getenv("CHANNEL_ID", "@kaaty320")

# مفاتيح Finnhub (يمكنك إضافة أكثر من مفتاح)
FINNHUB_KEYS = [
    "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"
]
# يتم اختيار مفتاح عشوائي في كل دورة لتخفيف الضغط
def get_key():
    return random.choice(FINNHUB_KEYS)

MARKET_MICS = {"XNAS", "XNYS", "XASE"}  # NASDAQ, NYSE, AMEX

CHECK_INTERVAL_SEC = 60      # كل دقيقة
UP_CHANGE_PCT      = 15      # الحد الأدنى للارتفاع
MIN_VOL_15M        = 100_000
MIN_DOLLAR_15M     = 200_000
REPEAT_COOLDOWN_S  = 15 * 60
US_TZ = pytz.timezone("US/Eastern")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
last_sent = {}
_daily_counts = {}

###############################################################################
#                            أدوات الاتصال بـ Finnhub                         #
###############################################################################

def fh_get_symbols_us():
    url = "https://finnhub.io/api/v1/stock/symbol"
    params = {"exchange": "US", "token": get_key()}
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        syms = []
        for x in data:
            mic = (x.get("mic") or "").upper()
            symbol = x.get("symbol")
            if (mic in MARKET_MICS) and symbol and symbol.isalpha() and len(symbol) <= 5:
                syms.append(symbol)
        return sorted(set(syms))
    except Exception as e:
        print("fh_get_symbols_us error:", e)
        return ["AAPL", "TSLA", "NVDA", "AMZN", "MSFT"]

def fh_quote(symbol):
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": symbol, "token": get_key()}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def fh_candles_1m(symbol, frm, to):
    url = "https://finnhub.io/api/v1/stock/candle"
    params = {
        "symbol": symbol,
        "resolution": 1,
        "from": int(frm),
        "to": int(to),
        "token": get_key()
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def fh_last_news(symbol, days=3):
    to_dt = datetime.utcnow().date()
    from_dt = to_dt - timedelta(days=days)
    url = "https://finnhub.io/api/v1/company-news"
    params = {"symbol": symbol, "from": str(from_dt), "to": str(to_dt), "token": get_key()}
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            data.sort(key=lambda x: x.get("datetime", 0), reverse=True)
            latest = data[0]
            headline = latest.get("headline") or ""
            source = latest.get("source") or ""
            if headline:
                return f"{headline} – {source}"
        return "بدون خبر"
    except Exception:
        return "بدون خبر"

###############################################################################
#                           شروط الفلترة والإرسال                             #
###############################################################################

def has_enough_momentum_and_liquidity(symbol, price, dp):
    if price <= 0 or dp < UP_CHANGE_PCT:
        return False, 0, 0
    now = int(datetime.utcnow().timestamp())
    frm = now - (15 * 60)
    try:
        candles = fh_candles_1m(symbol, frm, now)
        if candles.get("s") != "ok":
            return False, 0, 0
        vol_15m = sum(candles.get("v", []))
        dollar_15m = vol_15m * float(price)
        if vol_15m >= MIN_VOL_15M and dollar_15m >= MIN_DOLLAR_15M:
            return True, vol_15m, dollar_15m
        return False, vol_15m, dollar_15m
    except Exception as e:
        print("liquidity check error", symbol, e)
        return False, 0, 0

def fmt_us_time():
    try:
        return datetime.now(US_TZ).strftime("%I:%M:%S %p")
    except:
        return datetime.utcnow().strftime("%H:%M:%S")

def send_alert(symbol, price, dp, vol_15m, dollar_15m):
    today = datetime.utcnow().date().isoformat()
    key = f"{symbol}:{today}"
    count_today = _daily_counts.get(key, 0) + 1
    _daily_counts[key] = count_today
    news_text = fh_last_news(symbol)
    msg = (
        f"▪️ الرمز: <b>{symbol}</b>\n"
        f"▪️ نوع الحركة: 🚀 زخم شراء قوي\n"
        f"▪️ نسبة الارتفاع: <b>{dp:+.2f}%</b>\n"
        f"▪️ السعر الحالي: <b>{price:.2f}$</b>\n"
        f"▪️ حجم آخر 15 دقيقة: <b>{vol_15m:,}</b> سهم\n"
        f"▪️ قيمة التداول: <b>${int(dollar_15m):,}</b>\n"
        f"▪️ مرات التنبيه اليوم: {count_today}\n"
        f"▪️ الخبر: {news_text}\n"
        f"⏰ التوقيت الأمريكي: {fmt_us_time()}"
    )
    bot.send_message(CHANNEL_ID, msg)

###############################################################################
#                            الحلقة الرئيسية                                 #
###############################################################################

def main_loop():
    syms = fh_get_symbols_us()
    bot.send_message(CHANNEL_ID, "✅ البوت بدأ مراقبة أعلى الأسهم زخمًا (الإصدار الخفيف)")
    print(f"Loaded {len(syms)} symbols.")
    per_cycle = 30  # ✅ تخفيف الضغط على API
    while True:
        start_ts = time.time()
        checked = 0
        alerts = 0
        random.shuffle(syms)
        for symbol in syms[:per_cycle]:
            try:
                q = fh_quote(symbol)
                price = q.get("c", 0)
                dp = q.get("dp", 0)
                if not price or dp is None:
                    continue
                ok, vol_15m, dollar_15m = has_enough_momentum_and_liquidity(symbol, price, dp)
                checked += 1
                if ok:
                    last_t = last_sent.get(symbol, 0)
                    now_t = time.time()
                    if now_t - last_t >= REPEAT_COOLDOWN_S:
                        send_alert(symbol, price, dp, vol_15m, dollar_15m)
                        last_sent[symbol] = now_t
                        alerts += 1
            except Exception as e:
                print("Error on", symbol, "->", e)
        elapsed = time.time() - start_ts
        sleep_for = max(1.0, CHECK_INTERVAL_SEC - elapsed)
        print(f"[cycle] checked={checked} alerts={alerts} elapsed={elapsed:.1f}s sleep={sleep_for:.1f}s")
        time.sleep(sleep_for)

###############################################################################
#                              Flask للحفاظ على التشغيل                       #
###############################################################################

app = Flask(__name__)

@app.route("/")
def index():
    return "Auto market alert bot is running ✅"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

###############################################################################
#                                التشغيل الفعلي                               #
###############################################################################

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("==> Service starting...")

    def start_bot():
        try:
            print("✅ بدء تشغيل الحلقة الرئيسية (نسخة خفيفة)...")
            main_loop()
        except Exception as e:
            print("❌ خطأ في main_loop:", e)

    threading.Thread(target=start_bot, daemon=True).start()

    while True:
        time.sleep(60)
