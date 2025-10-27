# -*- coding: utf-8 -*-

import os
import time
import json
import math
import pytz
import queue
import signal
import random
import threading
import requests
from datetime import datetime, timedelta
import telebot
from flask import Flask

# ========= الإعدادات العامة =========
# يمكنك لاحقًا نقل هذه القيم إلى Environment Variables على Render
TOKEN       = os.getenv("BOT_TOKEN", "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU")
CHANNEL_ID  = os.getenv("CHANNEL_ID", "@kaaty320")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "d3udq1hr01qi14apjtb0d3udq1hr01qi14apjtbg")

# أسواق التداول المطلوبة
MARKET_MICS = {"XNAS", "XNYS", "XASE"}  # NASDAQ, NYSE, AMEX

# معايير التنبيه
CHECK_INTERVAL_SEC = 60           # كل دقيقة
UP_CHANGE_PCT      = 10.0         # تنبيه عند +10% أو أكثر
MIN_VOL_15M        = 100_000      # حد أدنى لحجم تداول آخر 15 دقيقة
MIN_DOLLAR_15M     = 200_000      # حد أدنى لقيمة التداول بالدولار (سعر * حجم) آخر 15 دقيقة
REPEAT_COOLDOWN_S  = 15 * 60      # منع تكرار التنبيه لنفس السهم لمدة 15 دقيقة

# المنطقة الزمنية للعرض
US_TZ = pytz.timezone("US/Eastern")

# تليجرام بوت
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# لتتبع آخر ما أُرسل
last_sent = {}  # symbol -> timestamp

###############################################################################
#                                  أدوات Finnhub                              #
###############################################################################

def fh_get_symbols_us():
    """جلب جميع رموز الأسهم الأمريكية ثم ترشيحها حسب الماركت ميك (MIC)."""
    url = "https://finnhub.io/api/v1/stock/symbol"
    params = {"exchange": "US", "token": FINNHUB_KEY}
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        # بعض السجلات قد لا تحتوي على mic أو تكون عملات/صناديق.. إلخ
        syms = []
        for x in data:
            mic = (x.get("mic") or "").upper()
            symbol = x.get("symbol")
            # نستبعد الرموز غير القياسية والتي تحتوي نقاط/محارف غير معتادة
            if (mic in MARKET_MICS) and symbol and symbol.isalpha() and len(symbol) <= 5:
                syms.append(symbol)
        # ترتيب لتقليل التذبذب
        syms = sorted(set(syms))
        return syms
    except Exception as e:
        print("fh_get_symbols_us error:", e)
        return []

def fh_quote(symbol):
    """جلب quote لسهم: السعر الحالي، نسبة التغير.. الخ"""
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": symbol, "token": FINNHUB_KEY}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()  # يحتوي dp (نسبة التغير)، c السعر الحالي، h/l/o/pc/d.. الخ

def fh_candles_1m(symbol, frm, to):
    """Campbell (شموع دقيقة) للحصول على حجم التداول خلال نافذة زمنية."""
    url = "https://finnhub.io/api/v1/stock/candle"
    params = {
        "symbol": symbol,
        "resolution": 1,  # 1 دقيقة
        "from": int(frm),
        "to": int(to),
        "token": FINNHUB_KEY
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()  # {s:'ok', t:[], v:[], c:[], ...}

def fh_last_news(symbol, days=3):
    """جلب أحدث خبر للسهم خلال آخر N أيام."""
    to_dt = datetime.utcnow().date()
    from_dt = to_dt - timedelta(days=days)
    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": symbol,
        "from": str(from_dt),
        "to": str(to_dt),
        "token": FINNHUB_KEY
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            # ترتيب تنازليًا بحسب datetime
            data.sort(key=lambda x: x.get("datetime", 0), reverse=True)
            latest = data[0]
            headline = latest.get("headline") or ""
            source = latest.get("source") or ""
            url_ = latest.get("url") or ""
            return f"{headline} – {source}" if headline else "بدون خبر"
        return "بدون خبر"
    except Exception:
        return "بدون خبر"

###############################################################################
#                                 فلترة السهم                                 #
###############################################################################

def has_enough_momentum_and_liquidity(symbol, price, dp):
    """تحقق الزخم والسيولة: ارتفاع + حجم تداول 15 دقيقة كافٍ + قيمة تداول بالدولار."""
    if price is None or price <= 0:
        return False, 0, 0

    if dp is None or dp < UP_CHANGE_PCT:
        return False, 0, 0

    now = int(datetime.utcnow().timestamp())
    frm = now - (15 * 60)
    try:
        candles = fh_candles_1m(symbol, frm, now)
        if candles.get("s") != "ok":
            return False, 0, 0
        vols = candles.get("v", []) or []
        vol_15m = sum(vols)
        dollar_15m = vol_15m * float(price)

        if vol_15m >= MIN_VOL_15M and dollar_15m >= MIN_DOLLAR_15M:
            return True, vol_15m, dollar_15m
        return False, vol_15m, dollar_15m
    except Exception as e:
        print("liquidity check error", symbol, e)
        return False, 0, 0

###############################################################################
#                               تنسيق وإرسال الرسالة                          #
###############################################################################

def fmt_us_time():
    try:
        return datetime.now(US_TZ).strftime("%I:%M:%S %p")
    except Exception:
        return datetime.utcnow().strftime("%H:%M:%S")

def format_alert(symbol, price, dp, vol_15m, dollar_15m, news_text, count_today):
    # ملاحظة: استخدمت نفس الروح التنسيقية التي أعجبتك سابقًا
    return (
        f"▫️الرمز: <b>{symbol}</b>\n"
        f"▫️نوع الزخم: 🚀 زخم شراء (صعود)\n"
        f"▫️نسبة التغير: <b>{dp:+.2f}%</b>\n"
        f"▫️السعر الحالي: <b>{price:.2f}$</b>\n"
        f"▫️حجم 15 دقيقة: <b>{vol_15m:,} سهم</b>\n"
        f"▫️قيمة 15 دقيقة: <b>${int(dollar_15m):,}</b>\n"
        f"▫️عدد مرات التنبيه اليوم: <b>{count_today} مرة</b>\n"
        f"▫️الخبر: {news_text}\n"
        f"▫️⏰ التوقيت الأمريكي: {fmt_us_time()}"
    )

def send_alert(symbol, price, dp, vol_15m, dollar_15m):
    # تتبع عدد مرات التنبيه اليومية
    today = datetime.utcnow().date().isoformat()
    key = f"{symbol}:{today}"
    count_today = _daily_counts.get(key, 0) + 1
    _daily_counts[key] = count_today

    news_text = fh_last_news(symbol, days=3)
    msg = format_alert(symbol, price, dp, vol_15m, dollar_15m, news_text, count_today)
    bot.send_message(CHANNEL_ID, msg)

###############################################################################
#                                  الحلقة الرئيسية                            #
###############################################################################

# حافظ عدد مرات التنبيه اليومية
_daily_counts = {}

def symbols_generator():
    """جلب الرموز مرة واحدة ثم تدويرها في حلقات متتابعة."""
    syms = fh_get_symbols_us()
    if not syms:
        # fallback بسيط
        syms = ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT"]
    print(f"Loaded {len(syms)} symbols.")
    while True:
        random.shuffle(syms)
        for s in syms:
            yield s

def main_loop():
    gen = symbols_generator()
    while True:
        start_ts = time.time()
        checked = 0
        alerts = 0

        # نتحكم بعدد الرموز في كل دقيقة كي لا نستهلك الكوتا
        # مثلاً نفحص 120 رمزا في الدقيقة (يمكنك تعديلها بسهولة)
        per_cycle = 120
        for _ in range(per_cycle):
            symbol = next(gen)
            try:
                q = fh_quote(symbol)
                price = q.get("c") or 0
                dp    = q.get("dp")  # نسبة التغير
                if not price or price <= 0 or dp is None:
                    continue

                ok, vol_15m, dollar_15m = has_enough_momentum_and_liquidity(symbol, price, dp)
                checked += 1

                if ok:
                    # منع التكرار: إذا تم الإرسال قبل أقل من REPEAT_COOLDOWN_S نتجاهل
                    last_t = last_sent.get(symbol, 0)
                    now_t = time.time()
                    if now_t - last_t >= REPEAT_COOLDOWN_S:
                        send_alert(symbol, float(price), float(dp), vol_15m, dollar_15m)
                        last_sent[symbol] = now_t
                        alerts += 1

            except Exception as e:
                # لا نوقف الحلقة بسبب خطأ في سهم
                print("Error on", symbol, "->", e)

        # انتظر حتى يكمل الدقيقة
        elapsed = time.time() - start_ts
        sleep_for = max(1.0, CHECK_INTERVAL_SEC - elapsed)
        print(f"[cycle] checked={checked} alerts={alerts} elapsed={elapsed:.1f}s sleep={sleep_for:.1f}s")
        time.sleep(sleep_for)

###############################################################################
#                               Flask Keep-alive (Render)                      #
###############################################################################

app = Flask(__name__)

@app.route("/")
def index():
    return "Auto market alert bot is running ✅"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    # تشغيل Flask في خيط منفصل
    app.run(host="0.0.0.0", port=port, debug=False)

###############################################################################
#                                    التشغيل                                   #
###############################################################################

if __name__ == "__main__":
    # شغّل خادم الويب (لحفظ الخدمة شغالة في Render)
    threading.Thread(target=run_web, daemon=True).start()

    print("==> Your service is live 🎉")
    print("==> //////////////////////////////////////////////////////////////")
    print("==> Available at your primary URL https://auto-market-alert-bot.onrender.com")
    print("==> //////////////////////////////////////////////////////////////")

    try:
        main_loop()
    except KeyboardInterrupt:
        print("Stopped by user")
