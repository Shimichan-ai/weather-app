"""
天気予報アプリ（WeatherAPI.com版）
------------------------------------------
Open-Meteoから乗り換えた理由:
  Open-MeteoはAPIキーが不要 = 利用者の識別手段がIPアドレスしかない。
  Renderの無料プランは送信元IPを他の利用者と共有しているため、
  自分の使用量に関係なく429（レート制限）で弾かれ続けた。

  WeatherAPI.comはキーを発行するので、利用枠が自分のアカウントに
  紐づく。他人の使用量に巻き込まれない。

重要:
  APIキーはパスワードと同じ。絶対にコードに直接書かないこと。
  環境変数から読み込む。

必要なライブラリ:
  pip install requests python-dotenv
"""

import os

import requests
from dotenv import load_dotenv

# .env ファイルがあれば読み込む（ローカル開発用）
# Renderなど本番環境では管理画面で設定した環境変数が使われるので、
# .env が無くてもエラーにはならない
load_dotenv()

# ============================================================
# APIキーの取得
#   os.environ.get() は「環境変数を名前で探す」命令。
#   見つからなければ None が返る。
# ============================================================
API_KEY = os.environ.get("WEATHER_API_KEY")

API_URL = "https://api.weatherapi.com/v1/forecast.json"

# ============================================================
# 地域マスタ（Open-Meteo版から変更なし）
# ============================================================
AREAS = {
    "札幌": (43.0642, 141.3469),
    "仙台": (38.2682, 140.8694),
    "東京": (35.6895, 139.6917),
    "名古屋": (35.1815, 136.9066),
    "大阪": (34.6937, 135.5023),
    "広島": (34.3853, 132.4553),
    "福岡": (33.5904, 130.4017),
    "那覇": (26.2124, 127.6809),
}

# WEATHER_CODES の変換テーブルは不要になった。
# WeatherAPI.com は lang=ja を付けると天気を日本語の文字列で返してくれる。
# 「数字を自分で日本語に直す」工程が、提供元の機能に置き換わった形。


def fetch_weather(latitude: float, longitude: float) -> dict:
    """指定座標の今日の天気をAPIから取得して辞書で返す。

    返す辞書の形はOpen-Meteo版と完全に同じ。
    呼び出す側（main.py）は一切変更しなくてよい。
    """

    if not API_KEY:
        raise RuntimeError(
            "環境変数 WEATHER_API_KEY が設定されていません。"
            "ローカルなら .env ファイル、Renderなら管理画面のEnvironmentで設定してください。"
        )

    params = {
        "key": API_KEY,               # 認証キー
        "q": f"{latitude},{longitude}",  # 「緯度,経度」をカンマ区切りの文字列で渡す
        "days": 1,                    # 今日ぶんだけ
        "lang": "ja",                 # 天気の説明を日本語で
        "aqi": "no",                  # 大気質データは不要
        "alerts": "no",               # 警報データは不要
    }

    response = requests.get(API_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    # --- 必要な値を取り出す ---
    # WeatherAPIは forecast > forecastday > [0] という階層構造で返す
    today = data["forecast"]["forecastday"][0]
    day = today["day"]

    return {
        "date": today["date"],
        "weather": day["condition"]["text"],
        "temp_max": day["maxtemp_c"],
        "temp_min": day["mintemp_c"],
        "rain_prob": day["daily_chance_of_rain"],
        "temp_unit": "°C",
    }


# ============================================================
# 以下はCLI版の名残。main.py からimportしても実行されない
# ============================================================
def show_weather(area_name: str, w: dict) -> None:
    print()
    print("=" * 32)
    print(f"  {area_name} の天気　{w['date']}")
    print("=" * 32)
    print(f"  天気　　: {w['weather']}")
    print(f"  最高気温: {w['temp_max']}{w['temp_unit']}")
    print(f"  最低気温: {w['temp_min']}{w['temp_unit']}")
    print(f"  降水確率: {w['rain_prob']}%")
    print("=" * 32)


def select_area() -> str | None:
    print("\n【地域を選んでください】")
    names = list(AREAS.keys())
    for i, name in enumerate(names, start=1):
        print(f"  {i}. {name}")
    print("  q. 終了")

    choice = input("番号を入力 > ").strip()
    if choice.lower() == "q":
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        return names[int(choice) - 1]

    print("!! 入力が正しくありません")
    return select_area()


def main() -> None:
    print("天気予報アプリ（WeatherAPI.com）")

    while True:
        area_name = select_area()
        if area_name is None:
            print("終了します。")
            break

        lat, lon = AREAS[area_name]
        try:
            weather = fetch_weather(lat, lon)
        except RuntimeError as e:
            print(f"!! {e}")
            break
        except requests.exceptions.Timeout:
            print("!! タイムアウトしました。")
            continue
        except requests.exceptions.HTTPError as e:
            print(f"!! APIがエラーを返しました: {e}")
            continue
        except requests.exceptions.RequestException as e:
            print(f"!! 通信に失敗しました: {e}")
            continue
        except (KeyError, IndexError) as e:
            print(f"!! 応答の形式が想定と違います: {e}")
            continue

        show_weather(area_name, weather)


if __name__ == "__main__":
    main()
