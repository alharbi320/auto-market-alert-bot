import os
import requests
import time
import telebot
from datetime import datetime, timedelta
from flask import Flask

# ========= إعدادات البوت =========
BOT_TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHAT_ID = "997530834"
CHECK_INTERVAL = 30  # كل 30 ثانية
DAILY_RISE_PCT = 15  # نسبة التنبيه
API_KEY = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"

bot = telebot.TeleBot(BOT_TOKEN)

# ========= دالة جلب بيانات السهم =========
def get_quote(symbol):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol.upper()}&token={API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        if "c" in data:
            return data
    except Exception as e:
        print(f"Error fetching quote for {symbol}: {e}")
    return None

# ========= دالة جلب آخر خبر عن السهم =========
def get_news(symbol):
    try:
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol.upper()}&from={(datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')}&to={datetime.utcnow().strftime('%Y-%m-%d')}&token={API_KEY}"
        res = requests.get(url)
        news = res.json()
        if news and isinstance(news, list) and len(news) > 0:
            return news[0].get("headline", "لا يوجد خبر حديث.")
        else:
            return "لا يوجد خبر حديث."
    except Exception:
        return "حدث خطأ أثناء جلب الأخبار."

# ========= دالة فحص الارتفاع =========
def check_price(symbol):
    quote = get_quote(symbol)
    if not quote:
        return None
    c = quote["c"]  # السعر الحالي
    pc = quote["pc"]  # سعر الإغلاق السابق
    if pc == 0:
        return None
    change_pct = ((c - pc) / pc) * 100
    return c, pc, change_pct

# ========= أوامر التلغرام =========
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    bot.reply_to(
        message,
        f"👋 أهلاً أنا *auto-market-alert-bot*!\n"
        f"✨ أنبّهك إذا ارتفع السهم ≥ {DAILY_RISE_PCT}% أو انخفض ≤ -10%.\n"
        f"📈 أرسل رمز السهم (مثلاً: AAPL / WGRX)\n"
        f"📰 سأعطيك السعر وآخر خبر إيجابي.\n"
        f"🔁 يتم الفحص كل {CHECK_INTERVAL} ثانية.\n"
        f"⚙️ البوت يعمل تلقائيًا عبر UptimeRobot."
    )

@bot.message_handler(func=lambda m: True, content_types=['text'])
def on_text(message):
    sym = message.text.strip().upper()
    if not sym or len(sym) > 12:
        bot.reply_to(message, "❌ اكتب رمز سهم صحيح (مثلاً: AAPL)")
        return

    quote = get_quote(sym)
    if not quote:
        bot.reply_to(message, "⚠️ لم أستطع جلب بيانات السهم.")
        return

    c = quote["c"]
    pc = quote["pc"]
    change = ((c - pc) / pc) * 100 if pc else 0
    news = get_news(sym)

    msg = (
        f"💹 *رمز السهم:* {sym}\n"
        f"💰 *السعر الحالي:* {c}\n"
        f"📊 *الإغلاق السابق:* {pc}\n"
        f"📈 *التغير:* {change:.2f}%\n\n"
        f"📰 *آخر خبر:* {news}"
    )
    bot.reply_to(message, msg, parse_mode="Markdown")

# ========= فحص دوري تلقائي =========
def auto_check():
    WATCHLIST = ["AAPL", "WGRX", "MGN", "NERV", "RANI", "TPET"]
    while True:
        for sym in WATCHLIST:
            try:
                result = check_price(sym)
                if not result:
                    continue
                c, pc, pct = result
                if pct >= DAILY_RISE_PCT:
                    bot.send_message(
                        CHAT_ID,
                        f"🚀 السهم {sym} ارتفع بنسبة {pct:.2f}% (السعر الحالي: {c})"
                    )
                elif pct <= -10:
                    bot.send_message(
                        CHAT_ID,
                        f"📉 السهم {sym} انخفض بنسبة {pct:.2f}% (السعر الحالي: {c})"
                    )
            except Exception as e:
                print(f"Error in auto_check for {sym}: {e}")
        time.sleep(CHECK_INTERVAL)

# ========= Flask لإبقاء Render حي =========
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is running successfully on Render!"

# ========= تشغيل البوت =========
if __name__ == "__main__":
    import threading
    t = threading.Thread(target=auto_check)
    t.daemon = True
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
