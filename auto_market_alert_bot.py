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

TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHANNEL_ID = "@kaaty320"
FINNHUB_KEY = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"

MARKET_MICS = {"XNAS", "XNYS", "XASE"}  # NASDAQ / NYSE / AMEX
UP_CHANGE_PCT = 20
MIN_PRICE = 1.0
CHECK_INTERVAL_SEC = 60
REPEAT_COOLDOWN_S = 15 * 60
US_TZ = pytz.timezone("US/Eastern")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
last_sent, _daily_counts = {}, {}

# ------------------ Finnhub API ------------------
def fh_get_symbols_us():
    url = "https://finnhub.io/api/v1/stock/symbol"
    try:
        r = requests.get(url, params={"exchange": "US", "token": FINNHUB_KEY}, timeout=25)
        r.raise_for_status()
        data = r.json()
        syms = [x["symbol"] for x in data if (x.get("mic") or "").upper() in MARKET_MICS]
        print(f"[INIT] Loaded {len(syms)} total symbols.")
        return random.sample(syms, 200)
    except Exception as e:
        print("fh_get_symbols_us error:", e)
        return ["AAPL", "TSLA", "NVDA", "AMZN"]

def fh_quote(symbol):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def fh_last_news(symbol):
    to_dt = datetime.now(datetime.UTC).date()
    from_dt = to_dt - timedelta(days=3)
    url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_dt}&to={to_dt}&token={FINNHUB_KEY}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data:
            latest = max(data, key=lambda x: x.get("datetime", 0))
            return latest.get("headline", "بدون خبر")
        return "بدون خبر"
    except Exception:
        return "بدون خبر"

# ------------------ التنبيهات ------------------
def fmt_us_time():
    return datetime.now(US_TZ).strftime("%I:%M:%S %p")

def send_alert(symbol, price, dp):
    today = datetime.utcnow().date().isoformat()
    key = f"{symbol}:{today}"
    _daily_counts[key] = _daily_counts.get(key, 0) + 1
    news_text = fh_last_news(symbol)
    msg = (
        f"🚀 <b>{symbol}</b>\n"
        f"▫️ الارتفاع: <b>{dp:+.2f}%</b>\n"
        f"▫️ السعر: <b>${price:.2f}</b>\n"
        f"▫️ عدد التنبيهات اليوم: {_daily_counts[key]}\n"
        f"▫️ الخبر: {news_text}\n"
        f"⏰ التوقيت الأمريكي: {fmt_us_time()}"
    )
    bot.send_message(CHANNEL_ID, msg)
    print(f"[ALERT] {symbol} +{dp:.2f}%")

# ------------------ الحلقة الرئيسية ------------------
def main_loop():
    print("[SYSTEM] Starting main loop...")
    syms = fh_get_symbols_us()
    bot.send_message(CHANNEL_ID, "🟢 بدأ البوت — مراقبة الأسهم فوق 20% (NASDAQ / NYSE / AMEX)")
    per_cycle = 50

    while True:
        start = time.time()
        random.shuffle(syms)
        checked, alerts = 0, 0

        for s in syms[:per_cycle]:
            try:
                q = fh_quote(s)
                price = q.get("c", 0)
                dp = q.get("dp", None)
                if (dp is None or dp == 0) and q.get("pc", 0) > 0:
                    dp = ((price - q["pc"]) / q["pc"]) * 100
                if dp and dp >= 10:
                    print(f"[DEBUG] {s} → {dp:+.2f}% @ {price:.2f}$")
                if dp and dp >= UP_CHANGE_PCT and price >= MIN_PRICE:
                    last_t = last_sent.get(s, 0)
                    if time.time() - last_t >= REPEAT_COOLDOWN_S:
                        send_alert(s, price, dp)
                        last_sent[s] = time.time()
                        alerts += 1
                checked += 1
            except Exception as e:
                print("Error on", s, ":", e)

        elapsed = time.time() - start
        print(f"[cycle] checked={checked}, alerts={alerts}, took={elapsed:.1f}s")
        time.sleep(max(1, CHECK_INTERVAL_SEC - elapsed))

# ------------------ Flask ------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Auto Market Alert Bot is running ✅"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

# ------------------ التشغيل ------------------
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("==> Flask web started.")
    # ✅ هذا هو السطر اللي يشغّل الحلقة فعلاً
    t = threading.Thread(target=main_loop, daemon=True)
    t.start()
    print("==> Main loop started ✅")
    # نخلي السيرفر يشتغل بلا توقف
    while True:
        time.sleep(60)
