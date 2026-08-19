import io
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import matplotlib
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import requests

matplotlib.use('Agg')

# --- BOT & TELEGRAM AYARLARI ---
BOT_TOKEN = "7820599329:AAEAa13edhS9PLoG1t8R34PLO9xpKlaT_Lc"
CHAT_ID = "-1004434260285"
TOPIC_ID = 387
COIN_LIMIT = 80  # En hacimli 80 coin (Rate-limit korumalı)

hafiza = set()


# Render Port Dinleyicisi (7/24 Açık Kalma)
class HealthCheckHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.send_header('Content-type', 'text/plain; charset=utf-8')
    self.end_headers()
    self.wfile.write(b'KENDINE22TRADER WhaleHunter 7/24 Aktif!')

  def log_message(self, format, *args):
    return


def start_http_server():
  port = int(os.environ.get('PORT', 10000))
  server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
  server.serve_forever()


def telegram_foto_gonder(foto_buf, caption):
  url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto'
  data = {
      'chat_id': CHAT_ID,
      'message_thread_id': TOPIC_ID,
      'caption': caption,
      'parse_mode': 'HTML',
  }
  files = {'photo': ('chart.png', foto_buf, 'image/png')}
  try:
    res = requests.post(url, data=data, files=files, timeout=15)
    print(f'Telegram Gönderim Sonucu: {res.status_code}')
  except Exception as e:
    print(f'Telegram Fotoğraf Hatası: {e}')


def grafik_ciz(df_mum, sembol, tf_etiket, tp1, tp2, sl):
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
  df_plot = df_grafik.tail(35)

  mc = mpf.make_marketcolors(
      up='#00FF88', down='#FF3366', inherit=True, volume='in'
  )
  s = mpf.make_mpf_style(
      base_mpf_style='nightclouds',
      marketcolors=mc,
      gridcolor='#20242C',
      facecolor='#0E1117',
      edgecolor='#30363D',
      figcolor='#0E1117',
  )
  hlines_dict = dict(
      hlines=[tp1, tp2, sl],
      colors=['#00FF88', '#38EF7D', '#FF3366'],
      linestyle=['--', '-.', ':'],
      linewidths=[1.6, 1.4, 1.6],
  )

  buf = io.BytesIO()
  fig, axes = mpf.plot(
      df_plot,
      type='candle',
      volume=True,
      style=s,
      hlines=hlines_dict,
      returnfig=True,
      figsize=(9, 5.2),
      savefig=dict(dpi=130, bbox_inches='tight'),
  )
  ax_main = axes[0]
  ax_main.set_title(
      f'KENDİNE22TRADER | {sembol} ({tf_etiket}) BALİNA SİNYALİ',
      fontsize=11,
      fontweight='bold',
      color='#00D4FF',
      pad=10,
  )

  fig.savefig(buf, format='png', bbox_inches='tight', facecolor='#0E1117')
  buf.seek(0)
  plt.close('all')
  return buf


# --- GELİŞMİŞ VE ONAYLI BALİNA MOTORU ---
def balina_kontrol(df):
  if len(df) < 20:
    return None, 0, 0

  closes = df['Kapanis'].values
  opens = df['Acilis'].values
  highs = df['Yuksek'].values
  lows = df['Dusuk'].values
  vols = df['Hacim'].values

  # 1. Hacim Katı (Son 15 mumluk hacim ortalamasına kıyasla)
  ort_hacim = np.mean(vols[-16:-1])
  son_hacim = vols[-1]
  if ort_hacim <= 0:
    return None, 0, 0
  hacim_kati = son_hacim / ort_hacim

  # 1.35x ve üzeri hacim patlaması
  if hacim_kati < 1.35:
    return None, 0, 0

  # 2. Gövde Gücü Kontrolü (Sahte İğne/Fitil Önleme)
  toplam_mum_boyu = highs[-1] - lows[-1]
  if toplam_mum_boyu <= 0:
    return None, 0, 0
  govde = abs(closes[-1] - opens[-1])
  if (govde / toplam_mum_boyu) < 0.35:  # Doji / Kararsız mumları eler
    return None, 0, 0

  # 3. RSI Hesaplama (14 Periyot)
  delta = pd.Series(closes).diff()
  gain = delta.where(delta > 0, 0.0).rolling(14).mean()
  loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
  rs = gain / (loss + 1e-9)
  rsi = float((100 - (100 / (1 + rs))).iloc[-1])

  # 4. Yön Tespiti
  if (closes[-1] > opens[-1]) and (30 <= rsi <= 75):
    return 'LONG', round(hacim_kati, 2), round(rsi, 1)
  elif (closes[-1] < opens[-1]) and (25 <= rsi <= 70):
    return 'SHORT', round(hacim_kati, 2), round(rsi, 1)

  return None, 0, 0


def main():
  threading.Thread(target=start_http_server, daemon=True).start()
  print('🐋 KENDİNE22TRADER WhaleHunter Hızlı Tarama Başlatıldı...')

  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
          ' like Gecko) Chrome/120.0.0.0 Safari/537.36'
      ),
      'Accept': 'application/json, text/plain, */*',
  }

  zaman_dilimleri = [
      ('Min15', '15m', '15 Dakika'),
      ('Min30', '30m', '30 Dakika'),
      ('Min60', '1h', '1 Saat'),
  ]

  while True:
    try:
      url_tickers = 'https://contract.mexc.com/api/v1/contract/ticker'
      res = requests.get(url_tickers, headers=headers, timeout=8).json()

      if res.get('success', False):
        tickers = [
            d
            for d in res.get('data', [])
            if d.get('symbol', '').endswith('_USDT')
        ]
        tickers.sort(
            key=lambda x: float(x.get('amount24', 0) or 0), reverse=True
        )
        secilen_pariteler = tickers[:COIN_LIMIT]

        print(
            f'🔍 [{time.strftime("%H:%M:%S")}] {len(secilen_pariteler)} Coin'
            ' Taranıyor...'
        )

        for coin in secilen_pariteler:
          sembol_raw = coin['symbol']
          temiz_parite = sembol_raw.replace('_', '/')
          mexc_link = f'https://www.mexc.com/tr-TR/futures/{sembol_raw}'

          for api_tf, tf_kod, tf_ad in zaman_dilimleri:
            try:
              time.sleep(0.05)  # MEXC Rate-limit engelleyici mikro bekleme
              url_kline = f'https://contract.mexc.com/api/v1/contract/kline/{sembol_raw}?interval={api_tf}'
              kline_res = requests.get(
                  url_kline, headers=headers, timeout=3
              ).json()

              if kline_res.get('success', False) and kline_res.get('data'):
                k_data = kline_res['data']
                times = k_data.get('time', [])
                opens = k_data.get('open', [])
                closes = k_data.get('close', [])
                highs = k_data.get('high', [])
                lows = k_data.get('low', [])
                vols = k_data.get('vol', [])

                if len(closes) >= 20:
                  df = pd.DataFrame({
                      'Zaman': [t * 1000 for t in times[-40:]],
                      'Acilis': [float(x) for x in opens[-40:]],
                      'Yuksek': [float(x) for x in highs[-40:]],
                      'Dusuk': [float(x) for x in lows[-40:]],
                      'Kapanis': [float(x) for x in closes[-40:]],
                      'Hacim': [float(x) for x in vols[-40:]],
                  })

                  yon, hacim_kati, rsi_val = balina_kontrol(df)

                  if yon:
                    son_kapanis = df['Kapanis'].iloc[-1]
                    son_zaman = df['Zaman'].iloc[-1]
                    sinyal_id = f'{sembol_raw}_{yon}_{tf_kod}_{son_zaman}'

                    if sinyal_id not in hafiza:
                      atr = (
                          (df['Yuksek'] - df['Dusuk'])
                          .rolling(14)
                          .mean()
                          .iloc[-1]
                      )
                      if np.isnan(atr):
                        atr = son_kapanis * 0.015

                      if yon == 'LONG':
                        sl = round(son_kapanis - (atr * 1.4), 6)
                        tp1 = round(son_kapanis + (atr * 1.8), 6)
                        tp2 = round(son_kapanis + (atr * 3.2), 6)
                        yon_str = '🟢 LONG'
                      else:
                        sl = round(son_kapanis + (atr * 1.4), 6)
                        tp1 = round(son_kapanis - (atr * 1.8), 6)
                        tp2 = round(son_kapanis - (atr * 3.2), 6)
                        yon_str = '🔴 SHORT'

                      caption = (
                          f'🐋 <b>KT22 WHALEHUNTER SİNYALİ (ONAYLI)</b>\n\n'
                          f'📌 <b>Parite:</b> {temiz_parite}\n'
                          f'⏱ <b>Zaman Dilimi:</b> {tf_ad} ({tf_kod})\n'
                          f'🎯 <b>Yön:</b> {yon_str}\n'
                          f'💰 <b>Giriş Fiyatı:</b> {son_kapanis} $\n'
                          f'📊 <b>Hacim Patlaması:</b> {hacim_kati}x\n'
                          f'📈 <b>RSI:</b> {rsi_val}\n\n'
                          f'🎯 <b>HEDEF 1 (TP1):</b> {tp1} $\n'
                          f'🎯 <b>HEDEF 2 (TP2):</b> {tp2} $\n'
                          f'🛑 <b>STOP-LOSS:</b> {sl} $\n\n'
                          f"🔗 <a href='{mexc_link}'>MEXC Vadeli Grafiği Aç"
                          ' ↗</a>'
                      )

                      foto = grafik_ciz(
                          df, temiz_parite, f'{tf_ad} ({tf_kod})', tp1, tp2, sl
                      )
                      telegram_foto_gonder(foto, caption)
                      hafiza.add(sinyal_id)
                      print(f'✅ Balina Sinyali Gönderildi: {sinyal_id}')
                      time.sleep(1)
            except Exception:
              pass
    except Exception as e:
      print(f'Ana Döngü Hatası: {e}')

    time.sleep(15)


if __name__ == '__main__':
  main()
