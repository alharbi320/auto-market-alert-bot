# -*- coding: utf-8 -*-
import os, time, math, random, requests, threading
from datetime import datetime, timedelta
import pytz
import telebot
from flask import Flask

# ========== إعدادات عامة ==========
TOKEN       = "8316302365:AAHNtXBdma4ggcw5dEwtwxHST8xqvgmJoOU"  # توكن البوت
CHANNEL_ID  = "@kaaty320"                                       # قناة التلغرام
FINNHUB_KEY = "d3udq1hr01qi14apjtb0d3udq1hr01qi14apjtbg"        # مفتاح Finnhub

MARKET_MICS = {"XNAS", "XNYS", "XASE"}
CHECK_INTERVAL_SEC = 60
UP_CHANGE_PCT = 5
MIN_VOL_15M = 100_000
MIN_DOLLAR_15M = 200_000
REPEAT_COOLDOWN_S = 15 * 60
TOP_N = 50
PRICE_FILTER = 0.4

US_TZ = pytz.timezone("US/Eastern")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
last_sent, _daily_counts = {}, {}
BASE = "https://finnhub.io/api/v1"

# ------------------- أدوات Finnhub -------------------
def fh_get_symbols_us():
    try:
        r = requests.get(f"{BASE}/stock/symbol", params={"exchange": "US", "token": FINNHUB_KEY}, timeout=20)
        r.raise_for_status()
        data = r.json()
        syms = [x["symbol"] for x in data if (x.get("mic","").upper() in MARKET_MICS and x.get("symbol","").isalpha() and len(x["symbol"])<=5)]
        return sorted(set(syms))
    except Exception as e:
        print("fh_get_symbols_us error:", e)
        return []

def fh_quote(s):
    r = requests.get(f"{BASE}/quote", params={"symbol": s, "token": FINNHUB_KEY}, timeout=15)
    r.raise_for_status(); return r.json()

def fh_candles_1m(s, frm, to):
    r = requests.get(f"{BASE}/stock/candle", params={"symbol": s, "resolution": 1, "from": int(frm), "to": int(to), "token": FINNHUB_KEY}, timeout=20)
    r.raise_for_status(); return r.json()

def fh_profile(s):
    try:
        r = requests.get(f"{BASE}/stock/profile2", params={"symbol": s, "token": FINNHUB_KEY}, timeout=10)
        r.raise_for_status(); return r.json()
    except Exception: return {}

def fh_metrics(s):
    try:
        r = requests.get(f"{BASE}/stock/metric", params={"symbol": s, "metric": "all", "token": FINNHUB_KEY}, timeout=10)
        r.raise_for_status(); return r.json()
    except Exception: return {}

# ------------------- الأدوات -------------------
def compute_vol_15m(s, price):
    now=int(datetime.utcnow().timestamp()); frm=now-3600
    try:
        data=fh_candles_1m(s,frm,now)
        if data.get("s")!="ok": return False,0,0,{}
        vols=data.get("v",[]) or []
        vol_15=sum(vols[-15:]); first_min=vols[-15] if len(vols)>=15 else (vols[0] if vols else 0)
        avg_15=(sum(vols)/len(vols))*15 if vols else 0
        return True,int(vol_15),int(first_min),{"avg_15m":avg_15}
    except Exception as e:
        print("compute_vol_15m error",s,e); return False,0,0,{}

def safe_num(x):
    try:return float(x)
    except:return None

def fmt_us_time():
    try:return datetime.now(US_TZ).strftime("%I:%M:%S %p")
    except:return datetime.utcnow().strftime("%H:%M:%S")

def format_alert_ar(sym,kind,count,dp,price,float_sh,market_cap,rel_vol,first_min,dollar_15):
    f_txt=f"{int(float_sh):,}" if float_sh else "—"
    m_txt=f"${int(market_cap):,}" if market_cap else "—"
    r_txt=f"{rel_vol:.2f}X" if rel_vol is not None else "—"
    fmin=f"{first_min:,}" if first_min else "—"
    dol=f"${int(dollar_15):,}" if dollar_15 else "—"
    return (f"▪️ الرمز: 🇺🇸 {sym}\n"
            f"▪️ نوع الحركة: {kind}\n"
            f"▪️ عدد مرات التنبيه اليوم: {count} مرة\n"
            f"▪️ نسبة الارتفاع: {dp:+.2f}%\n"
            f"▪️ السعر الحالي: {price:.3f} دولار\n"
            f"▪️ عدد الأسهم المتاحة للتداول: {f_txt}\n"
            f"▪️ القيمة السوقية: {m_txt}\n"
            f"▪️ الحجم النسبي: {r_txt}\n"
            f"▪️ حجم أول دقيقة: {fmin}\n"
            f"▪️ حجم السيولة: {dol}\n"
            f"🇺🇸 التوقيت الأمريكي: {fmt_us_time()}")

def send_alert(s,kind,price,dp,vol_15,first_min,dol_15,float_sh,market_cap,rel_vol):
    today=datetime.utcnow().date().isoformat(); key=f"{s}:{today}"
    _daily_counts[key]=_daily_counts.get(key,0)+1; count=_daily_counts[key]
    msg=format_alert_ar(s,kind,count,dp,price,float_sh,market_cap,rel_vol,first_min,dol_15)
    try:
        bot.send_message(CHANNEL_ID,msg)
        print(f"[ALERT SENT] {s} dp={dp:.2f}% vol15={vol_15}")
    except Exception as e: print("send_alert error",s,e)

# ------------------- الحلقة الرئيسية -------------------
def main_loop():
    bot.send_message(CHANNEL_ID,"✅ البوت اشتغل الآن — مراقبة أعلى 50 سهم زخماً (الكابتن)")
    syms=fh_get_symbols_us() or ["AAPL","NVDA","TSLA","AMZN","MSFT"]
    print(f"Loaded {len(syms)} symbols.")
    while True:
        start=time.time(); cands=[]
        sample=random.sample(syms,1200) if len(syms)>1200 else syms
        for s in sample:
            try:
                q=fh_quote(s); price=safe_num(q.get("c")); dp=safe_num(q.get("dp"))
                if price is None or dp is None or price<PRICE_FILTER: continue
                ok,vol_15,first_min,aux=compute_vol_15m(s,price)
                if not ok: continue
                score=(dp or 0)*(vol_15 or 0)
                cands.append({"s":s,"price":price,"dp":dp,"vol":vol_15,"f":first_min,"aux":aux,"sc":score})
            except Exception as e: print("scan error",s,e)
        top=sorted(cands,key=lambda x:x["sc"],reverse=True)[:TOP_N]
        print(f"Top {len(top)} ready...")
        for it in top:
            s,itp=it["s"],it["price"]; dp,vol,fm=it["dp"],it["vol"],it["f"]
            aux=it["aux"] or {}; avg15=aux.get("avg_15m") or 0
            dol=vol*itp; rel=(vol/avg15) if avg15>0 else None
            p=fh_profile(s) or {}; m=fh_metrics(s) or {}
            mc=p.get("marketCapitalization") or (m.get("metric") or {}).get("marketCapitalization")
            fl=p.get("shareOutstanding") or p.get("floatShares") or (m.get("shareOutstanding") if isinstance(m,dict) else None)
            if dp>=UP_CHANGE_PCT and vol>=MIN_VOL_15M and dol>=MIN_DOLLAR_15M:
                if time.time()-last_sent.get(s,0)>=REPEAT_COOLDOWN_S:
                    kind="اختراق" if dp>6 else "زخم صعودي"
                    send_alert(s,kind,itp,dp,vol,fm,dol,fl,mc,rel)
                    last_sent[s]=time.time()
        sl=max(1,CHECK_INTERVAL_SEC-(time.time()-start))
        print(f"[Cycle end] sleep={sl:.1f}s"); time.sleep(sl)

# ---------- Flask ----------
app=Flask(__name__)
@app.route("/")
def index(): return "Auto market alert bot is running ✅"
def run_web():
    port=int(os.getenv("PORT","10000"))
    app.run(host="0.0.0.0",port=port,debug=False)

# ---------- التشغيل ----------
if __name__=="__main__":
    threading.Thread(target=run_web,daemon=True).start()
    print("==> Service starting...")
    main_loop()
