import os
import time
import requests
import telebot
import threading
from datetime import datetime, timedelta
from flask import Flask

# ========== إعدادات البوت ==========
BOT_TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHAT_ID = "997530834"
API_KEY = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"
DAILY_RISE_PCT = 15
CHECK_INTERVAL = 30

bot = telebot.TeleBot(BOT_TOKEN)

# ========== دوال مساعدة ==========
def get_quote(symbol):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol.upper()}&token={API_KEY}"
    try:
        res = requests.get(url)
        data = res.json()
        if "c" in data:
            return data
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
    return None


def get_news(symbol):
    try:
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol.upper()}&from={(datetime.utcnow()-timedelta(days=7)).strftime('%Y-%m-%d')}&to={datetime.utcnow().strftime('%Y-%m-%d')}&token={API_KEY}"
        res = requests.get(url)
        news = res.json()
        if news and isinstance(news, list) and len(news) > 0:
            return news[0].get("headline", "لا يوجد خبر حديث.")
        else:
            return "لا يوجد خبر حديث."
    except:
        return "خطأ في جلب الأخبار."


def check_price(symbol):
    q = get_quote(symbol)
    if not q:
        return None
    c, pc = q["c"], q["pc"]
    if pc == 0:
        return None
    pct = ((c - pc) / pc) * 100
    return c, pc, pct


# ========== أوامر تلغرام ==========
@bot.message_handler(commands=["start", "help"])
def start_message(msg):
    bot.reply_to(
        msg,
        f"👋 أهلاً بك!\n"
        f"سأنبهك إذا ارتفع السهم أكثر من {DAILY_RISE_PCT}% 📈\n"
        f"أرسل رمز السهم مثل (AAPL / WGRX)\n"
        f"ويتم الفحص كل {CHECK_INTERVAL} ثانية 🔁"
    )


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_symbol(msg):
    sym = msg.text.strip().upper()
    q = get_quote(sym)
    if not q:
        bot.reply_to(msg, "⚠️ لم أستطع جلب بيانات السهم.")
        return
    c, pc = q["c"], q["pc"]
    pct = ((c - pc) / pc) * 100 if pc else 0
    news = get_news(sym)
    bot.reply_to(
        msg,
        f"💹 *رمز السهم:* {sym}\n"
        f"💰 *السعر الحالي:* {c}\n"
        f"📊 *الإغلاق السابق:* {pc}\n"
        f"📈 *التغير:* {pct:.2f}%\n\n"
        f"📰 *آخر خبر:* {news}",
        parse_mode="Markdown",
    )


# ========== فحص تلقائي ==========
def auto_check():
    WATCHLIST = ["AAPL", "WGRX", "NERV", "RANI", "TPET"]
    while True:
        for sym in WATCHLIST:
            try:
                result = check_price(sym)
                if not result:
                    continue
                c, pc, pct = result
                if pct >= DAILY_RISE_PCT:
                    bot.send_message(CHAT_ID, f"🚀 {sym} ارتفع {pct:.2f}% (السعر: {c})")
                elif pct <= -10:
                    bot.send_message(CHAT_ID, f"📉 {sym} انخفض {pct:.2f}% (السعر: {c})")
            except Exception as e:
                print(f"Error checking {sym}: {e}")
        time.sleep(CHECK_INTERVAL)


# ========== Flask لإبقاء Render حي ==========
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Auto Market Alert Bot is running!"

# ========== تشغيل البوت ==========
if __name__ == "__main__":
    # تشغيل التحقق التلقائي في Thread
    threading.Thread(target=auto_check, daemon=True).start()
    
    # تشغيل Flask على المنفذ الذي يطلبه Render
    port = int(os.environ.get("PORT", 5000))
    print(f"⚙️ Running Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
