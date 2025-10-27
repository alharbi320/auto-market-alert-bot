import telebot
import requests
import time
from datetime import datetime, timedelta
import pytz

# ========= إعدادات البوت =========
TOKEN = "ضع_توكن_البوت_هنا"         # ← ضع التوكن من @BotFather
CHANNEL_ID = "@kaaty320"             # ← اسم القناة العامة
API_KEY = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"  # مفتاح Finnhub
CHECK_INTERVAL = 60                  # كل 60 ثانية
RISE_ALERT = 15                      # نسبة الارتفاع للتنبيه
DROP_ALERT = -10                     # نسبة الهبوط للتنبيه
bot = telebot.TeleBot(TOKEN)
last_alerts = {}

# ========= دالة جلب السعر والتغير =========
def get_quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m"
    try:
        res = requests.get(url, timeout=10).json()
        meta = res["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev = meta["chartPreviousClose"]
        change = ((price - prev) / prev) * 100 if prev else 0
        return round(price, 2), round(change, 2)
    except Exception as e:
        print(f"❌ خطأ في جلب {symbol}: {e}")
        return None, None

# ========= دالة جلب آخر خبر من Finnhub =========
def get_latest_news(symbol):
    try:
        now = datetime.utcnow()
        past = now - timedelta(days=3)
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={past.strftime('%Y-%m-%d')}&to={now.strftime('%Y-%m-%d')}&token={API_KEY}"
        res = requests.get(url, timeout=10).json()
        if res and isinstance(res, list) and len(res) > 0:
            headline = res[0].get("headline", "")
            return f"📰 <b>آخر خبر:</b> {headline}"
        else:
            return "📰 <b>آخر خبر:</b> لا يوجد خبر حديث."
    except Exception as e:
        print(f"⚠️ خطأ في جلب الأخبار لـ {symbol}: {e}")
        return "📰 <b>آخر خبر:</b> تعذر الحصول على البيانات."

# ========= إرسال التنبيه مع منع التكرار =========
def send_alert(symbol, message):
    if last_alerts.get(symbol) == message:
        return
    last_alerts[symbol] = message
    bot.send_message(CHANNEL_ID, message, parse_mode="HTML")

# ========= تنسيق رسالة التنبيه =========
def make_message(symbol, price, change, news):
    now_us = datetime.now(pytz.timezone("US/Eastern")).strftime("%H:%M:%S")
    الاتجاه = "🚀 ارتفاع قوي" if change > 0 else "📉 هبوط حاد"
    نوع = "📊 زخم لحظي" if abs(change) < 15 else "⚡ تحرك كبير"
    msg = (
        f"<b>📈 الرمز:</b> {symbol}\n"
        f"<b>{الاتجاه}</b>\n"
        f"<b>💹 نسبة التغير:</b> {change:+.2f}%\n"
        f"<b>💰 السعر الحالي:</b> {price} دولار\n"
        f"<b>🧭 نوع الحركة:</b> {نوع}\n"
        f"<b>🇺🇸 التوقيت الأمريكي:</b> {now_us}\n\n"
        f"{news}"
    )
    return msg

# ========= مراقبة مستمرة =========
def monitor():
    watchlist = ["CASI", "RANI", "WGRX", "TPET", "NERV", "AAPL"]
    while True:
        for sym in watchlist:
            price, change = get_quote(sym)
            if price is None:
                continue
            if change >= RISE_ALERT or change <= DROP_ALERT or abs(change) >= 5:
                news = get_latest_news(sym)
                msg = make_message(sym, price, change, news)
                send_alert(sym, msg)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    print("🚀 البوت بدأ المراقبة وإرسال التنبيهات مع الأخبار إلى القناة...")
    monitor()
