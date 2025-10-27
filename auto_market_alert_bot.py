import requests
import telebot
import time
from datetime import datetime
from flask import Flask

# ===== إعدادات البوت =====
TOKEN = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"
CHANNEL_ID = "@kaaty320"
FINNHUB_API = "3duq1hr01qil14apjtb0d3udq1hr01qil14apjtb"
bot = telebot.TeleBot(TOKEN)

# ===== إعدادات السوق =====
MARKETS = ["NASDAQ", "NYSE", "AMEX"]
CHECK_INTERVAL = 60  # كل دقيقة
UP_CHANGE = 10.0     # ارتفاع 10٪ أو أكثر

# قاعدة بيانات مؤقتة لتجنب التكرار
sent_alerts = {}

# ===== دالة لجلب الأسهم ذات الزخم من Finnhub =====
def get_high_momentum_stocks():
    url = f"https://finnhub.io/api/v1/scan/technical?token={FINNHUB_API}"
    try:
        r = requests.get(url).json()
        results = r.get("technicalAnalysis", [])
        symbols = []
        for item in results:
            symbol = item.get("symbol", "")
            exchange = item.get("exchange", "")
            if exchange in MARKETS:
                symbols.append(symbol)
        return symbols
    except Exception as e:
        print(f"❌ خطأ في جلب الزخم: {e}")
        return []

# ===== دالة لجلب بيانات السهم =====
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

# ===== تنسيق الرسالة =====
def format_alert(symbol, price, change):
    now = datetime.now().strftime("%I:%M:%S %p")
    msg = (
        f"📈 الرمز: {symbol}\n"
        f"🚀 نسبة الارتفاع: +{change:.2f}%\n"
        f"💵 السعر الحالي: {price} دولار\n"
        f"🕐 التوقيت الأمريكي: {now}"
    )
    return msg

# ===== إرسال التنبيه =====
def send_alert(symbol, price, change):
    message = format_alert(symbol, price, change)
    bot.send_message(CHANNEL_ID, message)

# ===== الحلقة الرئيسية =====
def main_loop():
    while True:
        symbols = get_high_momentum_stocks()
        print(f"🔍 عدد الأسهم ذات الزخم العالي: {len(symbols)}")
        for sym in symbols:
            price, change = get_stock_data(sym)
            if price is None or change is None:
                continue
            if change >= UP_CHANGE:
                if sym not in sent_alerts or sent_alerts[sym] != change:
                    send_alert(sym, price, change)
                    sent_alerts[sym] = change
                    print(f"✅ تم إرسال تنبيه لـ {sym} (+{change}%)")
        time.sleep(CHECK_INTERVAL)

# ===== Flask لتشغيل Render =====
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ البوت يعمل بنجاح!"

if __name__ == "__main__":
    import threading
    threading.Thread(target=main_loop).start()
    app.run(host="0.0.0.0", port=10000)
