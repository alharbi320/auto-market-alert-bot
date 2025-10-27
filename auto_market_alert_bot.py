# -*- coding: utf-8 -*-
import os, time, json, math, pytz, random, threading, requests
from datetime import datetime, timedelta
import telebot
from flask import Flask

# ========== إعدادات عامة ==========
TOKEN       = os.getenv("BOT_TOKEN", "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU")
CHANNEL_ID  = os.getenv("CHANNEL_ID", "@kaaty320")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "d3udq1hr01qi14apjtb0d3udq1hr01qi14apjtbg")

MARKET_MICS = {"XNAS", "XNYS", "XASE"}  # NASDAQ, NYSE, AMEX
CHECK_INTERVAL_SEC = 60
UP_CHANGE_PCT = 5
MIN_VOL_15M = 100_000
MIN_DOLLAR_15M = 200_000
REPEAT_COOLDOWN_S = 60  # دقيقة للتجربة فقط
US_TZ = pytz.timezone("US/Eastern")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
last_sent = {}
_daily_counts = {}

###############################################################################
#                                  أدوات Finnhub                              #
###############################################################################
def fh_quote(symbol):
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": symbol, "token": FINNHUB_KEY}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def fh_candles_1m(symbol, frm, to):
    url = "https://finnhub.io/api/v1/stock/candle"
    params = {"symbol": symbol, "resolution": 1, "from": int(frm), "to": int(to), "token": FINNHUB_KEY}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def fh_last_news(symbol):
    try:
        to_dt = datetime.utcnow().date()
        from_dt = to_dt - timedelta(days=3)
        url = "https://finnhub.io/api/v1/company-news"
        params = {"symbol": symbol, "from": str(from_dt), "to": str(to_dt), "token": FINNHUB_KEY}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data:
            data.sort(key=lambda x: x.get("datetime", 0), reverse=True)
            h = data[0].get("headline", "")
            s = data[0].get("source", "")
            return f"{h} – {s}" if h else "بدون خبر"
        return "بدون خبر"
    except:
        return "بدون خبر"

###############################################################################
#                                الأدوات الرئيسية                             #
###############################################################################
def has_enough_momentum_and_liquidity(symbol, price, dp):
    if dp is None or dp < UP_CHANGE_PCT or price <= 0:
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
        print(f"[Error] Liquidity {symbol}: {e}")
        return False, 0, 0

def fmt_us_time():
    try:
        return datetime.now(US_TZ).strftime("%I:%M:%S %p")
    except:
        return datetime.utcnow().strftime("%H:%M:%S")

def format_alert(symbol, price, dp, vol_15m, dollar_15m, news_text, count_today):
    return (
        f"🚀 <b>{symbol}</b>\n"
        f"▫️نسبة التغير: <b>{dp:+.2f}%</b>\n"
        f"▫️السعر: <b>{price:.2f}$</b>\n"
        f"▫️حجم 15د: <b>{vol_15m:,}</b>\n"
        f"▫️قيمة: <b>${int(dollar_15m):,}</b>\n"
        f"▫️عدد تنبيهات اليوم: <b>{count_today}</b>\n"
        f"▫️الخبر: {news_text}\n"
        f"⏰ {fmt_us_time()}"
    )

def send_alert(symbol, price, dp, vol_15m, dollar_15m):
    today = datetime.utcnow().date().isoformat()
    key = f"{symbol}:{today}"
    _daily_counts[key] = _daily_counts.get(key, 0) + 1
    news = fh_last_news(symbol)
    msg = format_alert(symbol, price, dp, vol_15m, dollar_15m, news, _daily_counts[key])
    bot.send_message(CHANNEL_ID, msg)
    print(f"[ALERT] Sent {symbol} +{dp:.2f}%")

###############################################################################
#                                الحلقة الرئيسية                              #
###############################################################################
def main_loop():
    test_symbols = ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT"]
    print("بدأ الفحص...")
    bot.send_message(CHANNEL_ID, "✅ البوت يعمل الآن بنجاح (اختبار)")
    while True:
        start = time.time()
        for s in test_symbols:
            try:
                q = fh_quote(s)
                price, dp = q.get("c"), q.get("dp")
                ok, vol, dollar = has_enough_momentum_and_liquidity(s, price, dp)
                if ok:
                    last_t = last_sent.get(s, 0)
                    if time.time() - last_t >= REPEAT_COOLDOWN_S:
                        send_alert(s, price, dp, vol, dollar)
                        last_sent[s] = time.time()
            except Exception as e:
                print(f"[Error] {s}: {e}")
        elapsed = time.time() - start
        sleep_for = max(1, CHECK_INTERVAL_SEC - elapsed)
        print(f"[Cycle] انتهت دورة، النوم {sleep_for:.1f}s")
        time.sleep(sleep_for)

###############################################################################
#                                   Flask                                      #
###############################################################################
app = Flask(__name__)
@app.route("/")
def index():
    return "Bot is running ✅"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("✅ البوت بدأ التشغيل")
    main_loop()
