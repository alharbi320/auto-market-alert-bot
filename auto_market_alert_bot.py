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

# ========== إعدادات عامة ==========
TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHANNEL_ID = "@kaaty320"
FINNHUB_KEY = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"

MARKET_MICS = {"XNAS", "XNYS", "XASE"}  # NASDAQ, NYSE, AMEX
CHECK_INTERVAL_SEC = 60
UP_CHANGE_PCT = 20
MIN_PRICE = 1.00
REPEAT_COOLDOWN_S = 15 * 60  # 15 دقيقة
US_TZ = pytz.timezone("US/Eastern")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
last_sent = {}
_daily_counts = {}

# ========== أدوات API من Finnhub ==========
def fh_get_symbols_us():
    """جلب رموز الأسهم الأمريكية من الأسواق المطلوبة فقط"""
    url = "https://finnhub.io/api/v1/stock/symbol"
    params = {"exchange": "US", "token": FINNHUB_KEY}
    try:
        r = requests.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        syms = [x["symbol"] for x in data if (x.get("mic") or "").upper() in MARKET_MICS]
        return sorted(set(syms))
    except Exception as e:
        print("fh_get_symbols_us error:", e)
        return ["AAPL", "TSLA", "NVDA", "AMZN"]

def fh_quote(symbol):
    """جلب السعر الحالي والنسبة + دعم الـ pre/after hours"""
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def fh_last_news(symbol):
    """آخر خبر خلال 3 أيام"""
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

# ========== إرسال التنبيه ==========
def fmt_us_time():
    return datetime.now(US_TZ).strftime("%I:%M:%S %p")

def send_alert(symbol, price, dp):
    today = datetime.utcnow().date().isoformat()
    key = f"{symbol}:{today}"
    _daily_counts[key] = _daily_counts.get(key, 0) + 1

    news_text = fh_last_news(symbol)
    msg = (
        f"▪️ الرمز: <b>{symbol}</b>\n"
        f"▪️ نسبة الارتفاع: <b>{dp:+.2f}%</b>\n"
        f"▪️ السعر الحالي: <b>${price:.2f}</b>\n"
        f"▪️ عدد مرات التنبيه اليوم: <b>{_daily_counts[key]}</b>\n"
        f"▪️ الخبر: {news_text}\n"
        f"⏰ التوقيت الأمريكي: {fmt_us_time()}"
    )
    bot.send_message(CHANNEL_ID, msg)
    print(f"[ALERT] {symbol} +{dp:.1f}%")

# ========== الحلقة الرئيسية ==========
def main_loop():
    syms = fh_get_symbols_us()
    bot.send_message(CHANNEL_ID, "✅ بدأ البوت — مراقبة أسهم NASDAQ/NYSE/AMEX (+20%) تشمل Pre & After Hours 📊")
    per_cycle = 100  # عدد الأسهم في كل دورة

    while True:
        start = time.time()
        random.shuffle(syms)
        checked, alerts = 0, 0

        for s in syms[:per_cycle]:
            try:
                q = fh_quote(s)
                price = q.get("c", 0)
                dp = q.get("dp", 0)

                # حساب pre/after hours إذا كان الفرق أكبر
                if "pc" in q and q["pc"] > 0 and price > 0:
                    ext_dp = ((price - q["pc"]) / q["pc"]) * 100
                    if abs(ext_dp) > abs(dp):
                        dp = ext_dp

                if price >= MIN_PRICE and dp >= UP_CHANGE_PCT:
                    last_t = last_sent.get(s, 0)
                    if time.time() - last_t >= REPEAT_COOLDOWN_S:
                        send_alert(s, price, dp)
                        last_sent[s] = time.time()
                        alerts += 1
                checked += 1
            except Exception as e:
                print("Error on", s, ":", e)

        elapsed = time.time() - start
        print(f"[cycle] checked={checked} alerts={alerts} time={elapsed:.1f}s sleep={CHECK_INTERVAL_SEC - elapsed:.1f}s")
        time.sleep(max(1, CHECK_INTERVAL_SEC - elapsed))

# ========== Flask Keep-alive ==========
app = Flask(__name__)

@app.route("/")
def index():
    return "Auto Market Alert Bot is Running ✅"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("==> Service Starting...")
    main_loop()
