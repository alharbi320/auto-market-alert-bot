import requests
import telebot
import time
import datetime
import fcntl
import sys

# ========== بيانات الاتصال ==========
BOT_TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHAT_ID = "997530834"
FINNHUB_API = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"

bot = telebot.TeleBot(BOT_TOKEN)

# ========== حماية ضد التشغيل المكرر ==========
lock_file = open("/tmp/telegram_bot.lock", "w")
try:
    fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("✅ Lock acquired, starting bot polling...")
except IOError:
    print("⚠️ Bot instance already running. Exiting to prevent duplicate polling.")
    sys.exit()

# ========== رسالة البداية ==========
@bot.message_handler(commands=['start'])
def start_message(message):
    bot.reply_to(message, 
        "👋 أهلاً أنا auto-market-alert-bot!\n"
        "أتابع الأسهم الأمريكية 🚀.\n"
        "سأبلغك إذا:\n"
        "• ارتفع السهم أكثر من ‎15‎٪ 📈\n"
        "• أو كان عليه زخم لحظي عالي 🔥\n"
        "• أو نُشر خبر إيجابي 📰\n"
        "أرسل رمز السهم (مثل AAPL / TSLA / WGRX) لمعرفة آخر تحديث."
    )

# ========== دالة لجلب بيانات السهم ==========
def get_stock_data(symbol):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API}"
        data = requests.get(url).json()
        return data
    except Exception as e:
        print(f"❌ Error fetching stock data for {symbol}: {e}")
        return None

# ========== دالة لجلب الأخبار ==========
def get_news(symbol):
    try:
        to_date = datetime.datetime.now(datetime.UTC).date()
        from_date = to_date - datetime.timedelta(days=2)
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_date}&to={to_date}&token={FINNHUB_API}"
        news = requests.get(url).json()
        positive = [n for n in news if "up" in n["headline"].lower() or "rise" in n["headline"].lower() or "growth" in n["headline"].lower()]
        return positive[:1]
    except Exception as e:
        print(f"❌ Error fetching news: {e}")
        return []

# ========== فحص وتنبيه ==========
def monitor_stocks():
    watched_symbols = ["AAPL", "TSLA", "WGRX", "SPRC", "DFLI", "SOPA", "RANI", "NERV", "TPET", "MGN"]
    sent_alerts = set()

    while True:
        now = datetime.datetime.now()
        # وقت السوق الأمريكي
        if now.weekday() < 5 and 15 <= now.hour < 22:
            for symbol in watched_symbols:
                data = get_stock_data(symbol)
                if not data or "c" not in data:
                    continue

                change_percent = ((data["c"] - data["pc"]) / data["pc"]) * 100
                if change_percent >= 15 and symbol not in sent_alerts:
                    bot.send_message(CHAT_ID, f"🚀 السهم {symbol} ارتفع بنسبة {change_percent:.2f}% !")
                    sent_alerts.add(symbol)

                # زخم عالي (تغير لحظي سريع)
                if abs(data["d"]) > 3:
                    bot.send_message(CHAT_ID, f"⚡ زخم عالي على {symbol} — التغير الحالي {data['d']}$")

                # خبر إيجابي
                news = get_news(symbol)
                if news:
                    bot.send_message(CHAT_ID, f"📰 آخر خبر إيجابي لـ {symbol}:\n{news[0]['headline']}\n{news[0]['url']}")

        time.sleep(60)  # تحديث كل دقيقة

# ========== تشغيل البوت ==========
import threading
threading.Thread(target=monitor_stocks, daemon=True).start()

bot.infinity_polling(timeout=60, long_polling_timeout=50)
