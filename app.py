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
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

matplotlib.use('Agg')

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title='MEXC Ultra VIP Algoritmik Sinyal & Takip Radarı', layout='wide'
)

# Bellek Yönetimi (Sinyaller, Skorlar, TP/SL Takipçisi)
if 'sinyal_skorlari' not in st.session_state:
  st.session_state.sinyal_skorlari = {}

if 'aktif_takipler' not in st.session_state:
  # {'EDEN/USDT': {'yon': 'LONG', 'giris': 0.05, 'tp1': 0.052, 'tp2': 0.054, 'sl': 0.048, 'tp1_hit': False}}
  st.session_state.aktif_takipler = {}

if 'last_update_id' not in st.session_state:
  st.session_state.last_update_id = 0

# --- SESLİ BİLDİRİM FONKSİYONU ---
def ses_cal():
  audio_html = """
    <audio autoplay>
        <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mp3">
    </audio>
    """
  components.html(audio_html, height=0, width=0)


# --- YAN PANEL: TELEGRAM VE SİSTEM AYARLARI ---
st.sidebar.header('📱 Telegram & Bot Ayarları')
telegram_aktif = st.sidebar.checkbox('🚀 Telegram Bildirimleri Açık', value=True)
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

st.title(f'⚡ MEXC {piyasa_turu} Ultra VIP Algoritmik Radar & Takip Merkezi')


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
def telegram_mesaj_gonder(metin):
  if telegram_aktif and bot_token and chat_id:
    url = f'https://api.telegram.org/bot{bot_token.strip()}/sendMessage'
    params = {}
    if topic_id and str(topic_id).strip() != '':
      try:
        params['message_thread_id'] = int(str(topic_id).strip())
      except ValueError:
        pass
    payload = {'chat_id': chat_id.strip(), 'text': metin, 'parse_mode': 'HTML'}
    try:
      requests.post(url, params=params, data=payload, timeout=8)
    except Exception:
      pass


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


# --- TELEGRAM ÇİFT YÖNLÜ KOMUT DİNLEYİCİSİ (/fiyat, /total3, /durum) ---
def telegram_komutlari_isle(mexc_client):
  if not (telegram_aktif and bot_token):
    return

  url = f"https://api.telegram.org/bot{bot_token.strip()}/getUpdates?offset={st.session_state.last_update_id + 1}&timeout=1"
  try:
    res = requests.get(url, timeout=3).json()
    if res.get('ok') and res.get('result'):
      for update in res['result']:
        st.session_state.last_update_id = update['update_id']
        msg = update.get('message', {})
        text = msg.get('text', '').strip()

        if text.startswith('/total3'):
          t3 = fetch_total3_data()
          telegram_mesaj_gonder(
              f"🌐 <b>TOTAL3 Durumu:</b> {t3['total3_mcap']} Milyar $\n"
              f"📊 <b>24s Değişim:</b> %{t3['change_24h']}\n"
              f"🟠 <b>BTC Dom:</b> %{t3['btc_dom']}"
          )

        elif text.startswith('/fiyat'):
          parcalar = text.split()
          if len(parcalar) > 1:
            coin = parcalar[1].upper().replace('USDT', '') + '/USDT'
            try:
              t = mexc_client.fetch_ticker(coin)
              son_f = t['last']
              chg = t.get('percentage', 0)
              telegram_mesaj_gonder(
                  f'💰 <b>{coin} Anlık Fiyat:</b> {son_f} $\n📈 <b>24s Değişim:</b>'
                  f' %{chg}'
              )
            except Exception:
              telegram_mesaj_gonder(f'⚠️ {coin} paritesi bulunamadı.')

        elif text.startswith('/durum'):
          aktif_adet = len(st.session_state.aktif_takipler)
          telegram_mesaj_gonder(
              f'🤖 <b>Bot Canlı!</b>\n🎯 Takip Edilen Aktif Sinyal:'
              f' {aktif_adet} adet'
          )
  except Exception:
    pass


# --- TEKNİK HESAPLAMALAR ---
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


# --- BALİNA DERİNLİK TAHTASI ANALİZİ ---
def balina_derinlik_analizi(mexc_client, sembol):
  try:
    ob = mexc_client.fetch_order_book(sembol, limit=20)
    toplam_alis = sum([bid[1] for bid in ob['bids']])
    toplam_satis = sum([ask[1] for ask in ob['asks']])
    toplam = toplam_alis + toplam_satis
    if toplam > 0:
      alis_orani = round((toplam_alis / toplam) * 100, 1)
      satis_orani = round((toplam_satis / toplam) * 100, 1)
      if alis_orani >= 60:
        return f'🐋 Alıcı Baskısı (%{alis_orani}) 🟢'
      elif satis_orani >= 60:
        return f'🐋 Satıcı Baskısı (%{satis_orani}) 🔴'
      else:
        return f'⚖️ Dengeli Tahta (%{alis_orani} Alış)'
  except Exception:
    pass
  return '⚖️ Normal Derinlik'


# --- ÇOKLU ZAMAN DİLİMİ (MTF - 1h TREND ONAYI) ---
def mtf_trend_onayi(mexc_client, sembol, beklenen_yon):
  try:
    mum_1h = mexc_client.fetch_ohlcv(sembol, timeframe='1h', limit=25)
    if len(mum_1h) >= 20:
      df_1h = pd.DataFrame(
          mum_1h,
          columns=['Zaman', 'Acilis', 'Yuksek', 'Dusuk', 'Kapanis', 'Hacim'],
      )
      ema20_1h = df_1h['Kapanis'].ewm(span=20, adjust=False).mean().iloc[-1]
      ema50_1h = df_1h['Kapanis'].ewm(span=50, adjust=False).mean().iloc[-1]

      if beklenen_yon == 'LONG' and ema20_1h >= ema50_1h:
        return '⭐ 1h Trendiyle Uyumlu (Güçlü Boğa)'
      elif beklenen_yon == 'SHORT' and ema20_1h <= ema50_1h:
        return '⭐ 1h Trendiyle Uyumlu (Güçlü Ayı)'
      else:
        return '⚠️ 1h Trendi Zıt (Kısa Vadeli Tepki)'
  except Exception:
    pass
  return '🔍 Standart Zaman Dilimi'


# --- CANLI TP / SL TAKİP VE BİLDİRİM MOTORU ---
def canli_tp_sl_takip(tickers):
  tamamlananlar = []
  for sembol, veri in st.session_state.aktif_takipler.items():
    if sembol in tickers:
      anlik_fiyat = tickers[sembol]['last']
      yon = veri['yon']
      giris = veri['giris']
      tp1 = veri['tp1']
      tp2 = veri['tp2']
      sl = veri['sl']

      if yon == 'LONG':
        # TP1 Vuruldu
        if anlik_fiyat >= tp1 and not veri['tp1_hit']:
          veri['tp1_hit'] = True
          kazanc = round(((tp1 - giris) / giris) * 100, 2)
          telegram_mesaj_gonder(
              f'🎯🎯 <b>HEDEF 1 (TP1) VURULDU!</b>\n\n📌 <b>Parite:</b>'
              f' {sembol}\n💰 <b>Hedef Fiyat:</b> {tp1} $\n🚀 <b>Kâr:</b>'
              f' +%{kazanc} 💵\n<i>(Kâr realize edip SL seviyesini girişe'
              ' çekebilirsiniz.)</i>'
          )
        # TP2 Vuruldu
        elif anlik_fiyat >= tp2:
          kazanc = round(((tp2 - giris) / giris) * 100, 2)
          telegram_mesaj_gonder(
              f'🚀🚀 <b>HEDEF 2 (TP2) TAM İSABET!</b>\n\n📌 <b>Parite:</b>'
              f' {sembol}\n💰 <b>Kapanış:</b> {tp2} $\n🔥 <b>Toplam Kâr:</b>'
              f' +%{kazanc} 🏆'
          )
          tamamlananlar.append(sembol)
        # Stop-Loss Tetiklendi
        elif anlik_fiyat <= sl:
          zarar = round(((sl - giris) / giris) * 100, 2)
          telegram_mesaj_gonder(
              f'🛑 <b>STOP-LOSS SEVİYESİNE ULAŞILDI</b>\n\n📌 <b>Parite:</b>'
              f' {sembol}\n🔻 <b>Fiyat:</b> {sl} $\n⚠️ <b>Zarar Durdur:</b>'
              f' %{zarar}'
          )
          tamamlananlar.append(sembol)

      elif yon == 'SHORT':
        if anlik_fiyat <= tp1 and not veri['tp1_hit']:
          veri['tp1_hit'] = True
          kazanc = round(((giris - tp1) / giris) * 100, 2)
          telegram_mesaj_gonder(
              f'🎯🎯 <b>SHORT TP1 VURULDU!</b>\n\n📌 <b>Parite:</b>'
              f' {sembol}\n💰 <b>Hedef:</b> {tp1} $\n🚀 <b>Kâr:</b> +%{kazanc}'
              ' 💵'
          )
        elif anlik_fiyat <= tp2:
          kazanc = round(((giris - tp2) / giris) * 100, 2)
          telegram_mesaj_gonder(
              f'🚀🚀 <b>SHORT TP2 TAM İSABET!</b>\n\n📌 <b>Parite:</b>'
              f' {sembol}\n💰 <b>Fiyat:</b> {tp2} $\n🔥 <b>Toplam Kâr:</b>'
              f' +%{kazanc} 🏆'
          )
          tamamlananlar.append(sembol)
        elif anlik_fiyat >= sl:
          zarar = round(((giris - sl) / giris) * 100, 2)
          telegram_mesaj_gonder(
              f'🛑 <b>SHORT STOP-LOSS TETİKLENDİ</b>\n\n📌 <b>Parite:</b>'
              f' {sembol}\n🔺 <b>Fiyat:</b> {sl} $\n⚠️ <b>Zarar Durdur:</b>'
              f' %{zarar}'
          )
          tamamlananlar.append(sembol)

  for bitti in tamamlananlar:
    del st.session_state.aktif_takipler[bitti]


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

  # Telegram Komutlarını Dinle ve TP/SL Takip Et
  telegram_komutlari_isle(mexc)
  canli_tp_sl_takip(tickers)

  usdt_pariteler = [s for s in tickers.keys() if '/USDT' in s]
  usdt_pariteler.sort(
      key=lambda x: tickers[x].get('quoteVolume', 0) or 0, reverse=True
  )
  hedef_listesi = usdt_pariteler[:coin_adedi]

  sinyaller = []
  yeni_sinyal_var = False

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

        coin_24h_change = (
            float(t_info.get('percentage', 0) or 0)
            if 'percentage' in t_info
            else mum_degisimi
        )

        funding_rate = None
        if is_futures and 'info' in t_info:
          funding_rate = float(t_info['info'].get('fundingRate', 0) or 0) * 100

        sinyal_adi = None
        aksiyon = None

        # 1. 🔥 TOTAL3 AYRIŞMASI
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

        # 2. 💥 LİKİDASYON SQUEEZE
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

        # 5. 📈 RSI DIVERGENCE (Onaylı Dönüş)
        elif (
            (son_kapanis <= gecmis_en_dusuk * 1.01)
            and (mum_degisimi > 0.3)
            and (son_rsi > onceki_rsi + 2)
            and (20 <= son_rsi <= 40)
        ):
          sinyal_adi = '📈 POZİTİF UYUMSUZLUK (ONAYLI DİP DÖNÜŞ)'
          aksiyon = '🟢 LONG'

        elif (
            (son_kapanis >= gecmis_en_yuksek * 0.99)
            and (mum_degisimi < -0.3)
            and (son_rsi < onceki_rsi - 2)
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

          # Balina Tahta & MTF Analizleri
          balina_durumu = balina_derinlik_analizi(mexc, sembol)
          mtf_durumu = mtf_trend_onayi(mexc, sembol, yon_turu)

          sinyal_anahtari = f'{temiz_parite}_{sinyal_adi}_{zaman_dilimi}'

          # Skorlama
          if sinyal_anahtari in st.session_state.sinyal_skorlari:
            st.session_state.sinyal_skorlari[sinyal_anahtari]['count'] += 1
          else:
            st.session_state.sinyal_skorlari[sinyal_anahtari] = {
                'count': 1,
                'first_time': pd.Timestamp.now().strftime('%H:%M'),
            }
            yeni_sinyal_var = True  # Ses çalması için

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

          # Aktif Takip Listesine Ekle (TP/SL için)
          if temiz_parite not in st.session_state.aktif_takipler:
            st.session_state.aktif_takipler[temiz_parite] = {
                'yon': yon_turu,
                'giris': son_kapanis,
                'tp1': tp1,
                'tp2': tp2,
                'sl': sl,
                'tp1_hit': False,
            }

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
                f'🛡️ <b>MTF (1h):</b> {mtf_durumu}\n'
                f'🐋 <b>Tahta Analizi:</b> {balina_durumu}\n\n'
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
              'Skor': skor_tablo,
              'Yön': aksiyon,
              'Sinyal Detayı': sinyal_adi,
              'Sembol': temiz_parite,
              'Giriş ($)': son_kapanis,
              'TP1 ($)': tp1,
              'SL ($)': sl,
              'MTF (1h)': mtf_durumu,
              'Derinlik': balina_durumu,
              'RSI': son_rsi,
              'Grafik': mexc_link,
          })
    except Exception:
      pass

  # Yeni Sinyal Varsa Sesli Alarm Çal
  if yeni_sinyal_var:
    ses_cal()

  return pd.DataFrame(sinyaller)


# --- ÇALIŞTIRMA & GÖRÜNTÜLEME ---
manuel_tara = st.button('🔍 Şimdi Tara', type='primary', use_container_width=True)

if oto_yenileme or manuel_tara:
  with st.spinner('Tüm piyasa ve derinlik analizleri taranıyor...'):
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

# Canlı Takipteki Pozisyonlar Kartı
if st.session_state.aktif_takipler:
  st.markdown('---')
  st.subheader(
      f'🎯 Canlı Takipteki Sinyaller ({len(st.session_state.aktif_takipler)} Adet'
      ' TP/SL Bekleniyor)'
  )
  df_takip = pd.DataFrame.from_dict(
      st.session_state.aktif_takipler, orient='index'
  )
  st.dataframe(df_takip, use_container_width=True)
