import requests
import telebot
import time
from datetime import datetime

# إعدادات البوت
TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHANNEL_ID = "@kaaty320"  # اسم القناة
bot = telebot.TeleBot(TOKEN)

# قائمة الأسهم (يمكنك تعديلها أو توسيعها)
SYMBOLS = ["WGRX", "RANI", "CASI", "SPRC", "ONMD", "DFLI", "SOPA", "NERV"]

# قاعدة بيانات مؤقتة لتجنب التكرار
sent_alerts = {}

def get_stock_data(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m"
    try:
        r = requests.get(url).json()
        meta = r["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev_close = meta["previousClose"]
        change_percent = ((price - prev_close) / prev_close) * 100
        return round(price, 2), round(change_percent, 2)
    except Exception:
        return None, None

def format_alert(symbol, price, change):
    now = datetime.now().strftime("%H:%M:%S")
    move_type = "🚀 ارتفع" if change > 0 else "📉 انخفض"
    msg = (
        f"▫️الرمز: {symbol}\n"
        f"▫️نوع الحركة: {'اختراق' if change > 0 else 'هبوط'}\n"
        f"▫️نسبة التغير: {change:+.2f}%\n"
        f"▫️السعر الحالي: {price} دولار\n"
        f"▫️عدد مرات التنبيه اليوم: 1 مرة\n"
        f"▫️⏰ التوقيت الأمريكي: {now}"
    )
    return msg

def send_alert(symbol, price, change):
    message = format_alert(symbol, price, change)
    bot.send_message(CHANNEL_ID, message)

# الحلقة الرئيسية
while True:
    for sym in SYMBOLS:
        price, change = get_stock_data(sym)
        if price is None:
            continue

        # فحص الحركة ±15%
        if abs(change) >= 15:
            if sym not in sent_alerts or sent_alerts[sym] != change:
                send_alert(sym, price, change)
                sent_alerts[sym] = change
                print(f"تم إرسال تنبيه: {sym} ({change}%)")

    time.sleep(30)
