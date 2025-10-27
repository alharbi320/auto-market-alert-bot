import requests
import telebot
import time
import threading
from datetime import datetime, timedelta, date
from flask import Flask
import pytz

# =============== الإعدادات ===============
TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"  # توكن البوت
CHANNEL_ID = "@kaaty320"                                   # القناة العامة
FINNHUB_API = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"  # Finnhub API Key

REFRESH_SYMBOLS_EVERY_SEC = 60    # تحديث قائمة الرموز كل دقيقة
CHECK_INTERVAL_SEC = 60           # فحص الزخم كل دقيقة
RSI_PERIOD = 14
VOLUME_MULTIPLIER = 3.0           # حجم اليوم ≥ 3x متوسط آخر 10 أيام
PRICE_UP = 10.0                   # +10% فأكثر
PRICE_DOWN = -10.0                # -10% فأقل

bot = telebot.TeleBot(TOKEN)

# =============== ذاكرة منع التكرار / العد اليومي ===============
# last_state: تحفظ آخر قيم أرسلناها لكل سهم (سعريًا وحجميًا وRSI)
# daily_count: عداد مرات التنبيه اليوم لكل سهم
last_state = {}
daily_count = {}
current_day = date.today().isoformat()

def reset_daily_memories_if_new_day():
    global current_day, daily_count, last_state
    today = date.today().isoformat()
    if today != current_day:
        current_day = today
        daily_count = {}
        # لا نصفر آخر حالة بالكامل؛ نتركها لتقليل التكرار غير الضروري بعد منتصف الليل
        # يمكن تصفيرها أيضًا إن رغبت:
        # last_state = {}

# =============== أدوات مساعدة ===============
def fmt_time_us():
    return datetime.now(pytz.timezone("US/Eastern")).strftime("%I:%M:%S %p")

def fmt_money_short(x: float) -> str:
    try:
        n = float(x)
    except:
        return "0$"
    absn = abs(n)
    if absn >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B$"
    if absn >= 1_000_000:
        return f"{n/1_000_000:.1f}M$"
    if absn >= 1_000:
        return f"{n/1_000:.1f}K$"
    return f"{n:.0f}$"

def inc_daily_count(sym: str) -> int:
    reset_daily_memories_if_new_day()
    daily_count[sym] = daily_count.get(sym, 0) + 1
    return daily_count[sym]

# =============== استعلامات Finnhub ===============
def get_us_symbols(limit=200):
    """
    نجلب رموز السوق الأمريكي من Finnhub.
    لتفادي حدود المعدل، نكتفي بأول ~200 رمز ونحدّث كل دقيقة.
    """
    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_API}"
        res = requests.get(url, timeout=15).json()
        symbols = []
        for it in res:
            sym = it.get("symbol")
            typ = it.get("type", "")
            if not sym:
                continue
            # نختار الأسهم العادية فقط قدر الإمكان
            if "Stock" in typ or typ == "Common Stock" or typ == "EQS":
                symbols.append(sym)
            if len(symbols) >= limit:
                break
        return symbols
    except Exception as e:
        print(f"❌ رموز السوق: {e}")
        return []

def finnhub_quote(symbol: str):
    """Quote: السعر الحالي + التغير % + حجم اليوم + الافتتاح/أعلى/أدنى/الإغلاق السابق"""
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API}"
        r = requests.get(url, timeout=10).json()
        return {
            "c": r.get("c", 0.0),   # current
            "o": r.get("o", 0.0),   # open
            "h": r.get("h", 0.0),   # high
            "l": r.get("l", 0.0),   # low
            "pc": r.get("pc", 0.0), # previous close
            "dp": r.get("dp", 0.0), # change percent
            "t": r.get("t", 0),     # timestamp
        }
    except Exception as e:
        print(f"❌ quote({symbol}): {e}")
        return None

def finnhub_daily_candles(symbol: str, days: int = 15):
    """شمعات يومية (لنستخرج أحجام آخر 10 أيام وحجم اليوم)"""
    try:
        now = int(datetime.utcnow().timestamp())
        frm = now - days * 24 * 3600
        url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution=D&from={frm}&to={now}&token={FINNHUB_API}"
        data = requests.get(url, timeout=15).json()
        if data.get("s") != "ok":
            return None
        return {"v": data.get("v", []), "c": data.get("c", []), "t": data.get("t", [])}
    except Exception as e:
        print(f"❌ candles({symbol}): {e}")
        return None

def finnhub_rsi(symbol: str, period: int = RSI_PERIOD):
    """RSI يومي عبر مؤشر Finnhub"""
    try:
        now = int(datetime.utcnow().timestamp())
        frm = now - 200 * 24 * 3600
        url = (
            f"https://finnhub.io/api/v1/indicator?symbol={symbol}"
            f"&resolution=D&from={frm}&to={now}&indicator=rsi&timeperiod={period}&token={FINNHUB_API}"
        )
        data = requests.get(url, timeout=15).json()
        rsi_list = data.get("rsi", [])
        if not rsi_list:
            return None
        return float(rsi_list[-1])
    except Exception as e:
        print(f"❌ rsi({symbol}): {e}")
        return None

def finnhub_latest_news_str(symbol: str, hours_window: int = 6) -> str:
    """آخر خبر خلال X ساعات؛ وإلا 'بدون خبر'"""
    try:
        now = datetime.utcnow()
        start = (now - timedelta(hours=hours_window)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        url = (
            f"https://finnhub.io/api/v1/company-news?symbol={symbol}"
            f"&from={start}&to={end}&token={FINNHUB_API}"
        )
        data = requests.get(url, timeout=15).json()
        if isinstance(data, list) and len(data) > 0:
            headline = data[0].get("headline")
            if headline:
                return f"📢 الخبر: {headline}"
        return "📢 الخبر: بدون خبر"
    except Exception:
        return "📢 الخبر: بدون خبر"

# =============== صياغة الرسالة ===============
def build_message(symbol: str, tag: str, q: dict, rel_vol: float, liquidity: float, rsi_value):
    """
    tag: 'price_up' | 'price_down' | 'volume_spike' | 'rsi_up' | 'rsi_down'
    """
    if tag == "price_up":
        kind = "🚀 زخم شراء (ارتفاع سعري)"
    elif tag == "price_down":
        kind = "📉 زخم بيع (هبوط سعري)"
    elif tag == "volume_spike":
        kind = "⚡ زخم تداول عالي (حجم)"
    elif tag == "rsi_up":
        kind = "🔥 RSI مرتفع (زخم شراء)"
    elif tag == "rsi_down":
        kind = "❄️ RSI منخفض (زخم بيع)"
    else:
        kind = "📊 زخم"

    now_us = fmt_time_us()
    news_line = finnhub_latest_news_str(symbol)

    # عداد مرات التنبيه اليوم
    count = inc_daily_count(symbol)

    msg = (
        f"▫️الرمز: {symbol}\n"
        f"▫️نوع الزخم: {kind}\n"
        f"▫️نسبة التغير: {q['dp']:+.2f}%\n"
        f"▫️RSI: {f'{rsi_value:.1f}' if (rsi_value is not None) else 'غير متاح'}\n"
        f"▫️السعر الحالي: {q['c']:.2f} دولار\n"
        f"▫️أعلى/أدنى اليوم: {q['h']:.2f} / {q['l']:.2f}\n"
        f"▫️الحجم النسبي: {rel_vol:.1f}x\n"
        f"▫️📊 السيولة: {fmt_money_short(liquidity)}\n"
        f"▫️عدد مرات التنبيه اليوم: {count} مرة\n"
        f"{news_line}\n"
        f"⏰ التوقيت الأمريكي: {now_us}"
    )
    return msg

# =============== منطق التكرار ===============
def should_send(symbol: str, tag: str, value: float) -> bool:
    """
    لمنع تكرار نفس التنبيه.
    tag مثال: 'price', 'volume', 'rsi'
    نعتبر تغييرًا ملحوظًا إذا اختلفت القيمة بمقدار معيّن:
      - للسعر (dp): 0.5%
      - للحجم النسبي: 0.5x
      - للـ RSI: 2 نقاط
    """
    last = last_state.get(symbol, {})
    th = 0.5 if tag in ("price", "volume") else 2.0
    prev = last.get(tag)
    if prev is None or abs(value - prev) >= th:
        last_state.setdefault(symbol, {})[tag] = value
        return True
    return False

# =============== الحلقات الرئيسية ===============
symbols_cache = []

def refresh_symbols_loop():
    global symbols_cache
    while True:
        syms = get_us_symbols(limit=200)
        if syms:
            symbols_cache = syms
            print(f"✅ تم تحديث قائمة الرموز: {len(symbols_cache)} رمز")
        else:
            print("⚠️ لم يتم تحديث الرموز (سيُستخدم الكاش القديم)")
        time.sleep(REFRESH_SYMBOLS_EVERY_SEC)

def monitor_loop():
    while True:
        reset_daily_memories_if_new_day()
        if not symbols_cache:
            time.sleep(5)
            continue

        start_ts = time.time()
        for sym in symbols_cache:
            try:
                q = finnhub_quote(sym)
                if not q:
                    continue

                # شمعات يومية للحجم النسبي والسيولة
                candles = finnhub_daily_candles(sym, days=15)
                rel_vol = 1.0
                liquidity = 0.0
                if candles and len(candles["v"]) >= 11:
                    vols = candles["v"]
                    today_vol = float(vols[-1])
                    last10 = [float(v) for v in vols[-11:-1]]
                    avg10 = (sum(last10) / max(len(last10), 1)) if last10 else 0.0
                    rel_vol = (today_vol / avg10) if avg10 > 0 else 1.0
                    liquidity = (q["c"] or 0.0) * today_vol

                # RSI يومي
                rsi_val = finnhub_rsi(sym, period=RSI_PERIOD)

                # ===== شروط الزخم =====
                dp = float(q["dp"] or 0.0)

                # (أ) زخم سعري
                if dp >= PRICE_UP:
                    if should_send(sym, "price", dp):
                        msg = build_message(sym, "price_up", q, rel_vol, liquidity, rsi_val)
                        bot.send_message(CHANNEL_ID, msg)
                        print(f"PRICE_UP {sym} {dp:+.2f}%")

                elif dp <= PRICE_DOWN:
                    if should_send(sym, "price", dp):
                        msg = build_message(sym, "price_down", q, rel_vol, liquidity, rsi_val)
                        bot.send_message(CHANNEL_ID, msg)
                        print(f"PRICE_DOWN {sym} {dp:+.2f}%")

                # (ب) زخم حجم
                if rel_vol >= VOLUME_MULTIPLIER:
                    if should_send(sym, "volume", rel_vol):
                        msg = build_message(sym, "volume_spike", q, rel_vol, liquidity, rsi_val)
                        bot.send_message(CHANNEL_ID, msg)
                        print(f"VOLUME_SPIKE {sym} x{rel_vol:.1f}")

                # (ج) RSI
                if rsi_val is not None:
                    if rsi_val >= 70:
                        if should_send(sym, "rsi", rsi_val):
                            msg = build_message(sym, "rsi_up", q, rel_vol, liquidity, rsi_val)
                            bot.send_message(CHANNEL_ID, msg)
                            print(f"RSI_UP {sym} {rsi_val:.1f}")
                    elif rsi_val <= 30:
                        if should_send(sym, "rsi", rsi_val):
                            msg = build_message(sym, "rsi_down", q, rel_vol, liquidity, rsi_val)
                            bot.send_message(CHANNEL_ID, msg)
                            print(f"RSI_DOWN {sym} {rsi_val:.1f}")

                # احترام حدود المعدل المجاني
                time.sleep(0.25)

            except Exception as e:
                print(f"[{sym}] Error: {e}")
                time.sleep(0.5)

        # انتظار حتى نكمل دقيقة تقريبًا بين دورات الفحص
        elapsed = time.time() - start_ts
        if elapsed < CHECK_INTERVAL_SEC:
            time.sleep(CHECK_INTERVAL_SEC - elapsed)

# =============== Flask للإبقاء على Render Web Service ===============
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Market Momentum Bot is running (Finnhub + RSI + Volume + News)."

# =============== التشغيل ===============
if __name__ == "__main__":
    print("🚀 بدء تشغيل البوت...")
    threading.Thread(target=refresh_symbols_loop, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
