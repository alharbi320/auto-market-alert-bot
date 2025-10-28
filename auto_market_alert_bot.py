import requests
import time
import threading
from datetime import datetime
import os

# === إعدادات عامة ===
FINNHUB_TOKEN = "d3udq1hr01qil4apjtb0d3udq1hr01qil4apjtbg"
TELEGRAM_TOKEN = "ضع_توكن_البوت_هنا"
CHAT_ID = "ضع_رقم_المحادثة_هنا"

# === إعداد قائمة الأسواق المطلوبة ===
EXCHANGES = ["NASDAQ", "NYSE", "AMEX"]
PERCENT_LIMIT = 20  # شرط التنبيه فوق 20%

# === دالة إرسال تنبيه إلى التلغرام ===
def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"[Telegram Error] {e}")

# === دالة فحص السهم ===
def check_symbol(symbol):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_TOKEN}"
    try:
        response = requests.get(url)
        data = response.json()

        if "c" not in data or "pc" not in data:
            return None

        current = data["c"]
        previous = data["pc"]

        if previous == 0:
            return None

        percent_change = ((current - previous) / previous) * 100

        # 🟡 سطر الطباعة التحليلية
        print(f"[DEBUG] {symbol} => Current: {current} | Prev: {previous} | Change: {percent_change:.2f}%")

        if percent_change > PERCENT_LIMIT:
            return {
                "symbol": symbol,
                "change": percent_change,
                "current": current
            }

    except Exception as e:
        print(f"[Error] {symbol}: {e}")
    return None


# === حلقة التشغيل الرئيسية ===
def main_loop():
    print("✅ بدء مراقبة الأسهم (NASDAQ / NYSE / AMEX) فوق 20%")

    # رموز اختبار (يمكنك توسعتها لاحقاً)
    symbols = ["FRGT", "VSEE", "CODX", "SMX", "OP", "LUNG", "SBEV", "DDD"]

    while True:
        try:
            alerts = []

            for sym in symbols:
                result = check_symbol(sym)
                if result:
                    alerts.append(result)

            print(f"[cycle] checked={len(symbols)} | alerts={len(alerts)} | time={datetime.now().strftime('%H:%M:%S')}")

            # === إرسال التنبيهات ===
            for alert in alerts:
                msg = (
                    f"🚀 سهم {alert['symbol']} ارتفع بنسبة {alert['change']:.2f}%\n"
                    f"💰 السعر الحالي: ${alert['current']}\n"
                    f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                send_telegram_message(msg)

            # === تأخير بين كل دورة لتجنب الحظر ===
            time.sleep(30)

        except Exception as e:
            print(f"[Loop Error] {e}")
            time.sleep(60)


# === تشغيل البوت في Thread ===
def start_bot():
    main_loop()


if __name__ == "__main__":
    threading.Thread(target=start_bot, daemon=True).start()
    print("🌕 البوت شغال حالياً — ينتظر ظهور الأسهم فوق 20% 🚀")
    while True:
        time.sleep(100)
