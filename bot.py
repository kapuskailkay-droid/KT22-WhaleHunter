import io
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import matplotlib
import mplfinance as mpf
import numpy as np
import pandas as pd
import requests

matplotlib.use('Agg')

# --- SABİT GÖMÜLÜ TELEGRAM AYARLARI ---
BOT_TOKEN = "7820599329:AAEAa13edhS9PLoG1t8R34PLO9xpKlaT_Lc"
CHAT_ID = "-1004434260285"
TOPIC_ID = 387
COIN_ADEDI = 50
MIN_HACIM_KATI = 1.8

gonderilen_sinyaller = set()

# Render Ücretsiz Port Dinleyici
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"KENDINE22TRADER Coklu Zaman Balina Botu 7/24 Aktif!")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

def grafik_olustur(df_mum, sembol, tf_ad):
    df_grafik = df_mum.copy()
    df_grafik['Zaman'] = pd.to_datetime(df_grafik['Zaman'], unit='ms')
    df_grafik.set_index('Zaman', inplace=True)
    df_grafik.rename(columns={'Acilis':'Open','Yuksek':'High','Dusuk':'Low','Kapanis':'Close','Hacim':'Volume'}, inplace=True)
    
    mc = mpf.make_marketcolors(up='#00ff88', down='#ff3366', inherit=True)
    s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridcolor='#2b2b2b')
    buf = io.BytesIO()
    mpf.plot(df_grafik.tail(40), type='candle', volume=True, style=s, title=f"{sembol} ({tf_ad})", savefig=dict(fname=buf, dpi=120, bbox_inches='tight'))
    buf.seek(0)
    return buf

def telegram_fotograf_gonder(foto_buf, caption_metni):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": CHAT_ID,
        "message_thread_id": TOPIC_ID,
        "caption": caption_metni,
        "parse_mode": "HTML"
    }
    files = {"photo": ("chart.png", foto_buf, "image/png")}
    try:
        requests.post(url, data=data, files=files, timeout=14)
    except Exception as e:
        print(f"Telegram Hatası: {e}")

def hesapla_rsi(seri, periyot=14):
    fark = seri.diff()
    kazanc = (fark.where(fark > 0, 0)).rolling(window=periyot).mean()
    kayip = (-fark.where(fark < 0, 0)).rolling(window=periyot).mean()
    rs = kazanc / (kayip + 1e-9)
    return 100 - (100 / (1 + rs))

def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    print("🚀 KENDİNE22TRADER Balina & VIP (Topic 387) 7/24 Çoklu Zaman Motoru Devrede...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    zaman_dilimleri = [
        ("Min15", "15m", "15 Dakika"),
        ("Min30", "30m", "30 Dakika"),
        ("Min60", "1h", "1 Saat"),
        ("Hour4", "4h", "4 Saat"),
        ("Day1", "1d", "1 Gün"),
        ("Week1", "1w", "1 Hafta")
    ]

    while True:
        try:
            url_tickers = "https://contract.mexc.com/api/v1/contract/ticker"
            res = requests.get(url_tickers, headers=headers, timeout=6).json()
            if res.get("success", False):
                data_tickers = res.get("data", [])
                usdt_pariteler = [d for d in data_tickers if d.get("symbol", "").endswith("_USDT")]
                usdt_pariteler.sort(key=lambda x: float(x.get("amount24", 0) or 0), reverse=True)
                hedef_listesi = usdt_pariteler[:COIN_ADEDI]
                
                for coin_bilgi in hedef_listesi:
                    sembol_raw = coin_bilgi["symbol"]
                    temiz_parite = sembol_raw.replace('_', '/')
                    mexc_link = f"https://www.mexc.com/tr-TR/futures/{sembol_raw}"

                    for api_tf, tf_kod, tf_ad in zaman_dilimleri:
                        try:
                            url_kline = f"https://contract.mexc.com/api/v1/contract/kline/{sembol_raw}?interval={api_tf}"
                            kline_res = requests.get(url_kline, headers=headers, timeout=3).json()
                            if kline_res.get("success", False) and kline_res.get("data"):
                                k_data = kline_res["data"]
                                times = k_data.get("time", [])
                                opens = k_data.get("open", [])
                                closes = k_data.get("close", [])
                                highs = k_data.get("high", [])
                                lows = k_data.get("low", [])
                                vols = k_data.get("vol", [])
                                
                                if len(closes) >= 20:
                                    df = pd.DataFrame({
                                        "Zaman": [t * 1000 for t in times[-40:]],
                                        "Acilis": [float(x) for x in opens[-40:]],
                                        "Yuksek": [float(x) for x in highs[-40:]],
                                        "Dusuk": [float(x) for x in lows[-40:]],
                                        "Kapanis": [float(x) for x in closes[-40:]],
                                        "Hacim": [float(x) for x in vols[-40:]]
                                    })
                                    
                                    gecmis_hacim = df['Hacim'].iloc[:-1].mean()
                                    son_hacim = df['Hacim'].iloc[-1]
                                    hacim_orani = (son_hacim / gecmis_hacim) if gecmis_hacim > 0 else 0
                                    
                                    df['RSI'] = hesapla_rsi(df['Kapanis'])
                                    son_rsi = df['RSI'].iloc[-1]
                                    son_kapanis = df['Kapanis'].iloc[-1]
                                    son_acilis = df['Acilis'].iloc[-1]
                                    
                                    long_kosulu = (hacim_orani >= MIN_HACIM_KATI) and (son_kapanis > son_acilis) and (son_rsi <= 65)
                                    short_kosulu = (hacim_orani >= MIN_HACIM_KATI) and (son_kapanis < son_acilis) and (son_rsi >= 35)
                                    
                                    if long_kosulu or short_kosulu:
                                        yon = "🟢 LONG" if long_kosulu else "🔴 SHORT"
                                        sinyal_id = f"{sembol_raw}_{yon}_{tf_kod}"
                                        
                                        if sinyal_id not in gonderilen_sinyaller:
                                            atr = (df['Yuksek'] - df['Dusuk']).rolling(14).mean().iloc[-1]
                                            sl = round(son_kapanis - (atr * 1.5), 6) if long_kosulu else round(son_kapanis + (atr * 1.5), 6)
                                            tp1 = round(son_kapanis + (atr * 1.5), 6) if long_kosulu else round(son_kapanis - (atr * 1.5), 6)
                                            tp2 = round(son_kapanis + (atr * 3.0), 6) if long_kosulu else round(son_kapanis - (atr * 3.0), 6)
                                            
                                            tg_caption = (
                                                f"🐋 <b>KENDİNE22TRADER BALİNA & VIP SİNYALİ</b>\n\n"
                                                f"📌 <b>Parite:</b> {temiz_parite}\n"
                                                f"⏱ <b>Zaman Dilimi:</b> <b>{tf_ad} ({tf_kod})</b>\n"
                                                f"🎯 <b>Yön:</b> {yon}\n"
                                                f"💰 <b>Giriş Fiyatı:</b> {son_kapanis} $\n"
                                                f"📊 <b>Balina Hacim Patlaması:</b> <b>{round(hacim_orani, 2)}x</b>\n"
                                                f"📈 <b>RSI:</b> {round(son_rsi, 1)}\n\n"
                                                f"🎯 <b>HEDEF 1 (TP1):</b> {tp1} $\n"
                                                f"🎯 <b>HEDEF 2 (TP2):</b> {tp2} $\n"
                                                f"🛑 <b>STOP-LOSS:</b> {sl} $\n\n"
                                                f"🔗 <a href='{mexc_link}'>MEXC Vadeli Grafiği Aç ↗</a>"
                                            )
                                            foto = grafik_olustur(df, temiz_parite, f"{tf_ad} ({tf_kod})")
                                            telegram_fotograf_gonder(foto, tg_caption)
                                            gonderilen_sinyaller.add(sinyal_id)
                                            print(f"✅ Balina Sinyali Gönderildi: {sinyal_id}")
                        except Exception:
                            pass
        except Exception as e:
            print(f"Döngü Hatası: {e}")
        time.sleep(60)

if __name__ == "__main__":
    main()
