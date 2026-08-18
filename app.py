


import sys
import subprocess
import pkg_resources

# Eksik kütüphaneleri otomatik kurma bölümü
required = {'streamlit', 'ccxt', 'pandas'}
installed = {pkg.key for pkg in pkg_resources.working_set}
missing = required - installed

if missing:
    python = sys.executable
    subprocess.check_call([python, '-m', 'pip', 'install', *missing], stdout=subprocess.DEVNULL)
import streamlit as st
import ccxt
import pandas as pd

# Sayfa Ayarları
st.set_page_config(page_title="Balina Avcısı", layout="wide")

st.title("🐋 MEXC Balina Sinyal Tarayıcı")
st.write("Son 15 dakikalık periyotta, geçmiş ortalamasına göre %300'den fazla hacim (para) girişi olan coinleri yakalar.")

def balinalari_bul():
    mexc = ccxt.mexc()
    # Piyasayı hızlı taramak için öncelikle genel verileri çek
    tickers = mexc.fetch_tickers()
    
    # Sadece USDT paritelerini al ve en yüksek hacimli 50 coini seç (hızlı sonuç almak için)
    usdt_pariteler = [s for s in tickers.keys() if '/USDT' in s]
    usdt_pariteler.sort(key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)
    hedef_coinler = usdt_pariteler[:50] 

    veri_listesi = []
    
    # Tarama uzun süreceği için ekrana ilerleme çubuğu ekleyelim
    progress_bar = st.progress(0)
    durum_metni = st.empty()
    
    for i, sembol in enumerate(hedef_coinler):
        try:
            # Her coin için son 20 adet 15 dakikalık mumu çek
            mumlar = mexc.fetch_ohlcv(sembol, timeframe='15m', limit=20)
            
            if len(mumlar) >= 20:
                # Veriyi analiz için tabloya dönüştür
                df_mum = pd.DataFrame(mumlar, columns=['Zaman', 'Acilis', 'Yuksek', 'Dusuk', 'Kapanis', 'Hacim'])
                
                # Son anlık mum hariç, önceki 19 mumun ortalama hacmini bul
                gecmis_hacim_ortalama = df_mum['Hacim'].iloc[:-1].mean()
                son_hacim = df_mum['Hacim'].iloc[-1]
                son_fiyat = df_mum['Kapanis'].iloc[-1]
                
                # Eğer son 15 dakikadaki hacim, geçmiş ortalamanın 3 katından fazlaysa listeye ekle
                if son_hacim > (gecmis_hacim_ortalama * 3):
                    oran = (son_hacim / gecmis_hacim_ortalama) * 100
                    
                    veri_listesi.append({
                        "Sinyal": "🚨 BALİNA GİRİŞİ",
                        "Sembol": sembol,
                        "Fiyat": son_fiyat,
                        "Hacim Artışı (%)": round(oran, 2),
                    })
                    
        except Exception:
            pass # Bağlantı hatası olan coinleri atla ve devam et
            
        # İlerleme çubuğunu güncelle
        progress_bar.progress((i + 1) / len(hedef_coinler))
        durum_metni.text(f"Derin sular taranıyor: {sembol} ({i+1}/{len(hedef_coinler)})")
        
    # İşlem bitince çubuğu temizle
    progress_bar.empty()
    durum_metni.empty()
    
    return pd.DataFrame(veri_listesi)

# Taramayı başlatmak için buton
if st.button("Taramayı Başlat / Yenile", type="primary"):
    df_sonuc = balinalari_bul()
    
    if not df_sonuc.empty:
        st.success(f"{len(df_sonuc)} adet balina hareketi tespit edildi!")
        # Tabloyu büyükten küçüğe sırala ve ekrana bas
        df_sonuc = df_sonuc.sort_values(by="Hacim Artışı (%)", ascending=False)
        st.dataframe(df_sonuc, use_container_width=True)
    else:
        st.info("Şu an için piyasada anormal bir hacim girişi yok. Birazdan tekrar deneyin.")