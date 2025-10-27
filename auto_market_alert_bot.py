import requests
import telebot
import time
from datetime import datetime, date

# ===== إعدادات البوت =====
TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"  # توكن البوت
CHANNEL_ID = "@kaaty320"  # اسم القناة العامة
FINNHUB_API_KEY = "c3ui1a7r01qil4apjtb0c3ui1a7r01qil4apjtbg"  # مفتاح Finnhub API
bot = telebot.TeleBot(TOKEN)

# ===== قاعدة بيانات مؤقتة لتجنب التكرار =====
sent_alerts = {}

# ===== دالة جلب الأسهم ذات الزخم العالي =====
def get_momentum_stocks():
    url = f"https://finnhub.io/api/v1/scan/technical-indicator?symbol=US&resolution=1&token={FINNHUB_API_KEY}"
    trending_url = f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_API_KEY}"
    momentum_symbols = []

    try:
        # محاولة جلب الأسهم النشطة
        movers = requests.get("https://finnhub.io/api/v1/stock/symbol?exchange=US", timeout=10).json()
        for m in movers[:200]:  # نفحص أول 200 سهم فقط لتقليل الضغط
            sym = m.get("symbol")
            if not sym or not sym.isalpha():
                continue

            quote_url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_API_KEY}"
            q = requests.get(quote_url, timeout=10).json()
            change = ((q["c"] - q["pc"]) / q["pc"]) * 100 if q["pc"] else 0

            # زخم قوي = تغير أكثر من ±10%
            if abs(change) >= 10 and q["v"] > 500000:
                momentum_symbols.append((sym, q["c"], change))
    except Exception as e:
        print("⚠️ خطأ أثناء جلب الزخم:", e)
    return momentum_symbols[:20]  # نأخذ فقط أعلى 20 سهم

# ===== تنسيق الرسالة =====
def format_alert(symbol, price, change):
    now = datetime.now().strftime("%H:%M:%S")
    move = "🚀 اختراق قوي" if change > 0 else "📉 هبوط حاد"
    return (
        f"▫️الرمز: {symbol}\n"
        f"▫️نوع الحركة: {move}\n"
        f"▫️نسبة التغير: {change:+.2f}%\n"
        f"▫️السعر الحالي: {price:.2f} دولار\n"
        f"▫️⏰ التوقيت الأمريكي: {now}"
    )

# ===== إرسال التنبيه =====
def send_alert(symbol, price, change):
    msg = format_alert(symbol, price, change)
    bot.send_message(CHANNEL_ID, msg)
    print(f"🚨 تم إرسال تنبيه: {symbol} ({change:+.2f}%)")

# ===== الحلقة الرئيسية =====
while True:
    today = date.today().isoformat()
    if today not in sent_alerts:
        sent_alerts.clear()
        sent_alerts[today] = {}

    print("📊 فحص الأسهم ذات الزخم العالي...")
    momentum_stocks = get_momentum_stocks()

    for sym, price, change in momentum_stocks:
        if sym not in sent_alerts[today]:
            send_alert(sym, price, change)
            sent_alerts[today][sym] = round(change, 1)

    time.sleep(60)  # تحديث كل دقيقة
