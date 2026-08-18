import streamlit as st
import ccxt
import pandas as pd
import numpy as np

st.set_page_config(page_title="Gelişmiş MEXC Kripto Radarı", layout="wide")

st.title("🐋 MEXC Akıllı Sinyal & Balina Radarı")

# --- SOL YAN PANEL (FİLTRELER) ---
st.sidebar.header("⚙️ Tarama Parametreleri")

zaman_dilimi = st.sidebar.selectbox(
    "Zaman Dilimi",
    options=["1m", "5m", "15m", "1h", "4h"],
    index=2
)

hacim_esigi = st.sidebar.slider(
    "Hacim Artış Eşiği (%)",
    min_value=100,
    max_value=1000,
    value=200,
    step=50,
    help="Örnek: 200 seçilirse, son mumun hacmi ortalamanın 2 katı olmalıdır."
)

coin_limiti = st.sidebar.select_slider(
    "Taranacak En Popüler Coin Sayısı",
    options=[30, 50, 100, 150, 200],
    value=50
)

st.sidebar.markdown("---")
st.sidebar.info("💡 **İpucu:** Hiçbir sonuç çıkmıyorsa Hacim Eşiğini %150'ye düşürün veya 5m/1m zaman dilimini deneyin.")

# --- RSI HESAPLAMA FONKSİYONU ---
def rsi_hesapla(seri, periyot=14):
    fark = seri.diff(1)
    kazanc = fark.clip(lower=0)
    kayip = -fark.clip(upper=0)
    ortalama_kazanc = kazanc.rolling(window=periyot, min_periods=periyot).mean()
    ortalama_kayip = kayip.rolling(window=periyot, min_periods=periyot).mean()
    rs = ortalama_kazanc / ortalama_kayip
    return 100 - (100 / (1 + rs))

# --- ANA TARAYICI MOTORU ---
def piyasa_tara():
    mexc = ccxt.mexc()
    try:
        tickers = mexc.fetch_tickers()
    except Exception as e:
        st.error(f"Piyasa verileri çekilemedi: {e}")
        return pd.DataFrame()
    
    usdt_pariteler = [s for s in tickers.keys() if '/USDT' in s]
    usdt_pariteler.sort(key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)
    hedef_coinler = usdt_pariteler[:coin_limiti]

    bulunanlar = []
    progress_bar = st.progress(0)
    durum_metni = st.empty()

    for i, sembol in enumerate(hedef_coinler):
        try:
            mumlar = mexc.fetch_ohlcv(sembol, timeframe=zaman_dilimi, limit=25)
            if len(mumlar) >= 20:
                df = pd.DataFrame(mumlar, columns=['Zaman', 'Acilis', 'Yuksek', 'Dusuk', 'Kapanis', 'Hacim'])
                
                # Hacim ortalaması
                gecmis_hacim = df['Hacim'].iloc[:-1].mean()
                son_hacim = df['Hacim'].iloc[-1]
                son_fiyat = df['Kapanis'].iloc[-1]
                acilis_fiyat = df['Acilis'].iloc[-1]
                
                # Mum içi fiyat değişimi
                mum_degisim_yuzde = ((son_fiyat - acilis_fiyat) / acilis_fiyat) * 100
                
                # RSI Değeri
                df['RSI'] = rsi_hesapla(df['Kapanis'])
                son_rsi = round(df['RSI'].iloc[-1], 1) if not np.isnan(df['RSI'].iloc[-1]) else 50.0

                hacim_kat_orani = (son_hacim / gecmis_hacim) * 100

                if hacim_kat_orani >= hacim_esigi:
                    sinyal_tipi = "🚀 Alış Baskısı" if mum_degisim_yuzde >= 0 else "🔻 Satış Baskısı"
                    
                    bulunanlar.append({
                        "Durum": sinyal_tipi,
                        "Sembol": sembol,
                        "Fiyat ($)": son_fiyat,
                        "Hacim Artışı": f"%{round(hacim_kat_orani, 1)}",
                        "Mum Değişimi": f"%{round(mum_degisim_yuzde, 2)}",
                        "RSI (14)": son_rsi
                    })
        except Exception:
            pass

        progress_bar.progress((i + 1) / len(hedef_coinler))
        durum_metni.text(f"Analiz ediliyor: {sembol} ({i+1}/{len(hedef_coinler)})")

    progress_bar.empty()
    durum_metni.empty()
    return pd.DataFrame(bulunanlar)

# --- ÇALIŞTIRMA BUTONU VE GÖRSELLEŞTİRME ---
if st.button("🔍 Radarı Çalıştır", type="primary", use_container_width=True):
    df_sonuclar = piyasa_tara()
    
    if not df_sonuclar.empty:
        st.success(f"Toplam {len(df_sonuclar)} adet potansiyel hareket tespit edildi!")
        
        # Tabloyu göster
        st.dataframe(df_sonuclar, use_container_width=True)
    else:
        st.warning(f"Seçilen ayarlarda ({zaman_dilimi} - %{hacim_esigi} Hacim Eşiği) kriterlere uyan coin bulunamadı. Eşik değerini düşürmeyi veya zaman dilimini değiştirmeyi deneyin.")
