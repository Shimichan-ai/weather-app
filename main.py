"""
天気予報API（FastAPI版 / キャッシュ対応）
------------------------------------------
v1からの変更点：
  1. 一度取得した天気を30分間メモリに保持し、その間は外部APIを叩かない
  2. 外部APIが失敗しても、古いデータが残っていればそれを返す（サービスを止めない）
  3. 429（レート制限）に専用のメッセージを用意

なぜ必要か：
  Open-Meteoの制限はIP単位。Renderの無料プランは送信元IPを
  他の利用者と共有しているため、自分の利用量が少なくても
  枠を使い切られて429が返ることがある。
  → 呼ぶ回数そのものを減らすしかない。

起動方法:
  uvicorn main:app --reload
"""

from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from weather_app import AREAS, fetch_weather


app = FastAPI(
    title="天気予報API",
    description="地域名を渡すと今日の天気を返すAPI（30分キャッシュ付き）",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://weather-front-orcin.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# キャッシュ置き場
#   構造: { "東京": {"data": {...}, "fetched_at": datetime}, ... }
#
#   ただのPythonの辞書なので、サーバーを再起動すると消える。
#   Renderの無料プランはスリープのたびに再起動するため、
#   起きた直後の1回は必ず外部APIを叩きにいく。
#   ここが「消えたら困る」と感じ始めた時が、DBの出番。
# ============================================================
_cache: dict[str, dict] = {}

CACHE_TTL_SECONDS = 30 * 60  # 30分。日単位の予報なので十分


def _age_seconds(fetched_at: datetime) -> float:
    """取得してから何秒経ったか"""
    return (datetime.now(timezone.utc) - fetched_at).total_seconds()


class WeatherResponse(BaseModel):
    area: str
    date: str
    weather: str
    temp_max: float
    temp_min: float
    rain_prob: int
    temp_unit: str
    # --- ここから追加分。既存のフロントは無視するので影響なし ---
    cached: bool = False      # キャッシュから返したか
    age_minutes: int = 0      # データの古さ（分）
    stale: bool = False       # 期限切れだが緊急避難的に返したか


class AreaListResponse(BaseModel):
    areas: list[str]


@app.get("/")
def read_root():
    return {"message": "天気予報APIは動いています", "docs": "/docs"}


@app.get("/areas", response_model=AreaListResponse)
def get_areas():
    return {"areas": list(AREAS.keys())}


@app.get("/weather", response_model=WeatherResponse)
def get_weather(area: str):
    """
    今日の天気を返す。

    処理の順番:
      1. 新しいキャッシュがあれば、それを返して終了（外部APIを叩かない）
      2. なければ外部APIを叩き、結果をキャッシュに保存して返す
      3. 外部APIが失敗しても、古いキャッシュがあればそれを返す
      4. どれも駄目なら諦めてエラーを返す
    """
    if area not in AREAS:
        raise HTTPException(
            status_code=404,
            detail=f"地域「{area}」は登録されていません。/areas で一覧を確認してください。",
        )

    # --- 1. 新しいキャッシュがあるか ---
    entry = _cache.get(area)
    if entry and _age_seconds(entry["fetched_at"]) < CACHE_TTL_SECONDS:
        age = int(_age_seconds(entry["fetched_at"]) // 60)
        return {**entry["data"], "area": area, "cached": True, "age_minutes": age}

    # --- 2. 外部APIを叩く ---
    lat, lon = AREAS[area]
    try:
        weather = fetch_weather(lat, lon)
        _cache[area] = {"data": weather, "fetched_at": datetime.now(timezone.utc)}
        return {**weather, "area": area, "cached": False, "age_minutes": 0}

    except Exception as e:
        # --- 3. 失敗した。古いキャッシュで代用できないか ---
        if entry:
            age = int(_age_seconds(entry["fetched_at"]) // 60)
            return {
                **entry["data"],
                "area": area,
                "cached": True,
                "age_minutes": age,
                "stale": True,
            }

        # --- 4. 代用もできない。素直にエラーを返す ---
        raise _to_http_error(e)


def _to_http_error(e: Exception) -> HTTPException:
    """例外の種類ごとに、利用者が読んで意味のわかるエラーに変換する"""

    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
        if e.response.status_code == 429:
            return HTTPException(
                status_code=429,
                detail=(
                    "天気データの提供元が混雑しています（レート制限）。"
                    "しばらく待ってから再度お試しください。"
                ),
            )
        return HTTPException(
            status_code=502,
            detail=f"天気データの提供元がエラーを返しました ({e.response.status_code})",
        )

    if isinstance(e, requests.exceptions.Timeout):
        return HTTPException(status_code=504, detail="天気データの提供元がタイムアウトしました")

    if isinstance(e, requests.exceptions.RequestException):
        return HTTPException(status_code=502, detail="天気データの提供元と通信できませんでした")

    return HTTPException(status_code=502, detail=f"想定外の応答でした: {e}")


# ============================================================
# 動作確認用。キャッシュの中身を覗ける
# ============================================================
@app.get("/cache")
def inspect_cache():
    """今どの地域が何分前のデータを持っているか"""
    return {
        area: {
            "age_minutes": int(_age_seconds(v["fetched_at"]) // 60),
            "date": v["data"]["date"],
        }
        for area, v in _cache.items()
    }
