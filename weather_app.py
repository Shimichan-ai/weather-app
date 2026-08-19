"""天気予報アプリ（学習用）
------------------------------------------
地域を選ぶ → 外部API（Open-Meteo）からデータ取得 → 今日の天気を表示

Open-Meteo を使う理由:
  - APIキー不要（登録なしでいきなり試せる）
  - 非商用は無料
  - JSONで返ってくるので構造がわかりやすい

必要なライブラリ:
  pip install requests
"""

import requests

# ============================================================
# 1. 地域マスタ（緯度・経度）
#    多くの天気APIは「都市名」ではなく「緯度・経度」で問い合わせる
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

# ============================================================
# 2. 天気コードの変換テーブル
#    APIは天気を「数字（WMO天気コード）」で返してくるので、
#    人間が読める日本語に変換する
# ============================================================
WEATHER_CODES = {
    0: "晴れ",
    1: "おおむね晴れ",
    2: "一部曇り",
    3: "曇り",
    45: "霧",
    48: "霧（着氷性）",
    51: "霧雨（弱）",
    53: "霧雨",
    55: "霧雨（強）",
    56: "着氷性の霧雨",
    57: "着氷性の霧雨（強）",
    61: "雨（弱）",
    63: "雨",
    65: "雨（強）",
    66: "着氷性の雨",
    67: "着氷性の雨（強）",
    71: "雪（弱）",
    73: "雪",
    75: "雪（強）",
    77: "霧雪",
    80: "にわか雨（弱）",
    81: "にわか雨",
    82: "にわか雨（激しい）",
    85: "にわか雪（弱）",
    86: "にわか雪（強）",
    95: "雷雨",
    96: "雷雨（ひょう混じり）",
    99: "雷雨（激しいひょう）",
}

API_URL = "https://api.open-meteo.com/v1/forecast"


# ============================================================
# 3. API通信部分 ★このアプリの本題
# ============================================================
def fetch_weather(latitude: float, longitude: float) -> dict:
    """指定座標の今日の天気をAPIから取得して辞書で返す"""

    # (a) 送信するパラメータを組み立てる
    #     → URLの「?latitude=35.68&longitude=139.69&...」の部分になる
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Asia/Tokyo",
        "forecast_days": 1,  # 今日ぶんだけ
    }

    # (b) GETリクエストを送る
    #     timeout は必須級。付けないと相手が応答しない時に固まる
    response = requests.get(API_URL, params=params, timeout=10)

    # (c) ステータスコードを確認（200以外なら例外を投げる）
    response.raise_for_status()

    # (d) 返ってきたJSON文字列をPythonの辞書に変換
    data = response.json()

    # (e) 必要な値だけ取り出して、扱いやすい形に整える
    daily = data["daily"]
    return {
        "date": daily["time"][0],
        "weather": WEATHER_CODES.get(daily["weather_code"][0], "不明"),
        "temp_max": daily["temperature_2m_max"][0],
        "temp_min": daily["temperature_2m_min"][0],
        "rain_prob": daily["precipitation_probability_max"][0],
        "temp_unit": data["daily_units"]["temperature_2m_max"],
    }


# ============================================================
# 4. 表示部分
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
    """地域を選ばせて名前を返す。qで終了"""
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


# ============================================================
# 5. メイン処理
# ============================================================
def main() -> None:
    print("天気予報アプリ（Open-Meteo）")

    while True:
        area_name = select_area()
        if area_name is None:
            print("終了します。")
            break

        lat, lon = AREAS[area_name]

        # 通信は失敗する前提でエラー処理を書く
        try:
            weather = fetch_weather(lat, lon)
        except requests.exceptions.Timeout:
            print("!! タイムアウトしました。時間をおいて再試行してください。")
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