"""
天気予報API（FastAPI版）
------------------------------------------
weather_app.py で作った fetch_weather() を、そのままHTTPで叩けるようにする。

CLI版との違い:
  CLI版  : ターミナルから input() で操作
  API版  : ブラウザや他のアプリから URL で操作

起動方法:
  pip install fastapi uvicorn
  uvicorn main:app --reload

起動後、ブラウザで開く:
  http://127.0.0.1:8000/docs   ← 自動生成されたテスト画面
"""

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ============================================================
# 既存コードの再利用
#   weather_app.py と同じフォルダに置くこと。
#   weather_app.py の main() は if __name__ == "__main__": で
#   守られているので、importしても勝手に起動しない。
# ============================================================
from weather_app import AREAS, fetch_weather


# ============================================================
# 1. アプリ本体を作る
# ============================================================
app = FastAPI(
    title="天気予報API",
    description="地域名を渡すと今日の天気を返すAPI",
    version="1.0.0",
)

# ============================================================
# 2. CORS設定
#    ブラウザは「別のポートで動くサーバー」への通信を
#    デフォルトで拒否する。Reactから叩くために先に許可しておく。
#    ※ allow_origins に "*" を使うのは開発中だけ。
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite（React）の標準ポート
        "http://localhost:3000",  # Create React App の標準ポート
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 3. レスポンスの「型」を定義する
#    こう書いておくと、/docs に返り値の形が自動で表示され、
#    値がおかしければFastAPIが検知してくれる。
# ============================================================
class WeatherResponse(BaseModel):
    area: str
    date: str
    weather: str
    temp_max: float
    temp_min: float
    rain_prob: int
    temp_unit: str


class AreaListResponse(BaseModel):
    areas: list[str]


# ============================================================
# 4. エンドポイント（URLと処理の対応づけ）
# ============================================================

@app.get("/")
def read_root():
    """動作確認用。ここが表示されればサーバーは生きている"""
    return {"message": "天気予報APIは動いています", "docs": "/docs"}


@app.get("/areas", response_model=AreaListResponse)
def get_areas():
    """選択できる地域の一覧を返す（フロントのプルダウン用）"""
    return {"areas": list(AREAS.keys())}


@app.get("/weather", response_model=WeatherResponse)
def get_weather(area: str):
    """
    今日の天気を返す。

    呼び出し例:
        GET /weather?area=東京

    引数 area は関数の引数に書くだけで、
    FastAPIが自動でURLのクエリパラメータとして受け取ってくれる。
    """

    # (a) 知らない地域名なら 404 を返す
    if area not in AREAS:
        raise HTTPException(
            status_code=404,
            detail=f"地域「{area}」は登録されていません。/areas で一覧を確認してください。",
        )

    lat, lon = AREAS[area]

    # (b) 外部APIを叩く。失敗したら 502（上流サーバーの問題）を返す
    try:
        weather = fetch_weather(lat, lon)
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="天気APIがタイムアウトしました")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"天気APIとの通信に失敗しました: {e}")
    except (KeyError, IndexError) as e:
        raise HTTPException(status_code=502, detail=f"天気APIの応答形式が想定と違います: {e}")

    # (c) 地域名を足して返す。辞書を返すだけでFastAPIがJSONに変換する
    return {"area": area, **weather}
