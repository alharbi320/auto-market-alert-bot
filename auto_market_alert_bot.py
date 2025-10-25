# ======================================
# AUTO MARKET ALERT BOT (Render + Flask)
# By: alharbi320
# ======================================

import time
import requests
import telebot
import threading
from flask import Flask

# ===================== TELEGRAM SETTINGS =====================
TELEGRAM_BOT_TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHAT_ID = "997530834"  # حسابك الشخصي
# ============================================================

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# ===================== KEEP ALIVE (Flask) =====================
app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is alive and running!"

def run():
    app.run(host='0.0.0.0', port=8080)

# تشغيل Flask في خيط (Thread) منفصل حتى لا يوقف البوت
threading.Thread(target=run).start()
# ============================================================


# ===================== FUNCTION TO GET NEWS =====================
def get_stock_news(symbol):
    """جلب الأخبار من Yahoo Finance"""
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return f"🔔 آخر الأخبار عن {symbol}: تحقق من موقع Yahoo Finance 📈"
        else:
            return f"⚠️ لم أستطع جلب الأخبار عن {symbol} (رمز الاستجابة: {response.status_code})"
    except Exception as e:
        return f"❌ خطأ أثناء جلب الأخبار: {e}"
# ============================================================


# ===================== BOT COMMANDS =====================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "👋 أهلاً بك في بوت الأخبار!\n"
                          "أرسل لي رمز السهم مثل: `WGRX` لأجلب لك آخر الأخبار 🔍")

@bot.message_handler(func=lambda msg: True)
def stock_handler(message):
    symbol = message.text.strip().upper()
    bot.reply_to(message, f"⏳ جاري جلب الأخبار عن {symbol} ...")
    news = get_stock_news(symbol)
    bot.send_message(message.chat.id, news)
# ============================================================


# ===================== RUN BOT =====================
def run_bot():
    """تشغيل بوت التليجرام مع إعادة المحاولة عند الانقطاع"""
    while True:
        try:
            print("✅ Bot is running...")
            bot.polling(none_stop=True, interval=3)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)

# تشغيل البوت في خيط منفصل (حتى لا يتعارض مع Flask)
threading.Thread(target=run_bot).start()
# ============================================================
