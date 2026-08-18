import streamlit as st
import ccxt
import pandas as pd
import numpy as np
from streamlit_autorefresh import st_autorefresh

# Sayfa Yapılandırması
st.set_page_config(page_title="MEXC Squeeze & Sinyal Radarı", layout="wide")

# --- YAN MENÜ ---
st.sidebar.header("⚙️ Canlı Yayın Ayarları")

oto_yenileme = st.sidebar.checkbox("🔄 Otomatik Taramayı Aç", value=False)
yenileme_araligi = st.sidebar.selectbox(
    "Tarama Sıklığı",
    options=[15, 30, 60, 120, 300],
    index=2,
    format_func=lambda x: f"{x} Saniyede Bir"
)

if oto_yenileme:
    st_autorefresh(interval=yenileme_araligi * 1000, key="canli_tarayici")
    st.sidebar.success(f"🟢 Canlı mod aktif: Her {yenileme_araligi} sn")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Strateji & Filtreler")

piyasa_turu = st.sidebar.radio(
    "Piyasa Türü",
    options=["Vadeli (Futures)", "Spot"],
    index=0
)

mod_secimi = st.sidebar.radio(
    "Tarama Modu",
    options=["Tüm Sinyaller + Squeeze", "Sadece Sıkışanlar (Squeeze)"],
    index=0
)

zaman_dilimi = st.sidebar.selectbox(
    "Zaman Dilimi (Timeframe)",
    options=["5m", "15m", "1h", "4h", "1d", "1w"],
    index=1
)

hacim_carpani = st.sidebar.slider(
    "Minimum Hacim Patlama Katı",
    min_value=1.2,
    max_value=5.0,
    value=2.0,
    step=0.1
)

squeeze_esigi = st.sidebar.slider(
    "Maksimum Bollinger Genişliği (%)",
    min_value=1.0,
    max_value=10.0,
    value=4.0,
    step=0.5,
    help="Değer ne kadar küçükse fiyat o kadar sıkışmış ve patlamaya o kadar yakındır."
)

coin_adedi = st.sidebar.select_slider(
    "Taranacak En Yüksek Hacimli Coin Sayısı",
    options=[30, 50, 100, 150, 200],
    value=50
)

# Başlık
st.title(f"⚡ MEXC {piyasa_turu} Squeeze & Sinyal Radarı")
st.caption("Piyasadaki hacim kırılımlarını, dip dönüşlerini ve patlamaya hazır Bollinger sıkışmalarını tarar.")

# --- İNDİKATÖR HESAPLAMALARI ---
def hesapla_rsi(seri, periyot=14):
    fark = seri.diff(1)
    kazanc = fark.clip(lower=0)
    kayip = -fark.clip(upper=0)
    ortalama_kazanc = kazanc.rolling(window=periyot, min_periods=periyot).mean()
    ortalama_kayip = kayip.rolling(window=periyot, min_periods=periyot).mean()
    rs = ortalama_kazanc / ortalama_kayip
    return 100 - (100 / (1 + rs))

def hesapla_bollinger_genislik(df, periyot=20, std_kat=2):
    sma = df['Kapanis'].rolling(window=periyot).mean()
    std = df['Kapanis'].rolling(window=periyot).std()
    ust_bant = sma + (std * std_kat)
    alt_bant = sma - (std * std_kat)
    # Bant Genişliği Yüzdesi: ((Üst - Alt) / Orta) * 100
    genislik = ((ust_bant - alt_bant) / sma) * 100
    return genislik.iloc[-1]

# --- TARAMA MOTORU ---
def piyasa_tara():
    is_futures = (piyasa_turu == "Vadeli (Futures)")
    
    if is_futures:
        mexc = ccxt.mexc({'options': {'defaultType': 'swap'}, 'enableRateLimit': True})
    else:
        mexc = ccxt.mexc({'options': {'defaultType': 'spot'}, 'enableRateLimit': True})
        
    try:
        tickers = mexc.fetch_tickers()
    except Exception as e:
        st.error(f"MEXC Veri Hatası: {e}")
        return pd.DataFrame()

    usdt_pariteler = [s for s in tickers.keys() if '/USDT' in s]
    usdt_pariteler.sort(key=lambda x: tickers[x].get('quoteVolume', 0) or 0, reverse=True)
    hedef_listesi = usdt_pariteler[:coin_adedi]

    sinyaller = []

    for i, sembol in enumerate(hedef_listesi):
        try:
            mumlar = mexc.fetch_ohlcv(sembol, timeframe=zaman_dilimi, limit=35)
            if len(mumlar) >= 20:
                df = pd.DataFrame(mumlar, columns=['Zaman', 'Acilis', 'Yuksek', 'Dusuk', 'Kapanis', 'Hacim'])
                
                gecmis_hacim = df['Hacim'].iloc[:-1].mean()
                son_hacim = df['Hacim'].iloc[-1]
                son_kapanis = df['Kapanis'].iloc[-1]
                son_acilis = df['Acilis'].iloc[-1]
                son_yuksek = df['Yuksek'].iloc[-1]
                gecmis_en_yuksek = df['Yuksek'].iloc[:-1].max()
                
                # RSI & Bollinger Band Genişliği
                df['RSI'] = hesapla_rsi(df['Kapanis'])
                son_rsi = round(df['RSI'].iloc[-1], 1) if not np.isnan(df['RSI'].iloc[-1]) else 50.0
                bb_genislik = round(hesapla_bollinger_genislik(df), 2)
                
                hacim_orani = son_hacim / gecmis_hacim if gecmis_hacim > 0 else 0
                mum_degisimi = ((son_kapanis - son_acilis) / son_acilis) * 100

                sinyal_adi = None
                aksiyon = None

                # 1. Bollinger Squeeze Kontrolü (Bant daralması)
                if bb_genislik <= squeeze_esigi:
                    sinyal_adi = f"🗜️ SQUEEZE (Bant: %{bb_genislik})"
                    aksiyon = "🟡 PATLAMA BEKLENİYOR"

                # Eğer "Sadece Sıkışanlar" seçilmediyse diğer sinyalleri de tara
                if mod_secimi != "Sadece Sıkışanlar (Squeeze)":
                    if (hacim_orani >= hacim_carpani) and (son_kapanis >= gecmis_en_yuksek) and (45 <= son_rsi <= 75):
                        sinyal_adi = "🚀 DİRENÇ KIRILIMI (PUMP)"
                        aksiyon = "🟢 LONG" if is_futures else "🟢 GÜÇLÜ AL"

                    elif (hacim_orani >= hacim_carpani) and (son_rsi <= 32) and (mum_degisimi > 0):
                        sinyal_adi = "🩸 DİP DÖNÜŞ TEPKİSİ"
                        aksiyon = "🟢 LONG" if is_futures else "🟢 ALIM BÖLGESİ"

                    elif (hacim_orani >= hacim_carpani) and (son_rsi >= 75) and (mum_degisimi < 0):
                        sinyal_adi = "🪤 BOĞA TUZAĞI (TEPEDEN RET)"
                        aksiyon = "🔴 SHORT" if is_futures else "🔴 DİKKAT / SAT"

                    elif hacim_orani >= (hacim_carpani * 1.5):
                        sinyal_adi = "⚡ ANORMAL HACİM HAREKETİ"
                        if is_futures:
                            aksiyon = "🟢 LONG" if mum_degisimi >= 0 else "🔴 SHORT"
                        else:
                            aksiyon = "🟢 HACİMLİ YÜKSELİŞ" if mum_degisimi >= 0 else "🔴 HACİMLİ SATIŞ"

                if sinyal_adi:
                    temiz_parite = sembol.split(':')[0]
                    mexc_kod = temiz_parite.replace('/', '_')
                    
                    if is_futures:
                        mexc_link = f"https://www.mexc.com/tr-TR/futures/{mexc_kod}"
                    else:
                        mexc_link = f"https://www.mexc.com/tr-TR/exchange/{mexc_kod}"
                    
                    sinyaller.append({
                        "Yön / Durum": aksiyon,
                        "Sinyal": sinyal_adi,
                        "Sembol": temiz_parite,
                        "Fiyat ($)": son_kapanis,
                        "Bant Genişliği": f"%{bb_genislik}",
                        "Hacim Katı": f"{round(hacim_orani, 1)}x",
                        "Mum %": f"%{round(mum_degisimi, 2)}",
                        "RSI": son_rsi,
                        "Grafik": mexc_link
                    })
        except Exception:
            pass

    return pd.DataFrame(sinyaller)

# --- ÇALIŞTIRMA & GÖRÜNTÜLEME ---
manuel_tara = st.button("🔍 Şimdi Tara", type="primary", use_container_width=True)

if oto_yenileme or manuel_tara:
    with st.spinner("Piyasa taranıyor..."):
        df_sonuc = piyasa_tara()
        
    if not df_sonuc.empty:
        st.success(f"Tespit Edilen Fırsatlar ({pd.Timestamp.now().strftime('%H:%M:%S')}):")
        st.dataframe(
            df_sonuc,
            column_config={
                "Grafik": st.column_config.LinkColumn(
                    "MEXC Link",
                    display_text="Grafiği Aç ↗"
                )
            },
            use_container_width=True
        )
    else:
        st.info(f"Kriterlere uyan coin bulunamadı ({pd.Timestamp.now().strftime('%H:%M:%S')}).")
