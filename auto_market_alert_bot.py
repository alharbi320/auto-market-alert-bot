import requests, time, threading
from datetime import datetime, timedelta, date
import pytz
import telebot
from flask import Flask

# ========== إعدادات البوت ==========
TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHANNEL_ID = "@kaaty320"
FINNHUB_API = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"
bot = telebot.TeleBot(TOKEN)

# ========= الإعدادات العامة =========
MARKETS = ["NASDAQ", "NYSE", "AMEX"]
CHECK_INTERVAL = 60         # كل دقيقة
UP_CHANGE = 10.0            # ارتفاع 10% أو أكثر
VOLUME_MULT = 1.5           # حجم اليوم ≥ 1.5× المتوسط
RSI_PERIOD = 14

last_sent = {}
daily_count = {}
today_str = date.today().isoformat()

# ========= أدوات مساعدة =========
def reset_day():
    global today_str, daily_count
    now = date.today().isoformat()
    if now != today_str:
        today_str = now
        daily_count = {}

def fmt_time_us():
    return datetime.now(pytz.timezone("US/Eastern")).strftime("%I:%M:%S %p")

def fmt_money(n):
    try:
        n = float(n)
    except: return "0$"
    if n >= 1e9:  return f"{n/1e9:.1f}B$"
    if n >= 1e6:  return f"{n/1e6:.1f}M$"
    if n >= 1e3:  return f"{n/1e3:.1f}K$"
    return f"{n:.0f}$"

# ========= دوال جلب البيانات =========
def get_symbols():
    symbols = []
    for exch in MARKETS:
        try:
            url = f"https://finnhub.io/api/v1/stock/symbol?exchange={exch}&token={FINNHUB_API}"
            res = requests.get(url, timeout=15).json()
            for x in res:
                sym = x.get("symbol")
                if sym and sym.isalpha():
                    symbols.append(sym)
            time.sleep(1)
        except: pass
    print(f"✅ جلبنا {len(symbols)} رمز من الأسواق المحددة.")
    return symbols[:200]  # أول 200 فقط لتجنب تجاوز الحد المجاني

def get_quote(sym):
    try:
        r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_API}", timeout=10).json()
        return {"price": r["c"], "prev": r["pc"], "dp": r["dp"], "vol": r["v"]}
    except: return None

def get_candles(sym):
    try:
        now = int(datetime.utcnow().timestamp())
        frm = now - 15 * 24 * 3600
        url = f"https://finnhub.io/api/v1/stock/candle?symbol={sym}&resolution=D&from={frm}&to={now}&token={FINNHUB_API}"
        j = requests.get(url, timeout=10).json()
        if j.get("s") == "ok": return j
    except: pass
    return None

def get_rsi(sym):
    try:
        now = int(datetime.utcnow().timestamp())
        frm = now - 200 * 24 * 3600
        url = f"https://finnhub.io/api/v1/indicator?symbol={sym}&resolution=D&from={frm}&to={now}&indicator=rsi&timeperiod={RSI_PERIOD}&token={FINNHUB_API}"
        j = requests.get(url, timeout=10).json()
        if "rsi" in j and j["rsi"]: return j["rsi"][-1]
    except: pass
    return None

def get_news(sym):
    try:
        now = datetime.utcnow()
        start = (now - timedelta(hours=6)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={start}&to={end}&token={FINNHUB_API}"
        j = requests.get(url, timeout=10).json()
        if isinstance(j, list) and j:
            return f"📢 الخبر: {j[0].get('headline')}"
    except: pass
    return "📢 الخبر: بدون خبر"

# ========= صياغة الرسالة =========
def build_msg(sym, dp, price, rel_vol, liquidity, rsi_val, news):
    reset_day()
    daily_count[sym] = daily_count.get(sym, 0) + 1
    msg = (
        f"▫️الرمز: {sym}\n"
        f"▫️نوع الزخم: 🚀 زخم شراء قوي\n"
        f"▫️نسبة الارتفاع: +{dp:.2f}%\n"
        f"▫️RSI: {rsi_val:.1f}\n"
        f"▫️السعر الحالي: {price:.2f} دولار\n"
        f"▫️الحجم النسبي: {rel_vol:.2f}x\n"
        f"▫️📊 السيولة: {fmt_money(liquidity)}\n"
        f"▫️عدد مرات التنبيه اليوم: {daily_count[sym]} مرة\n"
        f"{news}\n"
        f"⏰ التوقيت الأمريكي: {fmt_time_us()}"
    )
    return msg

# ========= الفحص الرئيسي =========
symbols_cache = []

def refresh_symbols():
    global symbols_cache
    while True:
        symbols_cache = get_symbols()
        time.sleep(600)  # كل 10 دقائق يحدث القائمة

def monitor_loop():
    while True:
        if not symbols_cache:
            time.sleep(5); continue
        for sym in symbols_cache:
            try:
                q = get_quote(sym)
                if not q or q["dp"] < UP_CHANGE: continue  # فقط الزخم الصاعد
                candles = get_candles(sym)
                rel_vol, liquidity = 1.0, 0.0
                if candles and len(candles.get("v", [])) >= 11:
                    vols = candles["v"]
                    avg10 = sum(vols[-11:-1]) / 10
                    today_vol = vols[-1]
                    rel_vol = today_vol / avg10 if avg10 > 0 else 1
                    liquidity = today_vol * q["price"]
                if rel_vol < VOLUME_MULT: continue  # لازم حجم كبير
                rsi_val = get_rsi(sym)
                if not rsi_val or rsi_val < 60: continue  # تأكيد زخم شراء
                news = get_news(sym)
                msg = build_msg(sym, q["dp"], q["price"], rel_vol, liquidity, rsi_val, news)
                key = f"{sym}:{int(q['dp'])}"
                if key not in last_sent:
                    bot.send_message(CHANNEL_ID, msg)
                    last_sent[key] = True
                    print(f"🚀 {sym} +{q['dp']:.2f}% RSI {rsi_val:.1f}")
                time.sleep(0.3)
            except Exception as e:
                print(f"[{sym}] Error: {e}")
        time.sleep(CHECK_INTERVAL)

# ========= Flask للإبقاء على الخدمة =========
app = Flask(__name__)
@app.route("/")
def home():
    return "✅ Momentum Bot running (NASDAQ/NYSE/AMEX only)."

# ========= التشغيل =========
if __name__ == "__main__":
    print("🚀 بدء تشغيل البوت (زخم صاعد فقط من NASDAQ/NYSE/AMEX)")
    threading.Thread(target=refresh_symbols, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
