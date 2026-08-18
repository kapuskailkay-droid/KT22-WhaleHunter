import io
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
    page_title='MEXC VIP Çok Kanallı Algoritmik Radar', layout='wide'
)

if 'gonderilen_sinyaller' not in st.session_state:
  st.session_state.gonderilen_sinyaller = set()

# --- YAN PANEL: TELEGRAM TOPIC AYARLARI ---
st.sidebar.header('📱 Telegram Konu (Topic) ID Ayarları')
telegram_aktif = st.sidebar.checkbox('🚀 Telegram\'a Sinyal Gönder', value=True)
bot_token = st.sidebar.text_input(
    'Telegram Bot Token',
    type='password',
    placeholder='BotFather\'dan aldığınız token',
)
chat_id = st.sidebar.text_input('Telegram Chat ID', value='-1004434260285')

col_t1, col_t2 = st.sidebar.columns(2)
with col_t1:
  liq_thread_id = st.text_input(
      '💥 Likidasyon Sekme ID',
      value='73',
      help='Likidasyon sinyallerinin gideceği Topic ID',
  )
  long_thread_id = st.text_input(
      '🟢 Long / Pump Sekme ID',
      value='73',
      help='Long sinyallerinin gideceği Topic ID',
  )
with col_t2:
  short_thread_id = st.text_input(
      '🔴 Short Sekme ID',
      value='73',
      help='Short sinyallerinin gideceği Topic ID',
  )
  div_thread_id = st.text_input(
      '📈 Uyumsuzluk (Div) ID',
      value='73',
      help='RSI Divergence sinyallerinin gideceği Topic ID',
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

fonlama_esigi = st.sidebar.slider(
    'Eksi Fonlama Eşiği (%)',
    min_value=-0.20,
    max_value=-0.01,
    value=-0.03,
    step=0.01,
)

hacim_carpani = st.sidebar.slider(
    'Minimum Hacim Patlama Katı',
    min_value=1.2,
    max_value=5.0,
    value=2.0,
    step=0.1,
)

coin_adedi = st.sidebar.select_slider(
    'Taranacak En Yüksek Hacimli Coin Sayısı',
    options=[30, 50, 100, 150, 200],
    value=100,
)

st.title(f'⚡ MEXC {piyasa_turu} Çoklu Strateji & Likidasyon Radarı')


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


# --- TELEGRAM MESAJ GÖNDERME (SEKME YÖNLENDİRMELİ) ---
def telegram_fotograf_gonder(foto_buf, caption_metni, kanal_tipi):
  if telegram_aktif and bot_token and chat_id:
    url = f'https://api.telegram.org/bot{bot_token.strip()}/sendPhoto'

    hedef_topic = None
    if kanal_tipi == 'LIQUIDATION' and liq_thread_id:
      hedef_topic = str(liq_thread_id).strip()
    elif kanal_tipi == 'LONG' and long_thread_id:
      hedef_topic = str(long_thread_id).strip()
    elif kanal_tipi == 'SHORT' and short_thread_id:
      hedef_topic = str(short_thread_id).strip()
    elif kanal_tipi == 'DIVERGENCE' and div_thread_id:
      hedef_topic = str(div_thread_id).strip()

    params = {}
    if hedef_topic and hedef_topic != '':
      try:
        params['message_thread_id'] = int(hedef_topic)
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
  return tr.rolling(window=periyot).mean().iloc[-1]


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
      mumlar = mexc.fetch_ohlcv(sembol, timeframe=zaman_dilimi, limit=40)

      if len(mumlar) >= 25:
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
            round(df['RSI'].iloc[-6], 1)
            if not np.isnan(df['RSI'].iloc[-6])
            else 50.0
        )

        df['EMA20'] = df['Kapanis'].ewm(span=20, adjust=False).mean()
        df['EMA50'] = df['Kapanis'].ewm(span=50, adjust=False).mean()

        atr = hesapla_atr(df)
        if np.isnan(atr) or atr == 0:
          atr = son_kapanis * 0.02

        hacim_orani = son_hacim / gecmis_hacim if gecmis_hacim > 0 else 0
        mum_degisimi = ((son_kapanis - son_acilis) / son_acilis) * 100

        # Fonlama Oranı
        funding_rate = None
        if is_futures and 'info' in t_info:
          funding_rate = float(t_info['info'].get('fundingRate', 0) or 0) * 100

        sinyal_adi = None
        aksiyon = None
        kanal_tipi = None

        # 1. 💥 LİKİDASYON SQUEEZE
        if (
            funding_rate is not None
            and funding_rate <= fonlama_esigi
            and hacim_orani >= 1.4
        ):
          sinyal_adi = (
              f'💥 SHORT LİKİDASYON SQUEEZE (Fonlama: %{round(funding_rate, 4)})'
          )
          aksiyon = '🟢 GÜÇLÜ LONG'
          kanal_tipi = 'LIQUIDATION'

        elif (
            funding_rate is not None
            and funding_rate >= 0.08
            and hacim_orani >= 1.4
            and mum_degisimi < 0
        ):
          sinyal_adi = (
              f'💥 LONG LİKİDASYON TASFİYESİ (Fonlama: %{round(funding_rate, 4)})'
          )
          aksiyon = '🔴 GÜÇLÜ SHORT'
          kanal_tipi = 'LIQUIDATION'

        # 2. 📈 RSI DIVERGENCE (UYUMSUZLUK)
        elif (son_kapanis <= gecmis_en_dusuk) and (
            son_rsi > onceki_rsi and son_rsi <= 38
        ):
          sinyal_adi = '📈 POZİTİF UYUMSUZLUK (DİP REVERSAL)'
          aksiyon = '🟢 LONG'
          kanal_tipi = 'DIVERGENCE'

        elif (son_kapanis >= gecmis_en_yuksek) and (
            son_rsi < onceki_rsi and son_rsi >= 65
        ):
          sinyal_adi = '📉 NEGATİF UYUMSUZLUK (TEPE REVERSAL)'
          aksiyon = '🔴 SHORT'
          kanal_tipi = 'DIVERGENCE'

        # 3. ⚡ EMA TREND & BALİNA HACMİ
        elif (
            df['EMA20'].iloc[-1] > df['EMA50'].iloc[-1]
            and df['EMA20'].iloc[-2] <= df['EMA50'].iloc[-2]
            and hacim_orani >= 1.8
        ):
          sinyal_adi = '⚡ GOLDEN CROSS & BALİNA GİRİŞİ'
          aksiyon = '🟢 LONG'
          kanal_tipi = 'LONG'

        # 4. 🚀 DİRENÇ / DESTEK KIRILIMI
        elif (
            (hacim_orani >= hacim_carpani)
            and (son_kapanis >= gecmis_en_yuksek)
            and (45 <= son_rsi <= 75)
        ):
          sinyal_adi = '🚀 DİRENÇ KIRILIMI (PUMP)'
          aksiyon = '🟢 LONG'
          kanal_tipi = 'LONG'

        elif (
            (hacim_orani >= hacim_carpani)
            and (son_rsi >= 75)
            and (mum_degisimi < 0)
        ):
          sinyal_adi = '🪤 BOĞA TUZAĞI (REDDİYAT)'
          aksiyon = '🔴 SHORT'
          kanal_tipi = 'SHORT'

        if kanal_tipi is not None:
          temiz_parite = sembol.split(':')[0]
          mexc_kod = temiz_parite.replace('/', '_')

          if is_futures:
            mexc_link = f'https://www.mexc.com/tr-TR/futures/{mexc_kod}'
          else:
            mexc_link = f'https://www.mexc.com/tr-TR/exchange/{mexc_kod}'

          yon_turu = 'LONG' if 'LONG' in aksiyon else 'SHORT'
          tp1, tp2, sl = hesapla_tp_sl(son_kapanis, atr, yon=yon_turu)

          sinyal_id = f'{temiz_parite}_{sinyal_adi}_{zaman_dilimi}'

          # Telegram Gönderimi
          if (
              telegram_aktif
              and sinyal_id not in st.session_state.gonderilen_sinyaller
          ):
            fonlama_bilgi = (
                f'\n💸 <b>Fonlama:</b> %{round(funding_rate, 4)}'
                if funding_rate is not None
                else ''
            )
            tg_caption = (
                f'🚨 <b>MEXC {piyasa_turu.upper()} ALGORİTMİK SİNYAL</b>\n\n'
                f'📌 <b>Parite:</b> {temiz_parite}\n'
                f'🎯 <b>Yön:</b> {aksiyon}\n'
                f'⚡ <b>Strateji:</b> {sinyal_adi}\n'
                f'⏱ <b>Zaman:</b> {zaman_dilimi}\n'
                f'💰 <b>Giriş Fiyatı:</b> {son_kapanis} $\n'
                f'📊 <b>Hacim Katı:</b> {round(hacim_orani, 1)}x'
                f'{fonlama_bilgi}\n'
                f'📈 <b>RSI (14):</b> {son_rsi}\n\n'
                f'🎯 <b>HEDEF 1 (TP1):</b> {tp1} $\n'
                f'🎯 <b>HEDEF 2 (TP2):</b> {tp2} $\n'
                f'🛑 <b>STOP-LOSS:</b> {sl} $\n'
                f'⚖️ <b>Risk / Ödül:</b> 1 : 2.0\n\n'
                f"🔗 <a href='{mexc_link}'>MEXC Grafiği Aç ↗</a>"
            )
            try:
              foto_buffer = grafik_olustur(df, temiz_parite, zaman_dilimi)
              telegram_fotograf_gonder(foto_buffer, tg_caption, kanal_tipi)
            except Exception:
              pass

            st.session_state.gonderilen_sinyaller.add(sinyal_id)

          sinyaller.append({
              'Kanal': kanal_tipi,
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
  with st.spinner(
      'Tüm stratejiler (Likidasyon, Divergence, EMA, Kırılım) taranıyor...'
  ):
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
        'Seçilen zaman diliminde henüz strateji koşullarını sağlayan parite'
        f' bulunamadı ({pd.Timestamp.now().strftime("%H:%M:%S")}).'
    )
