import io
import time
import urllib.parse
import ccxt
import matplotlib
import mplfinance as mpf
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

matplotlib.use('Agg')

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title='MEXC VIP Algoritmik & TOTAL3 Sinyal Radarı', layout='wide'
)

# Sinyal tekrar & skor hafızası
if 'sinyal_skorlari' not in st.session_state:
  st.session_state.sinyal_skorlari = {}

# --- YAN PANEL: TELEGRAM AYARLARI ---
st.sidebar.header('📱 Telegram Bildirim Ayarları')
telegram_aktif = st.sidebar.checkbox('🚀 Telegram\'a Sinyal Gönder', value=True)
bot_token = st.sidebar.text_input(
    'Telegram Bot Token',
    type='password',
    placeholder='BotFather\'dan aldığınız token',
)
chat_id = st.sidebar.text_input('Telegram Chat ID', value='-1004434260285')
topic_id = st.sidebar.text_input(
    'Telegram Konu (Topic) ID',
    value='73',
    help='Mesajların gideceği Konu ID numarası',
)

st.sidebar.markdown('---')
st.sidebar.header('⚙️ Canlı Yayın & Tarama')

oto_yenileme = st.sidebar.checkbox('🔄 Otomatik Canlı Taramayı Aç', value=False)
yenileme_araligi = st.sidebar.selectbox(
    'Tarama Sıklığı',
    options=[15, 30, 60, 120, 300],
    index=2,
    format_func=lambda x: f'{x} Saniyede Bir',
)

if oto_yenileme:
  st_autorefresh(interval=yenileme_araligi * 1000, key='canli_tarayici')
  st.sidebar.success(f'🟢 Canlı mod aktif: Her {yenileme_araligi} sn')

st.sidebar.markdown('---')
st.sidebar.header('🎯 Tarama & Strateji Parametreleri')

piyasa_turu = st.sidebar.radio(
    'Piyasa Türü', options=['Vadeli (Futures)', 'Spot'], index=0
)

zaman_dilimi = st.sidebar.selectbox(
    'Zaman Dilimi (Timeframe)',
    options=['5m', '15m', '1h', '4h', '1d'],
    index=1,
)

hacim_carpani = st.sidebar.slider(
    'Minimum Hacim Artış Katı',
    min_value=1.1,
    max_value=3.5,
    value=1.3,
    step=0.1,
)

fonlama_esigi = st.sidebar.slider(
    'Eksi Fonlama Eşiği (%)',
    min_value=-0.15,
    max_value=-0.005,
    value=-0.015,
    step=0.005,
    format='%.3f',
)

coin_adedi = st.sidebar.select_slider(
    'Taranacak En Yüksek Hacimli Coin Sayısı',
    options=[30, 50, 100, 150, 200],
    value=100,
)

st.title(f'⚡ MEXC {piyasa_turu} VIP Algoritmik Sinyal & Skor Radarı')


# --- CANLI TOTAL3 ÇEKİCİ ---
@st.cache_data(ttl=60)
def fetch_total3_data():
  try:
    url = 'https://api.coingecko.com/api/v3/global'
    res = requests.get(url, timeout=5).json()
    data = res.get('data', {})

    total_market_cap = data.get('total_market_cap', {}).get('usd', 0)
    market_cap_percentage = data.get('market_cap_percentage', {})

    btc_pct = market_cap_percentage.get('btc', 0)
    eth_pct = market_cap_percentage.get('eth', 0)

    total3_val = total_market_cap * (1 - (btc_pct + eth_pct) / 100)
    total3_billions = round(total3_val / 1e9, 2)
    total_cap_change_24h = data.get(
        'market_cap_change_percentage_24h_usd', 0.0
    )

    return {
        'total3_mcap': total3_billions,
        'change_24h': round(total_cap_change_24h, 2),
        'btc_dom': round(btc_pct, 1),
        'eth_dom': round(eth_pct, 1),
    }
  except Exception:
    return {
        'total3_mcap': 0,
        'change_24h': 0.0,
        'btc_dom': 0.0,
        'eth_dom': 0.0,
    }


total3_info = fetch_total3_data()
col_m1, col_m2, col_m3 = st.columns(3)
with col_m1:
  st.metric(
      '🌐 TOTAL3 Market Cap (Altcoinler)',
      f"{total3_info['total3_mcap']} Milyar $",
      f"{total3_info['change_24h']}% (24s)",
  )
with col_m2:
  st.metric('🟠 BTC Dominance', f"%{total3_info['btc_dom']}")
with col_m3:
  st.metric('🔷 ETH Dominance', f"%{total3_info['eth_dom']}")


# --- GRAFİK OLUŞTURMA ---
def grafik_olustur(df_mum, sembol, zaman_dilimi):
  df_grafik = df_mum.copy()
  df_grafik['Zaman'] = pd.to_datetime(df_grafik['Zaman'], unit='ms')
  df_grafik.set_index('Zaman', inplace=True)
  df_grafik.rename(
      columns={
          'Acilis': 'Open',
          'Yuksek': 'High',
          'Dusuk': 'Low',
          'Kapanis': 'Close',
          'Hacim': 'Volume',
      },
      inplace=True,
  )

  mc = mpf.make_marketcolors(up='#00ff88', down='#ff3366', inherit=True)
  s = mpf.make_mpf_style(
      base_mpf_style='nightclouds', marketcolors=mc, gridcolor='#2b2b2b'
  )

  buf = io.BytesIO()
  mpf.plot(
      df_grafik.tail(30),
      type='candle',
      volume=True,
      style=s,
      title=f'{sembol} ({zaman_dilimi})',
      savefig=dict(fname=buf, dpi=120, bbox_inches='tight'),
  )
  buf.seek(0)
  return buf


# --- TELEGRAM MESAJ GÖNDERME ---
def telegram_fotograf_gonder(foto_buf, caption_metni):
  if telegram_aktif and bot_token and chat_id:
    url = f'https://api.telegram.org/bot{bot_token.strip()}/sendPhoto'

    params = {}
    if topic_id and str(topic_id).strip() != '':
      try:
        params['message_thread_id'] = int(str(topic_id).strip())
      except ValueError:
        pass

    data = {
        'chat_id': chat_id.strip(),
        'caption': caption_metni,
        'parse_mode': 'HTML',
    }
    files = {'photo': ('chart.png', foto_buf, 'image/png')}

    try:
      requests.post(url, params=params, data=data, files=files, timeout=12)
    except Exception:
      pass


# --- TEKNİK İNDİKATÖR VE TP/SL HESAPLAYICILARI ---
def hesapla_rsi(seri, periyot=14):
  fark = seri.diff(1)
  kazanc = fark.clip(lower=0)
  kayip = -fark.clip(upper=0)
  ortalama_kazanc = kazanc.rolling(window=periyot, min_periods=periyot).mean()
  ortalama_kayip = kayip.rolling(window=periyot, min_periods=periyot).mean()
  rs = ortalama_kazanc / ortalama_kayip
  return 100 - (100 / (1 + rs))


def hesapla_atr(df, periyot=14):
  h_l = df['Yuksek'] - df['Dusuk']
  h_pc = (df['Yuksek'] - df['Kapanis'].shift(1)).abs()
  l_pc = (df['Dusuk'] - df['Kapanis'].shift(1)).abs()
  tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
  atr_val = tr.rolling(window=periyot).mean().iloc[-1]
  return atr_val if not np.isnan(atr_val) else df['Kapanis'].iloc[-1] * 0.02


def hesapla_tp_sl(fiyat, atr, yon='LONG'):
  if yon == 'LONG':
    sl = round(fiyat - (atr * 1.5), 6)
    tp1 = round(fiyat + (atr * 1.5), 6)
    tp2 = round(fiyat + (atr * 3.0), 6)
  else:
    sl = round(fiyat + (atr * 1.5), 6)
    tp1 = round(fiyat - (atr * 1.5), 6)
    tp2 = round(fiyat - (atr * 3.0), 6)
  return tp1, tp2, sl


# --- PİYASA TARAMA MOTORU ---
def piyasa_tara():
  is_futures = piyasa_turu == 'Vadeli (Futures)'
  t3_data = fetch_total3_data()
  total3_change = t3_data['change_24h']

  if is_futures:
    mexc = ccxt.mexc(
        {'options': {'defaultType': 'swap'}, 'enableRateLimit': True}
    )
  else:
    mexc = ccxt.mexc(
        {'options': {'defaultType': 'spot'}, 'enableRateLimit': True}
    )

  try:
    tickers = mexc.fetch_tickers()
  except Exception as e:
    st.error(f'MEXC Veri Hatası: {e}')
    return pd.DataFrame()

  usdt_pariteler = [s for s in tickers.keys() if '/USDT' in s]
  usdt_pariteler.sort(
      key=lambda x: tickers[x].get('quoteVolume', 0) or 0, reverse=True
  )
  hedef_listesi = usdt_pariteler[:coin_adedi]

  sinyaller = []

  for i, sembol in enumerate(hedef_listesi):
    try:
      t_info = tickers[sembol]
      mumlar = mexc.fetch_ohlcv(sembol, timeframe=zaman_dilimi, limit=35)

      if len(mumlar) >= 20:
        df = pd.DataFrame(
            mumlar,
            columns=['Zaman', 'Acilis', 'Yuksek', 'Dusuk', 'Kapanis', 'Hacim'],
        )

        gecmis_hacim = df['Hacim'].iloc[:-1].mean()
        son_hacim = df['Hacim'].iloc[-1]
        son_kapanis = df['Kapanis'].iloc[-1]
        son_acilis = df['Acilis'].iloc[-1]
        gecmis_en_yuksek = df['Yuksek'].iloc[:-1].max()
        gecmis_en_dusuk = df['Dusuk'].iloc[:-1].min()

        df['RSI'] = hesapla_rsi(df['Kapanis'])
        son_rsi = (
            round(df['RSI'].iloc[-1], 1)
            if not np.isnan(df['RSI'].iloc[-1])
            else 50.0
        )
        onceki_rsi = (
            round(df['RSI'].iloc[-2], 1)
            if not np.isnan(df['RSI'].iloc[-2])
            else 50.0
        )
        min_gecmis_rsi = df['RSI'].iloc[-12:-1].min()
        max_gecmis_rsi = df['RSI'].iloc[-12:-1].max()

        df['EMA20'] = df['Kapanis'].ewm(span=20, adjust=False).mean()
        df['EMA50'] = df['Kapanis'].ewm(span=50, adjust=False).mean()

        atr = hesapla_atr(df)
        hacim_orani = son_hacim / gecmis_hacim if gecmis_hacim > 0 else 0
        mum_degisimi = ((son_kapanis - son_acilis) / son_acilis) * 100

        # 24s Değişim
        coin_24h_change = (
            float(t_info.get('percentage', 0) or 0)
            if 'percentage' in t_info
            else mum_degisimi
        )

        # Fonlama Oranı
        funding_rate = None
        if is_futures and 'info' in t_info:
          funding_rate = float(t_info['info'].get('fundingRate', 0) or 0) * 100

        sinyal_adi = None
        aksiyon = None

        # 1. 🔥 TOTAL3 AYRIŞMASI (Onaylı)
        if (
            total3_change <= -0.5
            and coin_24h_change >= 1.5
            and hacim_orani >= 1.2
            and mum_degisimi > 0
        ):
          sinyal_adi = (
              f'🔥 ALFA BOĞA (TOTAL3 Düşerken Güçlenen / +%{coin_24h_change})'
          )
          aksiyon = '🟢 GÜÇLÜ LONG'

        elif (
            total3_change >= 0.8
            and coin_24h_change <= -1.2
            and hacim_orani >= 1.2
            and mum_degisimi < 0
        ):
          sinyal_adi = (
              f'🩸 ALFA AYI (TOTAL3 Yükselirken Düşen / %{coin_24h_change})'
          )
          aksiyon = '🔴 GÜÇLÜ SHORT'

        # 2. 💥 LİKİDASYON SQUEEZE (Onaylı)
        elif (
            funding_rate is not None
            and funding_rate <= fonlama_esigi
            and hacim_orani >= 1.3
            and mum_degisimi > 0
        ):
          sinyal_adi = (
              f'💥 SHORT SQUEEZE ADAYI (Fonlama: %{round(funding_rate, 4)})'
          )
          aksiyon = '🟢 GÜÇLÜ LONG'

        elif (
            funding_rate is not None
            and funding_rate >= 0.06
            and hacim_orani >= 1.3
            and mum_degisimi < 0
        ):
          sinyal_adi = (
              f'💥 LONG TASFİYE BASKISI (Fonlama: %{round(funding_rate, 4)})'
          )
          aksiyon = '🔴 GÜÇLÜ SHORT'

        # 3. 🚀 LONG PUMP & KIRILIM
        elif (
            (hacim_orani >= hacim_carpani)
            and (son_kapanis >= gecmis_en_yuksek * 0.998)
            and (mum_degisimi > 0.5)
        ):
          sinyal_adi = '🚀 DİRENÇ KIRILIMI / PUMP'
          aksiyon = '🟢 LONG'

        elif (
            (df['EMA20'].iloc[-1] >= df['EMA50'].iloc[-1])
            and (hacim_orani >= hacim_carpani)
            and (mum_degisimi > 0.8)
            and (son_rsi <= 70)
        ):
          sinyal_adi = '⚡ HACİMLİ BOĞA TRENDİ'
          aksiyon = '🟢 LONG'

        # 4. 🔴 SHORT DUMP & DÜŞÜŞ
        elif (
            (hacim_orani >= hacim_carpani)
            and (son_kapanis <= gecmis_en_dusuk * 1.002)
            and (mum_degisimi < -0.5)
        ):
          sinyal_adi = '🩸 DESTEK KIRILIMI / DUMP'
          aksiyon = '🔴 SHORT'

        elif (
            (df['EMA20'].iloc[-1] <= df['EMA50'].iloc[-1])
            and (hacim_orani >= hacim_carpani)
            and (mum_degisimi < -0.8)
            and (son_rsi >= 30)
        ):
          sinyal_adi = '⚡ HACİMLİ AYI BASKISI'
          aksiyon = '🔴 SHORT'

        # 5. 📈 RSI DIVERGENCE (DÜZELTİLMİŞ GÜVENLİ FİLTRE: Yeşil Mum + RSI Kafayı Kaldırdı)
        elif (
            (son_kapanis <= gecmis_en_dusuk * 1.01)
            and (mum_degisimi > 0.3)  # MUTLAKA YEŞİL DÖNÜŞ MUMU
            and (son_rsi > onceki_rsi + 2)  # RSI YUKARI DÖNDÜ
            and (20 <= son_rsi <= 40)
        ):  # DİPTE SÜRÜNEN DEĞİL, DÖNEN RSI
          sinyal_adi = '📈 POZİTİF UYUMSUZLUK (ONAYLI DİP DÖNÜŞ)'
          aksiyon = '🟢 LONG'

        elif (
            (son_kapanis >= gecmis_en_yuksek * 0.99)
            and (mum_degisimi < -0.3)  # MUTLAKA KIRMIZI TEPE MUMU
            and (son_rsi < onceki_rsi - 2)  # RSI AŞAĞI DÖNDÜ
            and (60 <= son_rsi <= 80)
        ):
          sinyal_adi = '📉 NEGATİF UYUMSUZLUK (ONAYLI TEPE DÖNÜŞ)'
          aksiyon = '🔴 SHORT'

        if aksiyon is not None:
          temiz_parite = sembol.split(':')[0]
          mexc_kod = temiz_parite.replace('/', '_')

          if is_futures:
            mexc_link = f'https://www.mexc.com/tr-TR/futures/{mexc_kod}'
          else:
            mexc_link = f'https://www.mexc.com/tr-TR/exchange/{mexc_kod}'

          yon_turu = 'LONG' if 'LONG' in aksiyon else 'SHORT'
          tp1, tp2, sl = hesapla_tp_sl(son_kapanis, atr, yon=yon_turu)

          sinyal_anahtari = f'{temiz_parite}_{sinyal_adi}_{zaman_dilimi}'

          # Skorlama
          if sinyal_anahtari in st.session_state.sinyal_skorlari:
            st.session_state.sinyal_skorlari[sinyal_anahtari]['count'] += 1
          else:
            st.session_state.sinyal_skorlari[sinyal_anahtari] = {
                'count': 1,
                'first_time': pd.Timestamp.now().strftime('%H:%M'),
            }

          skor = st.session_state.sinyal_skorlari[sinyal_anahtari]['count']

          if skor == 1:
            skor_metni = '1x (İlk Tespit 🎯)'
            skor_tablo = '⭐ 1x'
          elif skor == 2:
            skor_metni = '2x (2. Kez Teyit Edildi ⚡)'
            skor_tablo = '⭐⭐ 2x'
          elif skor >= 3:
            skor_metni = f'{skor}x ({skor}. Kez Güçlü Teyit 🔥)'
            skor_tablo = f'🔥🔥 {skor}x'

          # Telegram Gönderimi
          if telegram_aktif:
            fonlama_bilgi = (
                f'\n💸 <b>Fonlama:</b> %{round(funding_rate, 4)}'
                if funding_rate is not None
                else ''
            )
            tg_caption = (
                f'🚨 <b>MEXC {piyasa_turu.upper()} SİNYALİ</b>\n\n'
                f'📌 <b>Parite:</b> {temiz_parite}\n'
                f'🎯 <b>Yön:</b> {aksiyon}\n'
                f'⚡ <b>Strateji:</b> {sinyal_adi}\n'
                f'🏆 <b>Sinyal Skoru:</b> {skor_metni}\n'
                f'🌐 <b>TOTAL3 (24s):</b> %{total3_change}\n'
                f'⏱ <b>Zaman:</b> {zaman_dilimi}\n'
                f'💰 <b>Giriş:</b> {son_kapanis} $\n'
                f'📊 <b>Hacim Katı:</b> {round(hacim_orani, 1)}x'
                f'{fonlama_bilgi}\n'
                f'📈 <b>RSI (14):</b> {son_rsi}\n\n'
                f'🎯 <b>HEDEF 1 (TP1):</b> {tp1} $\n'
                f'🎯 <b>HEDEF 2 (TP2):</b> {tp2} $\n'
                f'🛑 <b>STOP-LOSS:</b> {sl} $\n\n'
                f"🔗 <a href='{mexc_link}'>MEXC Grafiği Aç ↗</a>"
            )
            try:
              foto_buffer = grafik_olustur(df, temiz_parite, zaman_dilimi)
              telegram_fotograf_gonder(foto_buffer, tg_caption)
            except Exception:
              pass

          sinyaller.append({
              'Skor (Teyit)': skor_tablo,
              'Yön': aksiyon,
              'Sinyal Detayı': sinyal_adi,
              'Sembol': temiz_parite,
              'Giriş ($)': son_kapanis,
              'TP1 ($)': tp1,
              'SL ($)': sl,
              'Hacim Katı': f'{round(hacim_orani, 1)}x',
              'RSI': son_rsi,
              'Grafik': mexc_link,
          })
    except Exception:
      pass

  return pd.DataFrame(sinyaller)


# --- ÇALIŞTIRMA & GÖRÜNTÜLEME ---
manuel_tara = st.button('🔍 Şimdi Tara', type='primary', use_container_width=True)

if oto_yenileme or manuel_tara:
  with st.spinner('Piyasa güvenli filtrelerle taranıyor...'):
    df_sonuc = piyasa_tara()

  if not df_sonuc.empty:
    st.success(
        f'Tespit Edilen Fırsatlar ({pd.Timestamp.now().strftime("%H:%M:%S")}):'
    )
    st.dataframe(
        df_sonuc,
        column_config={
            'Grafik': st.column_config.LinkColumn(
                'MEXC Link', display_text='Grafiği Aç ↗'
            )
        },
        use_container_width=True,
    )
  else:
    st.info(
        'Seçilen kriterlere uygun onaylanmış fırsat bulunamadı.'
        f' ({pd.Timestamp.now().strftime("%H:%M:%S")})'
    )
