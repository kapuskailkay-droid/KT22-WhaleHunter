import streamlit as st
import ccxt
import pandas as pd
import numpy as np

# Sayfa Yapılandırması
st.set_page_config(page_title="MEXC Akıllı Sinyal Radarı", layout="wide")

# --- YAN MENÜ (FİLTRELER & AYARLAR) ---
st.sidebar.header("🎯 Strateji & Piyasa Ayarları")

piyasa_turu = st.sidebar.radio(
    "Piyasa Türü",
    options=["Vadeli (Futures)", "Spot"],
    index=0,
    help="Taramak istediğiniz piyasayı seçin."
)

zaman_dilimi = st.sidebar.selectbox(
    "Zaman Dilimi (Timeframe)",
    options=["5m", "15m", "1h", "4h", "1d", "1w"],
    index=1,
    help="Scalp için 5m/15m, trend için 1h/4h, büyük dalgalar için 1d/1w seçin."
)

hacim_carpani = st.sidebar.slider(
    "Minimum Hacim Patlama Katı",
    min_value=1.2,
    max_value=5.0,
    value=2.0,
    step=0.1,
    help="Son mumun hacmi, geçmiş mumların ortalamasının kaç katı olsun?"
)

coin_adedi = st.sidebar.select_slider(
    "Taranacak En Yüksek Hacimli Coin Sayısı",
    options=[30, 50, 100, 150, 200],
    value=50
)

st.sidebar.markdown("---")
if piyasa_turu == "Vadeli (Futures)":
    st.sidebar.warning("⚠️ **Risk Uyarısı:** Vadeli işlemlerde yüksek kaldıraçtan kaçının ve mutlaka Stop-Loss kullanın.")
else:
    st.sidebar.info("💡 **Spot Bilgi:** Spot piyasada düşüşler yerine ağırlıklı olarak yeşil (Long/Alım) sinyallerine odaklanın.")

# Sayfa Başlığı
st.title(f"⚡ MEXC {piyasa_turu} Algoritmik Sinyal Radarı")
st.caption(f"{piyasa_turu} piyasasında hacim patlamalarını, kırılımları ve tepe/dip dönüşlerini tarar.")

# --- RSI HESAPLAMA ---
def hesapla_rsi(seri, periyot=14):
    fark = seri.diff(1)
    kazanc = fark.clip(lower=0)
    kayip = -fark.clip(upper=0)
    ortalama_kazanc = kazanc.rolling(window=periyot, min_periods=periyot).mean()
    ortalama_kayip = kayip.rolling(window=periyot, min_periods=periyot).mean()
    rs = ortalama_kazanc / ortalama_kayip
    return 100 - (100 / (1 + rs))

# --- TARAMA MOTORU ---
def piyasa_tara():
    is_futures = (piyasa_turu == "Vadeli (Futures)")
    
    # Piyasa türüne göre CCXT yapılandırması
    if is_futures:
        mexc = ccxt.mexc({'options': {'defaultType': 'swap'}, 'enableRateLimit': True})
    else:
        mexc = ccxt.mexc({'options': {'defaultType': 'spot'}, 'enableRateLimit': True})
        
    try:
        tickers = mexc.fetch_tickers()
    except Exception as e:
        st.error(f"MEXC Veri Hatası: {e}")
        return pd.DataFrame()

    # USDT paritelerini filtreleme ve sıralama
    usdt_pariteler = [s for s in tickers.keys() if '/USDT' in s]
    usdt_pariteler.sort(key=lambda x: tickers[x].get('quoteVolume', 0) or 0, reverse=True)
    hedef_listesi = usdt_pariteler[:coin_adedi]

    sinyaller = []
    progress_bar = st.progress(0)
    durum_metni = st.empty()

    for i, sembol in enumerate(hedef_listesi):
        try:
            mumlar = mexc.fetch_ohlcv(sembol, timeframe=zaman_dilimi, limit=35)
            if len(mumlar) >= 20:
                df = pd.DataFrame(mumlar, columns=['Zaman', 'Acilis', 'Yuksek', 'Dusuk', 'Kapanis', 'Hacim'])
                
                # Değerler
                gecmis_hacim = df['Hacim'].iloc[:-1].mean()
                son_hacim = df['Hacim'].iloc[-1]
                son_kapanis = df['Kapanis'].iloc[-1]
                son_acilis = df['Acilis'].iloc[-1]
                son_yuksek = df['Yuksek'].iloc[-1]
                gecmis_en_yuksek = df['Yuksek'].iloc[:-1].max()
                
                # RSI
                df['RSI'] = hesapla_rsi(df['Kapanis'])
                son_rsi = round(df['RSI'].iloc[-1], 1) if not np.isnan(df['RSI'].iloc[-1]) else 50.0
                
                # Hacim kat oranı ve fiyat değişimi
                hacim_orani = son_hacim / gecmis_hacim if gecmis_hacim > 0 else 0
                mum_degisimi = ((son_kapanis - son_acilis) / son_acilis) * 100

                # --- STRATEJİ KONTROLLERİ ---
                sinyal_adi = None
                aksiyon = None

                # 1. Strateji: Direnç Kırılımı (Pump)
                if (hacim_orani >= hacim_carpani) and (son_kapanis >= gecmis_en_yuksek) and (45 <= son_rsi <= 75):
                    sinyal_adi = "🚀 DİRENÇ KIRILIMI (PUMP)"
                    aksiyon = "🟢 LONG" if is_futures else "🟢 GÜÇLÜ AL"

                # 2. Strateji: Dip Avcısı (Oversold Tepki)
                elif (hacim_orani >= hacim_carpani) and (son_rsi <= 32) and (mum_degisimi > 0):
                    sinyal_adi = "🩸 DİP DÖNÜŞ TEPKİSİ"
                    aksiyon = "🟢 LONG" if is_futures else "🟢 ALIM BÖLGESİ"

                # 3. Strateji: Tepe Boğa Tuzağı (Reversal)
                elif (hacim_orani >= hacim_carpani) and (son_rsi >= 75) and (mum_degisimi < 0):
                    sinyal_adi = "🪤 BOĞA TUZAĞI (TEPEDEN RET)"
                    aksiyon = "🔴 SHORT" if is_futures else "🔴 DİKKAT / SAT"

                # 4. Genel Anormal Hacim Hareketi
                elif hacim_orani >= (hacim_carpani * 1.5):
                    sinyal_adi = "⚡ ANORMAL HACİM HAREKETİ"
                    if is_futures:
                        aksiyon = "🟢 LONG" if mum_degisimi >= 0 else "🔴 SHORT"
                    else:
                        aksiyon = "🟢 HACİMLİ YÜKSELİŞ" if mum_degisimi >= 0 else "🔴 HACİMLİ SATIŞ"

                if sinyal_adi:
                    temiz_parite = sembol.split(':')[0]
                    mexc_kod = temiz_parite.replace('/', '_')
                    
                    # Doğru URL formatı (Vadeli vs Spot)
                    if is_futures:
                        mexc_link = f"https://www.mexc.com/tr-TR/futures/{mexc_kod}"
                        link_baslik = "MEXC Vadeli"
                    else:
                        mexc_link = f"https://www.mexc.com/tr-TR/exchange/{mexc_kod}"
                        link_baslik = "MEXC Spot"
                    
                    sinyaller.append({
                        "Yön": aksiyon,
                        "Sinyal Türü": sinyal_adi,
                        "Sembol": temiz_parite,
                        "Fiyat ($)": son_kapanis,
                        "Hacim Katı": f"{round(hacim_orani, 1)}x",
                        "Mum %": f"%{round(mum_degisimi, 2)}",
                        "RSI (14)": son_rsi,
                        "Grafik": mexc_link
                    })
        except Exception:
            pass

        progress_bar.progress((i + 1) / len(hedef_listesi))
        durum_metni.text(f"{piyasa_turu} taranıyor: {sembol} ({i+1}/{len(hedef_listesi)})")

    progress_bar.empty()
    durum_metni.empty()
    return pd.DataFrame(sinyaller)

# --- ÇALIŞTIRMA BUTONU ---
buton_metni = f"🔥 {piyasa_turu} Sinyallerini Tara"
if st.button(buton_metni, type="primary", use_container_width=True):
    df_sonuc = piyasa_tara()
    
    if not df_sonuc.empty:
        st.success(f"{piyasa_turu} piyasasında {len(df_sonuc)} adet işlem fırsatı tespit edildi!")
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
        st.info(f"Şu anda {piyasa_turu} piyasasında seçtiğiniz kriterlere uyan net bir sinyal bulunamadı. Hacim çarpanını esneterek tekrar deneyebilirsiniz.")
