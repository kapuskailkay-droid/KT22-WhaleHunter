import io
import time
import urllib.parse
import matplotlib
import mplfinance as mpf
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

matplotlib.use('Agg')

# --- SABİT BOT VE TELEGRAM AYARLARI (GÖMÜLÜ) ---
GOMULU_BOT_TOKEN = "7820599329:AAEAa13edhS9PLoG1t8R34PLO9xpKlaT_Lc"
GOMULU_CHAT_ID = "-1004434260285"
GOMULU_TOPIC_ID = "387"
MIN_HACIM_KATI = 1.8

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="KENDİNE22TRADER VIP MEXC Çoklu Zaman Radarı",
    layout="wide"
)

if "gonderilen_sinyaller" not in st.session_state:
    st.session_state.gonderilen_sinyaller = set()

# --- YAN PANEL: TELEGRAM AYARLARI ---
st.sidebar.header("📱 Telegram Bildirim Ayarları")
telegram_aktif = st.sidebar.checkbox("🚀 Telegram'a Gönder", value=True)
bot_token = st.sidebar.text_input("Telegram Bot Token", value=GOMULU_BOT_TOKEN, type="password")
chat_id = st.sidebar.text_input("Telegram Chat ID", value=GOMULU_CHAT_ID)
topic_id = st.sidebar.text_input("Telegram Topic ID", value=GOMULU_TOPIC_ID)

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Canlı Yayın & Otomatik Yenileme")

oto_yenileme = st.sidebar.checkbox("🔄 Otomatik Canlı Taramayı Aç", value=True)
st_autorefresh(interval=60 * 1000, key="canli_vip_tarayici")
st.sidebar.success("🟢 Canlı mod aktif: Her 1 dakikada bir yenileniyor")

st.sidebar.markdown("---")
st.sidebar.info("🔍 **Otomatik Taranan Zaman Dilimleri:**\n• 15 Dakika (15m)\n• 30 Dakika (30m)\n• 1 Saat (1h)\n• 4 Saat (4h)\n• 1 Gün (1d)\n• 1 Hafta (1w)\n\n🐋 **Minimum Hacim Patlaması:** 1.8x")

coin_adedi = st.sidebar.select_slider("Taranacak En Yüksek Hacimli Coin Sayısı", options=[20, 40, 60, 80, 100], value=50)

st.title("🐋 KENDİNE22TRADER - TÜM ZAMAN DİLİMLERİ BALİNA & VIP SİNYAL RADARI")

# --- GRAFİK OLUŞTURMA ---
def grafik_olustur(df_mum, sembol, zaman_dilimi_adi):
    df_grafik = df_mum.copy()
    df_grafik['Zaman'] = pd.to_datetime(df_grafik['Zaman'], unit='ms')
    df_grafik.set_index('Zaman', inplace=True)
    df_grafik.rename(columns={
        'Acilis': 'Open', 'Yuksek': 'High', 'Dusuk': 'Low', 'Kapanis': 'Close', 'Hacim': 'Volume'
    }, inplace=True)
    
    mc = mpf.make_marketcolors(up='#00ff88', down='#ff3366', inherit=True)
    s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc, gridcolor='#2b2b2b')
    
    buf = io.BytesIO()
    mpf.plot(
        df_grafik.tail(40),
        type='candle',
        volume=True,
        style=s,
        title=f"{sembol} ({zaman_dilimi_adi})",
        savefig=dict(fname=buf, dpi=120, bbox_inches='tight')
    )
    buf.seek(0)
    return buf

# --- TELEGRAM FOTOĞRAF GÖNDERME (TOPIC 387 KİLİTLİ) ---
def telegram_fotograf_gonder(foto_buf, caption_metni):
    if telegram_aktif and bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token.strip()}/sendPhoto"
        hedef_topic = str(topic_id).strip() if (topic_id and str(topic_id).strip() != "") else GOMULU_TOPIC_ID
        
        data = {
            "chat_id": chat_id.strip(),
            "caption": caption_metni,
            "parse_mode": "HTML"
        }
        if hedef_topic:
            try:
                data["message_thread_id"] = int(hedef_topic)
            except ValueError:
                pass
                
        files = {"photo": ("chart.png", foto_buf, "image/png")}
        try:
            requests.post(url, data=data, files=files, timeout=14)
        except Exception:
            pass

# --- İNDİKATÖR HESAPLAMALARI ---
def hesapla_rsi(seri, periyot=14):
    fark = seri.diff()
    kazanc = (fark.where(fark > 0, 0)).rolling(window=periyot).mean()
    kayip = (-fark.where(fark < 0, 0)).rolling(window=periyot).mean()
    rs = kazanc / (kayip + 1e-9)
    return 100 - (100 / (1 + rs))

def hesapla_atr(df, periyot=14):
    h_l = df['Yuksek'] - df['Dusuk']
    h_pc = (df['Yuksek'] - df['Kapanis'].shift(1)).abs()
    l_pc = (df['Dusuk'] - df['Kapanis'].shift(1)).abs()
    tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
    atr_val = tr.rolling(window=periyot).mean().iloc[-1]
    return atr_val if not np.isnan(atr_val) else df['Kapanis'].iloc[-1] * 0.02

def hesapla_tp_sl(fiyat, atr, yon="LONG"):
    if yon == "LONG":
        sl = round(fiyat - (atr * 1.5), 6)
        tp1 = round(fiyat + (atr * 1.5), 6)
        tp2 = round(fiyat + (atr * 3.0), 6)
    else:
        sl = round(fiyat + (atr * 1.5), 6)
        tp1 = round(fiyat - (atr * 1.5), 6)
        tp2 = round(fiyat - (atr * 3.0), 6)
    return tp1, tp2, sl

# --- ÇOKLU ZAMAN DİLİMLİ MEXC VADELİ TARAYICI ---
def coklu_piyasa_tara():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    try:
        url_tickers = "https://contract.mexc.com/api/v1/contract/ticker"
        res = requests.get(url_tickers, headers=headers, timeout=6).json()
        if not res.get("success", False):
            st.error("MEXC Vadeli Veri Akışı Hatası")
            return pd.DataFrame()
            
        data_tickers = res.get("data", [])
        usdt_pariteler = [d for d in data_tickers if d.get("symbol", "").endswith("_USDT")]
        usdt_pariteler.sort(key=lambda x: float(x.get("amount24", 0) or 0), reverse=True)
        hedef_listesi = usdt_pariteler[:coin_adedi]
    except Exception as e:
        st.error(f"MEXC Bağlantı Hatası: {e}")
        return pd.DataFrame()

    zaman_dilimleri = [
        ("Min15", "15m", "15 Dakika"),
        ("Min30", "30m", "30 Dakika"),
        ("Min60", "1h", "1 Saat"),
        ("Hour4", "4h", "4 Saat"),
        ("Day1", "1d", "1 Gün"),
        ("Week1", "1w", "1 Hafta")
    ]

    sonuclar = []

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
                            atr = hesapla_atr(df)
                            yon_turu = "LONG" if long_kosulu else "SHORT"
                            tp1, tp2, sl = hesapla_tp_sl(son_kapanis, atr, yon=yon_turu)
                            
                            sinyal_id = f"{sembol_raw}_{yon}_{tf_kod}"
                            
                            if telegram_aktif and sinyal_id not in st.session_state.gonderilen_sinyaller:
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
                                try:
                                    foto_buffer = grafik_olustur(df, temiz_parite, f"{tf_ad} ({tf_kod})")
                                    telegram_fotograf_gonder(foto_buffer, tg_caption)
                                except Exception:
                                    pass
                                    
                                st.session_state.gonderilen_sinyaller.add(sinyal_id)
                            
                            sonuclar.append({
                                "Zaman Dilimi": f"{tf_ad} ({tf_kod})",
                                "Yön": yon,
                                "Sembol": temiz_parite,
                                "Fiyat ($)": son_kapanis,
                                "Hacim Katı": f"{round(hacim_orani, 2)}x",
                                "RSI": round(son_rsi, 1),
                                "TP1 ($)": tp1,
                                "SL ($)": sl,
                                "Grafik": mexc_link
                            })
            except Exception:
                pass
                
    return pd.DataFrame(sonuclar)

# --- ÇALIŞTIRMA VE GÖRÜNTÜLEME ---
manuel_tara = st.button("🔍 Tüm Zaman Dilimlerini Manuel Tara", type="primary", use_container_width=True)

if oto_yenileme or manuel_tara:
    with st.spinner("15m, 30m, 1h, 4h, 1d ve 1w zaman dilimlerinde balina hacimleri taranıyor..."):
        df_sonuc = coklu_piyasa_tara()
        
    if not df_sonuc.empty:
        st.success(f"Tespit Edilen Balina Sinyalleri ({pd.Timestamp.now().strftime('%H:%M:%S')}):")
        st.dataframe(
            df_sonuc,
            column_config={"Grafik": st.column_config.LinkColumn("MEXC Link", display_text="Grafiği Aç ↗")},
            use_container_width=True
        )
    else:
        st.info(f"Şu an taranan zaman dilimlerinde 1.8x ve üzeri balina hacim patlaması bulunamadı ({pd.Timestamp.now().strftime('%H:%M:%S')}).")
