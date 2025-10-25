# ======================================
# AUTO MARKET ALERT BOT (Render + Flask)
# By: alharbi320
# ======================================

import time
import requests
import telebot
import threading
from flask import Flask
import re

# ===================== TELEGRAM SETTINGS =====================
TELEGRAM_BOT_TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHAT_ID = "997530834"  # رقمك الشخصي
# ============================================================

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# ===================== KEEP ALIVE (Flask) =====================
app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is alive and running!"

def run():
    app.run(host='0.0.0.0', port=8080)

# تشغيل Flask في خيط منفصل
threading.Thread(target=run).start()
# ============================================================


# ===================== FUNCTION TO GET NEWS =====================
def get_stock_news(symbol):
    try:
        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        response = requests.get(rss_url, timeout=10)
        if response.status_code == 200 and "<item>" in response.text:
            titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", response.text)
            if len(titles) > 1:
                latest = titles[1]  # أول خبر بعد العنوان العام
                return f"📰 آخر خبر عن {symbol}:\n{latest}\n\n📍المصدر: Yahoo Finance"
            else:
                return f"ℹ️ لم أجد أخبارًا حديثة عن {symbol}."
        else:
            return f"⚠️ لم أستطع جلب الأخبار عن {symbol} (رمز الاستجابة: {response.status_code})"
    except Exception as e:
        return f"❌ خطأ أثناء جلب الأخبار: {e}"
# ============================================================


# ===================== BOT COMMANDS =====================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "👋 أهلاً بك! أرسل رمز السهم مثل: `WGRX` لأجلب لك آخر الأخبار.")

@bot.message_handler(func=lambda msg: True)
def stock_handler(message):
    symbol = message.text.strip().upper()
    bot.reply_to(message, f"⏳ جاري جلب الأخبار عن {symbol} ...")
    news = get_stock_news(symbol)
    bot.send_message(message.chat.id, news)
# ============================================================


# ===================== RUN BOT (With 409 fix) =====================
def run_bot():
    while True:
        try:
            print("✅ Bot is running...")
            bot.polling(none_stop=True, interval=3, timeout=30)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)

threading.Thread(target=run_bot).start()
# ============================================================

