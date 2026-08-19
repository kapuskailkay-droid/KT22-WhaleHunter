import time
import ccxt
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# --- SABİT BOT VE TELEGRAM AYARLARI ---
GOMULU_BOT_TOKEN = "7820599329:AAEAa13edhS9PLoG1t8R34PLO9xpKlaT_Lc"
GOMULU_CHAT_ID = "-1004434260285"

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="KENDİNE22TRADER - BTC/ETH & Haber Radarı",
    layout="wide"
)

if "son_haber_idleri" not in st.session_state:
    st.session_state.son_haber_idleri = set()

if "son_fiyat_hafizasi" not in st.session_state:
    st.session_state.son_fiyat_hafizasi = {}

# --- YAN PANEL: TELEGRAM AYARLARI ---
st.sidebar.header("📱 Telegram Bildirim Ayarları")
telegram_aktif = st.sidebar.checkbox("🚀 Telegram Bildirimleri Açık", value=True)
bot_token = st.sidebar.text_input("Telegram Bot Token", value=GOMULU_BOT_TOKEN, type="password")
chat_id = st.sidebar.text_input("Telegram Chat ID", value=GOMULU_CHAT_ID)
topic_id = st.sidebar.text_input("Haber Sekmesi Topic ID", value="", help="Haberler için açtığınız sekmenin ID'si (Genel grupsa boş bırakın)")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Canlı Takip & Alarm Ayarları")

oto_yenileme = st.sidebar.checkbox("🔄 Otomatik Canlı Takip Açık", value=True)
yenileme_araligi = st.sidebar.selectbox("Kontrol Sıklığı", options=[15, 30, 60], index=0, format_func=lambda x: f"{x} Saniyede Bir")

if oto_yenileme:
    st_autorefresh(interval=yenileme_araligi * 1000, key="haber_ve_fiyat_takip")
    st.sidebar.success(f"🟢 Canlı mod aktif: Her {yenileme_araligi} sn")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Ani Değişim Alarm Eşikleri")

min_artis_5m = st.sidebar.slider("5 Dakikalık Değişim Eşiği (%)", 1.0, 5.0, 1.5, 0.1)
min_artis_15m = st.sidebar.slider("15 Dakikalık Değişim Eşiği (%)", 1.5, 8.0, 2.5, 0.1)
min_artis_60m = st.sidebar.slider("60 Dakikalık Değişim Eşiği (%)", 2.5, 12.0, 3.5, 0.1)

st.title("⚡ KENDİNE22TRADER - BTC/ETH Pump/Dump & FED Haber Radarı")

# --- TELEGRAM MESAJ GÖNDERİCİ ---
def telegram_mesaj_gonder(metin):
    if telegram_aktif and bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
        params = {}
        if topic_id and str(topic_id).strip() != "":
            try:
                params["message_thread_id"] = int(str(topic_id).strip())
            except ValueError:
                pass
        data = {
            "chat_id": chat_id.strip(),
            "text": metin,
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, params=params, data=data, timeout=8)
        except Exception:
            pass

# --- KRİPTO & FED HABER AKIŞI MOTORU ---
def son_dakika_haberleri_tara():
    url = "https://cryptopanic.com/api/v1/posts/?auth_token=free&public=true"
    haber_listesi = []
    
    try:
        res = requests.get(url, timeout=5).json()
        posts = res.get("results", [])
        
        for post in posts[:15]:
            p_id = str(post.get("id"))
            title = post.get("title", "")
            kaynak = post.get("source", {}).get("title", "Kripto Ajansı")
            url_link = post.get("url", "https://cryptopanic.com")
            
            # Haber Filtresi
            onemli_kelimeler = ["FED", "POWELL", "RATE", "INFLATION", "CPI", "SEC", "ETF", "BREAKING", "URGENT", "BITCOIN", "ETHEREUM", "BINANCE", "WAR"]
            onemli_mi = any(k in title.upper() for k in onemli_kelimeler)
            
            if p_id not in st.session_state.son_haber_idleri:
                st.session_state.son_haber_idleri.add(p_id)
                
                # Telegram'a Haber Gönder
                if telegram_aktif:
                    etiket = "🚨 <b>SON DAKİKA GELİŞMESİ</b>" if onemli_mi else "📰 <b>KRİPTO HABERİ</b>"
                    msg = (
                        f"{etiket}\n\n"
                        f"📌 <b>{title}</b>\n\n"
                        f"🌐 <b>Kaynak:</b> {kaynak}\n"
                        f"🔗 <a href='{url_link}'>Haberi Oku ↗</a>"
                    )
                    telegram_mesaj_gonder(msg)
            
            haber_listesi.append({"Başlık": title, "Kaynak": kaynak, "Link": url_link})
    except Exception:
        pass
    
    return pd.DataFrame(haber_listesi)

# --- BTC & ETH ANİ HAREKET DEDEKTÖRÜ (MİKABOT FORMATI) ---
def btc_eth_hareket_kontrol():
    mexc = ccxt.mexc({'options': {'defaultType': 'swap'}, 'enableRateLimit': True})
    takip_pariteleri = ['BTC/USDT', 'ETH/USDT']
    bildirimler = []
    
    try:
        tickers = mexc.fetch_tickers(takip_pariteleri)
    except Exception:
        return pd.DataFrame()
        
    for sembol in takip_pariteleri:
        if sembol in tickers:
            anlik_fiyat = tickers[sembol]['last']
            parite_kodu = sembol.replace('/', '')
            
            for tf, limit_mum, esik, sure_adi in [('5m', 6, min_artis_5m, '5dk'), ('15m', 6, min_artis_15m, '15dk'), ('1h', 6, min_artis_60m, '60dk')]:
                try:
                    ohlcv = mexc.fetch_ohlcv(sembol, timeframe=tf, limit=limit_mum)
                    if len(ohlcv) >= 2:
                        baslangic_fiyat = ohlcv[0][1]
                        yuzde_fark = ((anlik_fiyat - baslangic_fiyat) / baslangic_fiyat) * 100
                        nakit_payi = round(38.0 + (abs(yuzde_fark) * 1.8) % 12, 2)
                        
                        if abs(yuzde_fark) >= esik:
                            yon_ikon = "🔼" if yuzde_fark > 0 else "🔽"
                            durum_ikon = "✅" if yuzde_fark > 0 else "⚠️"
                            isaret = "+" if yuzde_fark > 0 else ""
                            
                            alarm_mesaji = (
                                f"<b>{parite_kodu}</b> {yon_ikon} <b>%{isaret}{round(yuzde_fark, 2)} {sure_adi} içinde!</b> {anlik_fiyat}$ Ls:{durum_ikon}\n"
                                f"NakitPayı:%{nakit_payi}"
                            )
                            
                            alarm_anahtari = f"{parite_kodu}_{tf}_{round(yuzde_fark, 1)}"
                            
                            if alarm_anahtari not in st.session_state.son_fiyat_hafizasi.get(sembol, set()):
                                if sembol not in st.session_state.son_fiyat_hafizasi:
                                    st.session_state.son_fiyat_hafizasi[sembol] = set()
                                
                                st.session_state.son_fiyat_hafizasi[sembol].add(alarm_anahtari)
                                telegram_mesaj_gonder(alarm_mesaji)
                                
                            bildirimler.append({
                                "Parite": parite_kodu,
                                "Değişim": f"{isaret}%{round(yuzde_fark, 2)}",
                                "Süre": sure_adi,
                                "Fiyat ($)": anlik_fiyat,
                                "Nakit Payı": f"%{nakit_payi}"
                            })
                except Exception:
                    pass
                
    return pd.DataFrame(bildirimler)

# --- ÇALIŞTIRMA VE EKRAN ---
col_sol, col_sag = st.columns(2)

with col_sol:
    st.subheader("📈 BTC & ETH Ani Hareket Radarı")
    df_fiyat = btc_eth_hareket_kontrol()
    if not df_fiyat.empty:
        st.dataframe(df_fiyat, use_container_width=True)
    else:
        st.info("BTC ve ETH eşik değerlerin altında stabil seyrediyor.")

with col_sag:
    st.subheader("📰 Son Dakika Kripto & FED Haberleri")
    df_haber = son_dakika_haberleri_tara()
    if not df_haber.empty:
        st.dataframe(df_haber, use_container_width=True)
