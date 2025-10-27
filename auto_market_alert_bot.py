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
def get_key():
    return random.choice(FINNHUB_KEYS)

MARKET_MICS = {"XNAS", "XNYS", "XASE"}  # NASDAQ, NYSE, AMEX
CHECK_INTERVAL_SEC = 60
UP_CHANGE_PCT      = 20  # ✅ فقط الأسهم فوق +20%
REPEAT_COOLDOWN_S  = 15 * 60
US_TZ = pytz.timezone("US/Eastern")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
last_sent = {}
_daily_counts = {}

###############################################################################
# Finnhub API
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
# التنبيه
###############################################################################

def fmt_us_time():
    return datetime.now(US_TZ).strftime("%I:%M:%S %p")

def send_alert(symbol, price, dp):
    today = datetime.utcnow().date().isoformat()
    key = f"{symbol}:{today}"
    count_today = _daily_counts.get(key, 0) + 1
    _daily_counts[key] = count_today

    news_text = fh_last_news(symbol, days=3)
    msg = (
        f"▪️ الرمز: <b>{symbol}</b>\n"
        f"▪️ نسبة الارتفاع: <b>{dp:+.2f}%</b>\n"
        f"▪️ السعر الحالي: <b>{price:.2f}$</b>\n"
        f"▪️ مرات التنبيه اليوم: {count_today}\n"
        f"▪️ الخبر: {news_text}\n"
        f"⏰ التوقيت الأمريكي: {fmt_us_time()}"
    )
    bot.send_message(CHANNEL_ID, msg)
    print(f"[ALERT] {symbol} +{dp:.2f}% at {price}$")

###############################################################################
# الحلقة الرئيسية
###############################################################################

def main_loop():
    syms = fh_get_symbols_us()
    bot.send_message(CHANNEL_ID, "✅ البوت بدأ — مراقبة الأسهم فوق 20% 📈")
    print(f"Loaded {len(syms)} symbols.")
    per_cycle = 30  # عدد الأسهم التي يتم فحصها في كل دورة لتجنب 429

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
                if dp is None or price <= 0:
                    continue
                if dp >= UP_CHANGE_PCT:
                    last_t = last_sent.get(symbol, 0)
                    now_t = time.time()
                    if now_t - last_t >= REPEAT_COOLDOWN_S:
                        send_alert(symbol, price, dp)
                        last_sent[symbol] = now_t
                        alerts += 1
                checked += 1
            except Exception as e:
                print("Error on", symbol, "->", e)
        elapsed = time.time() - start_ts
        sleep_for = max(1.0, CHECK_INTERVAL_SEC - elapsed)
        print(f"[cycle] checked={checked} alerts={alerts} elapsed={elapsed:.1f}s sleep={sleep_for:.1f}s")
        time.sleep(sleep_for)

###############################################################################
# Flask Keep-alive
###############################################################################

app = Flask(__name__)

@app.route("/")
def index():
    return "Auto market alert bot is running ✅"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

###############################################################################
# التشغيل
###############################################################################

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("==> Service starting...")

    def start_bot():
        try:
            print("✅ بدء تشغيل الحلقة — مراقبة الأسهم فوق 20% 📊")
            main_loop()
        except Exception as e:
            print("❌ خطأ في main_loop:", e)

    threading.Thread(target=start_bot, daemon=True).start()
    while True:
        time.sleep(60)
