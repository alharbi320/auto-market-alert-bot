# -*- coding: utf-8 -*-
import os
import time
import math
import random
import requests
import threading
from datetime import datetime, timedelta
import pytz
import telebot
from flask import Flask

# ========== إعدادات عامة ==========
TOKEN       = os.getenv("BOT_TOKEN", "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU")
CHANNEL_ID  = os.getenv("CHANNEL_ID", "@kaaty320")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "d3udq1hr01qi14apjtb0d3udq1hr01qi14apjtbg")

MARKET_MICS = {"XNAS", "XNYS", "XASE"}  # NASDAQ, NYSE, AMEX
CHECK_INTERVAL_SEC = 60                 # وقت الدورة الرئيسية
UP_CHANGE_PCT = 1.0                     # حد تجريبي: % ارتفاع (ضبط لاحقًا)
MIN_VOL_15M = 10_000                    # حد أدنى لحجم 15 دقيقة (تجريبي)
MIN_DOLLAR_15M = 10_000                 # حد أدنى لقيمة السيولة (تجريبي)
REPEAT_COOLDOWN_S = 60                  # منع التكرار لنفس السهم خلال هذه الثواني
TOP_N = 50                              # نأخذ أقوى 50 سهم حسب score

US_TZ = pytz.timezone("US/Eastern")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
last_sent = {}       # symbol -> last sent timestamp
_daily_counts = {}   # symbol:date -> count

# ------------------- مساعدة Finnhub -------------------
BASE = "https://finnhub.io/api/v1"

def fh_get_symbols_us():
    """جلب رموز US ثم فلترتها حسب MIC."""
    url = f"{BASE}/stock/symbol"
    params = {"exchange": "US", "token": FINNHUB_KEY}
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
        return []

def fh_quote(symbol):
    url = f"{BASE}/quote"
    params = {"symbol": symbol, "token": FINNHUB_KEY}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def fh_candles_1m(symbol, frm, to):
    url = f"{BASE}/stock/candle"
    params = {"symbol": symbol, "resolution": 1, "from": int(frm), "to": int(to), "token": FINNHUB_KEY}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def fh_profile(symbol):
    """يجلب profile2 (ويحتوي غالبًا على marketCapitalization و shareOutstanding)."""
    try:
        url = f"{BASE}/stock/profile2"
        params = {"symbol": symbol, "token": FINNHUB_KEY}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        # لا نوقف التنفيذ لو لم يتوفر
        # print("profile error", symbol, e)
        return {}

def fh_metrics(symbol):
    """محاولة جلب مقاييس إضافية (إذا متاحة)."""
    try:
        url = f"{BASE}/stock/metric"
        params = {"symbol": symbol, "metric": "all", "token": FINNHUB_KEY}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def fh_last_news(symbol, days=3):
    try:
        to_dt = datetime.utcnow().date()
        from_dt = to_dt - timedelta(days=days)
        url = f"{BASE}/company-news"
        params = {"symbol": symbol, "from": str(from_dt), "to": str(to_dt), "token": FINNHUB_KEY}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            data.sort(key=lambda x: x.get("datetime", 0), reverse=True)
            top = data[0]
            h = top.get("headline", "")
            s = top.get("source", "")
            return f"{h} – {s}" if h else "بدون خبر"
        return "بدون خبر"
    except Exception:
        return "بدون خبر"

# ------------------- أدوات التحليل -------------------
def compute_vol_15m(symbol, price):
    """جلب حجومات الدقيقة وتجميع آخر 15 دقيقة. يعيد (ok, vol_15m, first_min_vol, vols_list)"""
    now = int(datetime.utcnow().timestamp())
    frm = now - (60 * 60)  # نأخذ آخر ساعة لنعرف المتوسط أيضاً
    try:
        data = fh_candles_1m(symbol, frm, now)
        if data.get("s") != "ok":
            return False, 0, 0, []
        vols = data.get("v", []) or []
        # نحتاج آخر 15 قيمة دقيقة (قد تكون أقل إن السوق مقفل)
        vol_15m = sum(vols[-15:]) if len(vols) >= 1 else 0
        first_min = vols[-15] if len(vols) >= 15 else (vols[0] if vols else 0)
        # متوسط حجم 15 دقيقة مبني من الـ last 60 minutes -> نحسب متوسط لحجم كل 15-min window
        # تبسيط: استخدم متوسط الحجم لكل دقيقة * 15 كقيمة مرجعية
        avg_minute = (sum(vols) / len(vols)) if vols else 0
        avg_15m = avg_minute * 15
        return True, int(vol_15m), int(first_min), {"vols": vols, "avg_15m": avg_15m}
    except Exception as e:
        print("compute_vol_15m error", symbol, e)
        return False, 0, 0, {}

def safe_num(x):
    try:
        return float(x)
    except:
        return None

def fmt_us_time():
    try:
        return datetime.now(US_TZ).strftime("%I:%M:%S %p")
    except:
        return datetime.utcnow().strftime("%H:%M:%S")

def format_alert_ar(symbol, kind, count_today, dp, price, float_shares, market_cap, rel_vol, first_min_vol, dollar_15m):
    # تنسيق الرسالة بالعربي حسب المثال اللي أعطيتني
    float_txt = f"{int(float_shares):,}" if float_shares and float_shares > 0 else "—"
    market_txt = f"${int(market_cap):,}" if market_cap and market_cap > 0 else "—"
    rel_txt = f"{rel_vol:.2f}X" if rel_vol is not None else "—"
    first_min_txt = f"{first_min_vol:,}" if first_min_vol is not None else "—"
    dollar_txt = f"${int(dollar_15m):,}" if dollar_15m is not None else "—"

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
    today = datetime.utcnow().date().isoformat()
    key = f"{symbol}:{today}"
    _daily_counts[key] = _daily_counts.get(key, 0) + 1
    count_today = _daily_counts[key]
    msg = format_alert_ar(symbol, kind, count_today, dp, price, float_shares, market_cap, rel_vol, first_min, dollar_15m)
    try:
        bot.send_message(CHANNEL_ID, msg)
        print(f"[ALERT SENT] {symbol} dp={dp:.2f}% vol15={vol_15m} market={market_cap} relV={rel_vol}")
    except Exception as e:
        print("send_alert error", symbol, e)

# ------------------- اللوب الرئيسي -------------------
def main_loop():
    # رسالة تجريبية عند الإقلاع لتأكيد الربط
    try:
        bot.send_message(CHANNEL_ID, "✅ البوت اشتغل الآن — مراقبة أعلى 50 سهم زخماً (اختبار)")
    except Exception as e:
        print("startup test message failed:", e)

    # جلب الرموز (مرة كل دورة كاملة طويلة)
    symbols = fh_get_symbols_us()
    if not symbols:
        # fallback صغير
        symbols = ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT"]
    print(f"Loaded {len(symbols)} US symbols to evaluate.")

    while True:
        cycle_start = time.time()
        candidates = []

        # نجمع بيانات سريعة لكل رمز (quote + quick vol_15m) لكن نحد من العدد كي لا نخنق الكوتا
        # لو عدد الرموز كثير نقتصر على عينة عشوائية أو أول N
        sample_symbols = symbols
        if len(symbols) > 1200:
            # خذ عينة عشوائية 1200 لخفض الطلبات
            sample_symbols = random.sample(symbols, 1200)

        for s in sample_symbols:
            try:
                q = fh_quote(s)
                price = safe_num(q.get("c"))
                dp = safe_num(q.get("dp"))  # نسبة التغير اليومي
                if price is None or dp is None:
                    continue
                ok, vol_15m, first_min, aux = compute_vol_15m(s, price)
                if not ok:
                    continue
                # score بسيط: dp * vol_15m (نستبعد الأسهم الصغيرة جداً أو صفرية)
                score = (dp if dp else 0) * (vol_15m if vol_15m else 0)
                candidates.append({
                    "symbol": s,
                    "price": price,
                    "dp": dp,
                    "vol_15m": vol_15m,
                    "first_min": first_min,
                    "aux": aux,
                    "score": score
                })
            except Exception as e:
                # لا نوقف الحلقة بسبب خطأ في سهم
                print("scan error", s, e)

        # ترتيب واختيار TOP_N
        candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
        top_candidates = candidates[:TOP_N]
        print(f"Top candidates picked: {len(top_candidates)} (cycle)")

        # الآن نفحص كل رمز في الـ TOP_N بتفصيل أكبر ونقرر الإرسال
        for item in top_candidates:
            s = item["symbol"]
            price = item["price"]
            dp = item["dp"]
            vol_15m = item["vol_15m"]
            first_min = item["first_min"]
            aux = item["aux"] or {}
            avg_15m = aux.get("avg_15m") or 0
            # حساب قيمة السيولة بالدولار خلال 15 دقيقة
            dollar_15m = vol_15m * price if vol_15m and price else 0

            # حساب relative volume (تقريب سريع)
            rel_vol = None
            try:
                if avg_15m and avg_15m > 0:
                    rel_vol = (vol_15m / avg_15m) if avg_15m else None
            except:
                rel_vol = None

            # جلب profile/metrics للحصول على market cap و float (إن توفّرا)
            profile = fh_profile(s) or {}
            metrics = fh_metrics(s) or {}
            # market cap: حاول من profile أولاً ثم من metrics
            market_cap = profile.get("marketCapitalization") or (metrics.get("metric") or {}).get("marketCapitalization") or None
            # float_shares: بعض الـ APIs تعطي shareOutstanding أو floatShares
            float_shares = profile.get("shareOutstanding") or profile.get("floatShares") or (metrics.get("shareOutstanding") if isinstance(metrics, dict) else None)

            # شرط الفلترة النهائي: زخم كافي و سيولة كافية و نسبة ارتفاع كافية
            if dp >= UP_CHANGE_PCT and vol_15m >= MIN_VOL_15M and dollar_15m >= MIN_DOLLAR_15M:
                # منع التكرار القصير
                last_t = last_sent.get(s, 0)
                if time.time() - last_t >= REPEAT_COOLDOWN_S:
                    # نوع الحركة: إذا اخترق أعلى اليوم (تقريب): نتحقق من high اليوم
                    kind = "زخم صعودي"
                    try:
                        # هنا نستخدم quote.h (اليوم) ونقارن بالسعر السابق لو عندنا
                        # (تبسيط) لو dp>0 نعتبره اختراق/زخم
                        if dp > 2.0:
                            kind = "اختراق"
                    except:
                        pass

                    # إرسال التنبيه
                    send_alert(s, kind, price, dp, vol_15m, first_min, dollar_15m, float_shares, market_cap, rel_vol)
                    last_sent[s] = time.time()
                else:
                    print(f"[SKIP cooldown] {s} recently sent.")
            else:
                # لم يحقق شروط التنبيه؛ نطبع للـ logs لماذا
                print(f"[NO ALERT] {s} dp={dp:.2f}% vol15={vol_15m} dollar15={int(dollar_15m)} (req dp>={UP_CHANGE_PCT}, vol>={MIN_VOL_15M}, $>={MIN_DOLLAR_15M})")

        # انتظار قبل الدورة التالية
        elapsed = time.time() - cycle_start
        sleep_for = max(1.0, CHECK_INTERVAL_SEC - elapsed)
        print(f"[Cycle end] elapsed={elapsed:.1f}s sleeping={sleep_for:.1f}s")
        time.sleep(sleep_for)

# ---------- Flask keep-alive (Render) ----------
app = Flask(__name__)
@app.route("/")
def index():
    return "Auto market alert bot is running ✅"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

# ---------- تشغيل ----------
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("==> Service starting...")
    main_loop()
