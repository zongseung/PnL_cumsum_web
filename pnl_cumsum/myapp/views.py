# myapp/views.py

import matplotlib
matplotlib.use('Agg')  # 서버 환경에서 GUI 백엔드 사용을 막기 위해

import io
import base64
import json
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
from scipy.interpolate import CubicSpline

from django.shortcuts import render
from django.http import HttpResponse

class CoinNamePreprocessing:
    def __init__(self, wallet_address):
        self.wallet_address = wallet_address

    def fetch_spot_meta(self):
        api_url = "https://api.hyperliquid.xyz/info"
        headers = {"Content-Type": "application/json"}
        payload = {"type": 'spotMetaAndAssetCtxs'}
        
        response = requests.post(api_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        
        data = response.json()
        
        tokens = pd.DataFrame(data[0]["tokens"]).rename(columns={"name": "Tname"})
        universe = pd.DataFrame(data[0]["universe"]).rename(columns={"name": "coin"})
        
        tokens = tokens.merge(universe, left_on="index", right_on="index", how="inner")
        return tokens

    def fetch_and_plot_total_pnl(self, time_interval=7, spot_only=False):
        """
        time_interval: 기간(일수)
        spot_only: True이면 Spot Only, False이면 Perps Only
        """
        url = "https://api.hyperliquid.xyz/info"
        headers = {"Content-Type": "application/json"}
        
        payload = {
            "type": "userFillsByTime",
            "user": self.wallet_address,
            "startTime": int((pd.Timestamp.now() - pd.Timedelta(days=time_interval)).timestamp() * 1000),
            "endTime": int(pd.Timestamp.now().timestamp() * 1000),
            "aggregateByTime": False
        }
        
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code != 200:
            print("오류:", response.status_code, response.text)
            # (df, fig) 형태로 맞춰야 하므로 두 개 반환
            return pd.DataFrame(), None
        
        data = response.json()
        df = pd.DataFrame(data)
        
        # 'time' 관련 컬럼이 없으므로, 임의로 날짜열 생성
        if not df.empty:
            df["Timestamp"] = pd.date_range(end=pd.Timestamp.now(), periods=len(df), freq='D')
        else:
            df["Timestamp"] = []
        
        # spot_only -> Spot 필터링, 아니면 Perps
        if spot_only:
            filtered_df = df[df["coin"].str.startswith("@")].copy()
            spot_meta = self.fetch_spot_meta()
            spot_meta1 = spot_meta[["Tname", "coin"]]
            coin_to_tname = dict(zip(spot_meta1["coin"], spot_meta1["Tname"]))
            filtered_df["coin"] = filtered_df["coin"].map(coin_to_tname)
            filtered_df = filtered_df[filtered_df["coin"].isin(spot_meta1["Tname"].values)]
        else:
            filtered_df = df[~df["coin"].str.startswith("@")].copy()
        
        filtered_df["closedPnl"] = pd.to_numeric(filtered_df["closedPnl"], errors="coerce").fillna(0.0)
        
        filtered_df.sort_values(by="Timestamp", inplace=True)
        filtered_df.drop_duplicates(subset="Timestamp", inplace=True)
        filtered_df["Cumulative PnL"] = filtered_df["closedPnl"].cumsum()
        
        if filtered_df.empty:
            return filtered_df, None

        # --- Matplotlib 그래프 ---
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))

        x = filtered_df["Timestamp"]
        y = filtered_df["Cumulative PnL"]

        x_numeric = mdates.date2num(x)
        cs = CubicSpline(x_numeric, y)

        x_smooth = np.linspace(x_numeric.min(), x_numeric.max(), 300)
        y_smooth = cs(x_smooth)

        ax.plot(mdates.num2date(x_smooth), y_smooth, color='#00FFAA', linewidth=2.5)
        ax.fill_between(mdates.num2date(x_smooth), y_smooth, color='#00FFAA', alpha=0.2)

        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.set_facecolor("#11191D")
        ax.tick_params(axis='both', colors='white')
        ax.set_xlabel("Date", color='white')
        ax.set_ylabel("Cumulative PnL", color='white')

        if time_interval == 3:
            ax.set_title("24H Cumulative PnL", color='white')
        else:
            ax.set_title(f"Total {time_interval-2}-day Cumulative PnL", color='white')

        ax.grid(color='#444444', linestyle='--', linewidth=0.5)
        ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=6))
        plt.xticks(rotation=45)

        return filtered_df, fig


def plot_form(request):
    """
    1) 웹 폼을 표시 (wallet, time_interval, spot_only)
    2) 폼이 제출되면 (GET 파라미터 있으면) -> 그래프 생성 -> 같은 페이지에 표시
    """
    wallet = request.GET.get('wallet', '')
    interval_str = request.GET.get('time_interval', '')
    spot_only_str = request.GET.get('spot_only', 'false')  # 'true' or 'false'

    chart_data = None  # base64 인코딩된 이미지 데이터 (없으면 표시X)

    if wallet and interval_str:
        # 폼이 제출된 상황
        try:
            time_interval = int(interval_str)
        except ValueError:
            time_interval = 7

        spot_only = (spot_only_str.lower() == 'true')

        # CoinNamePreprocessing 이용
        coin_proc = CoinNamePreprocessing(wallet)
        df, fig = coin_proc.fetch_and_plot_total_pnl(time_interval=time_interval, spot_only=spot_only)
        
        # df가 비어있지 않고 fig가 있으면 -> PNG 변환
        if not df.empty and fig is not None:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            # base64 인코딩
            chart_data = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig)

    context = {
        'wallet': wallet,
        'time_interval': interval_str,
        'spot_only': spot_only_str,
        'chart_data': chart_data,
    }
    return render(request, 'myapp/plot_form.html', context)
