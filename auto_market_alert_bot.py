import finnhub
import time
import telebot
from datetime import datetime
import pytz
import threading

# 🔑 مفاتيح التشغيل
FINNHUB_API_KEY = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"
TELEGRAM_BOT_TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHAT_ID = 997530834  # رقمك في التليجرام

# إنشاء الاتصال مع Finnhub و Telegram
finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# تخزين التنبيهات السابقة
alerted_stocks = set()
alerted_crypto = set()
price_history = {}

# توقيت نيويورك
ny_tz = pytz.timezone("America/New_York")

# 🕒 تحديد أوقات السوق الأمريكي (من الاثنين إلى الجمعة فقط)
def in_market_hours():
    now_ny = datetime.now(ny_tz)
    weekday = now_ny.weekday()  # الإثنين=0 / الأحد=6
    total_minutes = now_ny.hour * 60 + now_ny.minute

    # السوق مفتوح فقط من الاثنين إلى الجمعة
    if weekday >= 5:  # السبت=5 والأحد=6
        return False

    # من 3AM إلى 8PM بتوقيت نيويورك (11 صباحًا → 4 فجرًا بتوقيت السعودية)
    return 3 * 60 <= total_minutes <= 20 * 60

# 📈 فحص الأسهم الأمريكية
def check_stocks():
    stocks = finnhub_client.stock_symbols('US')
    print(f"📊 فحص {len(stocks)} سهم أمريكي...")
    for stock in stocks:
        symbol = stock['symbol']
        try:
            quote = finnhub_client.quote(symbol)
            pc = quote['pc']
            c = quote['c']
            if pc and c and pc > 0:
                change = ((c - pc) / pc) * 100
                if change >= 15 and symbol not in alerted_stocks:
                    alerted_stocks.add(symbol)
                    msg = f"🚀 *تنبيه سهم!* `{symbol}` ارتفع {change:.2f}% 📈"
                    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                    print(msg)
        except Exception as e:
            print("❌ خطأ في السهم:", e)
            continue

# 💰 فحص العملات الرقمية (كل العملات من Binance)
def check_crypto():
    global price_history
    try:
        crypto_pairs = [c["symbol"] for c in finnhub_client.crypto_symbols('BINANCE')]
    except Exception as e:
        print("⚠️ فشل تحميل أزواج العملات:", e)
        return

    print(f"💰 فحص {len(crypto_pairs)} عملة رقمية...")
    for pair in crypto_pairs:
        try:
            quote = finnhub_client.crypto_quote(f"BINANCE:{pair}")
            price = quote.get("c", 0)
            if not price or price == 0:
                continue

            # حفظ آخر 5 دقائق لكل عملة
            if pair not in price_history:
                price_history[pair] = []
            price_history[pair].append(price)
            if len(price_history[pair]) > 5:
                price_history[pair].pop(0)

            # حساب التغير خلال آخر 5 دقائق
            if len(price_history[pair]) >= 2:
                first = price_history[pair][0]
                last = price_history[pair][-1]
                change = ((last - first) / first) * 100
                if change >= 15 and pair not in alerted_crypto:
                    alerted_crypto.add(pair)
                    msg = f"💎 *تنبيه عملة!* `{pair}` ارتفعت {change:.2f}% خلال آخر 5 دقائق 🔥"
                    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                    print(msg)
        except:
            continue

# 🚀 الحلقة الرئيسية للتنبيهات
def auto_monitor():
    market_open_alert = False
    market_close_alert = False

    while True:
        now = datetime.now(ny_tz).strftime("%Y-%m-%d %H:%M:%S")
        print(f"⏰ فحص عند: {now}")

        # ✅ فحص الأسهم أثناء السوق فقط (الإثنين - الجمعة)
        if in_market_hours():
            if not market_open_alert:
                bot.send_message(CHAT_ID, "📈 السوق الأمريكي مفتوح ✅", parse_mode="Markdown")
                market_open_alert = True
                market_close_alert = False
            check_stocks()
        else:
            # رسالة إغلاق السوق لمرة واحدة فقط
            if not market_close_alert:
                bot.send_message(CHAT_ID, "😴 السوق الأمريكي مغلق الآن 🕓", parse_mode="Markdown")
                market_close_alert = True
                market_open_alert = False

        # 💰 فحص العملات الرقمية (دائمًا)
        check_crypto()

        # انتظار دقيقة واحدة
        time.sleep(60)

# تشغيل المهمة في Thread منفصل
threading.Thread(target=auto_monitor, daemon=True).start()

print("🤖 البوت يعمل تلقائيًا الآن...")
print("📈 الأسهم الأمريكية: الإثنين → الجمعة (11 صباحًا - 4 فجرًا 🇸🇦)")
print("💰 العملات الرقمية: 24 ساعة / 7 أيام 🔁")

bot.polling()
