# auto-market-alert-bot.py
import os, time, json, threading, requests, math
from datetime import datetime, timedelta
import pytz
import telebot
from http.server import BaseHTTPRequestHandler, HTTPServer

# ========= إعدادات البوت =========
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU")
CHAT_ID          = os.getenv("CHAT_ID", "997530834")
FINNHUB_API      = os.getenv("FINNHUB_API", "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg")

INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "10"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "50"))
DAILY_RISE_PCT    = float(os.getenv("DAILY_RISE_PCT", "15"))
MOMO_PRICE_5M_PCT = float(os.getenv("MOMO_PRICE_5M_PCT", "5"))
MOMO_VOL_SPIKE_FACTOR = float(os.getenv("MOMO_VOL_SPIKE_FACTOR", "2"))
STATE_FILE = os.getenv("STATE_FILE", "auto_stock_state.json")
TZ_NY = pytz.timezone("America/New_York")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")
LOCK = threading.Lock()

STATE = {
    "symbols_queue": [],
    "alerted_day": {},
    "alerted_momo": {},
    "symbols_loaded_for_date": ""
}

# ========= أدوات مساعدة =========
def ny_now():
    return datetime.now(TZ_NY)

def today_key_ny():
    return ny_now().strftime("%Y-%m-%d")

def http_get(url, params=None, timeout=12):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                STATE.update(json.load(f))
        except Exception:
            pass

def save_state():
    with LOCK:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE, f, ensure_ascii=False, indent=2)

load_state()

def finnhub_symbols_us():
    url = "https://finnhub.io/api/v1/stock/symbol"
    data = http_get(url, {"exchange": "US", "token": FINNHUB_API})
    if not data:
        return []
    syms = []
    for item in data:
        sym = item.get("symbol", "")
        t = item.get("type", "")
        if not sym:
            continue
        if "ETF" in t.upper() or "-" in sym or "." in sym:
            continue
        syms.append(sym)
    return syms

def ensure_symbols_loaded_daily():
    dkey = today_key_ny()
    if STATE.get("symbols_loaded_for_date") == dkey and STATE["symbols_queue"]:
        return
    syms = finnhub_symbols_us()
    if syms:
        with LOCK:
            STATE["symbols_queue"] = syms
            STATE["symbols_loaded_for_date"] = dkey
            save_state()

def get_quote(symbol):
    return http_get("https://finnhub.io/api/v1/quote", {"symbol": symbol, "token": FINNHUB_API})

def get_stock_candles_1m(symbol, frm_ts, to_ts):
    return http_get("https://finnhub.io/api/v1/stock/candle", {
        "symbol": symbol, "resolution": "1", "from": frm_ts, "to": to_ts, "token": FINNHUB_API
    })

def get_company_news(symbol, days_back=3):
    to_date = datetime.utcnow().date()
    from_date = to_date - timedelta(days=days_back)
    data = http_get("https://finnhub.io/api/v1/company-news", {
        "symbol": symbol, "from": from_date.strftime("%Y-%m-%d"),
        "to": to_date.strftime("%Y-%m-%d"), "token": FINNHUB_API
    })
    return data or []

def get_news_sentiment(symbol):
    return http_get("https://finnhub.io/api/v1/news-sentiment", {"symbol": symbol, "token": FINNHUB_API}) or {}

def fmt_price(p):
    try:
        return f"{p:.4f}" if p < 1 else f"{p:.2f}"
    except:
        return str(p)

def summarize_positive_news(symbol):
    senti = get_news_sentiment(symbol)
    score = senti.get("sentiment", {}).get("companyNewsScore", None)
    items = get_company_news(symbol)
    text = ""
    if score is not None and score >= 0.55:
        text += f"\n🟢 *مزاج الأخبار إيجابي* (Score: {score:.2f})"
    if items:
        last = sorted(items, key=lambda x: x.get("datetime", 0))[-1]
        dt = datetime.utcfromtimestamp(last.get("datetime", 0)).strftime("%Y-%m-%d %H:%M UTC")
        text += f"\n📰 *{last.get('headline','بدون عنوان')}*\nالمصدر: {last.get('source','—')}\nالتاريخ: {dt}\nالرابط: {last.get('url','')}"
    return text.strip()

def mark_alert_once(bucket, symbol):
    d = today_key_ny()
    with LOCK:
        daymap = STATE.get(bucket, {}).get(d, {})
        if daymap.get(symbol): return False
        daymap[symbol] = True
        STATE.setdefault(bucket, {})[d] = daymap
        save_state()
    return True

def already_alerted(bucket, symbol):
    d = today_key_ny()
    return STATE.get(bucket, {}).get(d, {}).get(symbol, False)

# ========= منطق التنبيهات =========
def check_daily_15pct(symbol, q):
    c, pc = q.get("c", 0), q.get("pc", 0)
    if not pc or pc <= 0: return
    pct = (c - pc) / pc * 100
    if pct >= DAILY_RISE_PCT and not already_alerted("alerted_day", symbol):
        if mark_alert_once("alerted_day", symbol):
            msg = f"🚀 *{symbol}* ارتفع *{pct:.2f}%* اليوم\nالسعر الحالي: {fmt_price(c)} | الإغلاق السابق: {fmt_price(pc)}"
            news = summarize_positive_news(symbol)
            if news: msg += "\n\n" + news
            bot.send_message(CHAT_ID, msg)

def deep_momo_check(symbol):
    now = int(time.time())
    frm = now - 15*60
    data = get_stock_candles_1m(symbol, frm, now)
    if not data or data.get("s") != "ok": return False, None
    c, v = data.get("c", []), data.get("v", [])
    if len(c) < 6 or len(v) < 12: return False, None
    base, last = c[-6], c[-1]
    price_5m = (last - base) / base * 100 if base > 0 else 0
    avg10 = sum(v[-12:-2]) / 10 if len(v) >= 12 else 0
    vol_spike = v[-1] / avg10 if avg10 > 0 else 0
    if price_5m >= MOMO_PRICE_5M_PCT and vol_spike >= MOMO_VOL_SPIKE_FACTOR:
        return True, {"price_5m_pct": price_5m, "vol_spike": vol_spike, "last": last}
    return False, None

def process_symbol(symbol):
    q = get_quote(symbol)
    if not q: return
    check_daily_15pct(symbol, q)
    if already_alerted("alerted_momo", symbol): return
    ok, info = deep_momo_check(symbol)
    if ok and mark_alert_once("alerted_momo", symbol):
        msg = (
            f"⚡ *{symbol}* زخم لحظي قوي\n"
            f"قفزة 5د: *{info['price_5m_pct']:.2f}%* | سبايك فوليوم: *{info['vol_spike']:.2f}x*\n"
            f"السعر الآن: {fmt_price(info['last'])}"
        )
        news = summarize_positive_news(symbol)
        if news: msg += "\n\n" + news
        bot.send_message(CHAT_ID, msg)

# ========= حلقة المراقبة =========
def scanner_loop():
    while True:
        try:
            now_ny = ny_now()
            weekday = now_ny.weekday()  # Monday=0 ... Sunday=6
            # عطلة نهاية الأسبوع
            if weekday >= 5:
                print(f"⏸️ السوق مغلق ({now_ny.strftime('%A')})، النوم 6 ساعات...")
                time.sleep(6 * 3600)
                continue

            ensure_symbols_loaded_daily()
            cycles_per_min = max(1, math.floor(60 / INTERVAL_SECONDS))
            per_cycle = max(1, RATE_LIMIT_PER_MIN // cycles_per_min)

            if not STATE["symbols_queue"]:
                time.sleep(INTERVAL_SECONDS)
                continue

            batch = []
            with LOCK:
                for _ in range(min(per_cycle, len(STATE["symbols_queue"]))):
                    s = STATE["symbols_queue"].pop(0)
                    batch.append(s)
                    STATE["symbols_queue"].append(s)

            for sym in batch:
                try:
                    process_symbol(sym)
                except Exception:
                    pass

            save_state()
            time.sleep(INTERVAL_SECONDS)
        except Exception:
            time.sleep(INTERVAL_SECONDS)

# ========= أوامر التلغرام =========
@bot.message_handler(commands=["start","help"])
def cmd_start(message):
    bot.reply_to(message,
        "👋 أهلاً! أنا *auto-market-alert-bot* (Stocks Only)\n"
        f"• تنبيه إذا ارتفع السهم ≥ *{DAILY_RISE_PCT:.0f}%* خلال اليوم\n"
        f"• تنبيه الزخم اللحظي (قفزة ≥{MOMO_PRICE_5M_PCT:.0f}% بفوليوم ≥{MOMO_VOL_SPIKE_FACTOR:.1f}x)\n"
        "• أرسل رمز السهم (مثل: AAPL / WGRX) للحصول على السعر + آخر خبر إيجابي.\n"
        "• يتوقف تلقائيًا السبت والأحد.\n"
        "• مدعوم بالـ Ping من UptimeRobot لإبقائه شغال دائمًا 🔁"
    )

@bot.message_handler(func=lambda m: True, content_types=['text'])
def on_text(message):
    sym = message.text.strip().upper()
    if not sym or len(sym) > 12:
        bot.reply_to(message, "اكتب رمز سهم صحيح (مثال: AAPL)")
        return
    q = get_quote(sym)
    lines = []
    if q:
        c, pc = q.get("c", 0.0), q.get("pc", 0.0)
        pct = ((c - pc)/pc*100.0) if pc else 0.0
        lines.append(f"📊 *{sym}* السعر: {fmt_price(c)} | التغير اليومي: *{pct:.2f}%*")
    else:
        lines.append(f"📊 *{sym}* — تعذر جلب السعر.")
    news = summarize_positive_news(sym)
    if news:
        lines.append("\n" + news)
    bot.reply_to(message, "\n".join(lines))

# ========= التشغيل الرئيسي =========
def start_threads():
    t = threading.Thread(target=scanner_loop, daemon=True)
    t.start()

if __name__ == "__main__":
    print("✅ auto-market-alert-bot running (stocks only)…")
    start_threads()

    # 🌐 خادم صغير لإبقاء الخدمة نشطة في Render (UptimeRobot)
    class PingHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Bot is alive!")

    def run_server():
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(("", port), PingHandler)
        print(f"🌐 Web ping server running on port {port}")
        server.serve_forever()

    threading.Thread(target=run_server, daemon=True).start()
    bot.infinity_polling(timeout=60, long_polling_timeout=50)
