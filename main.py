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
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import auth
import db
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
        "https://weather-front-orcin.vercel.app",  # ← 本番のフロント。消すと画面が動かなくなる
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


class HourItem(BaseModel):
    """1時間ぶんのデータ。入れ子の構造も型で定義できる"""
    time: str          # "14:00"
    temp: float
    icon: str = ""
    icon_name: str = "cloudy"
    weather: str = ""
    rain_prob: int = 0


class WeatherResponse(BaseModel):
    area: str
    date: str
    weather: str
    icon: str = ""     # 提供元のアイコンURL（未使用・互換のため残す）
    icon_name: str = "cloudy"    # 自作アイコンの名前
    hours: list[HourItem] = []   # 1時間ごと（24件）
    local_hour: int = 0          # 観測地点の現在時刻（時）
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
    # 週間予報はフロントから直接Open-Meteoを叩くので、座標を渡す必要がある。
    # 既存の areas はそのまま残すので、古いフロントも壊れない。
    coords: dict[str, list[float]] = {}


@app.get("/")
def read_root():
    return {"message": "天気予報APIは動いています", "docs": "/docs"}


@app.get("/areas", response_model=AreaListResponse)
def get_areas():
    """選択できる地域の一覧と座標を返す"""
    return {
        "areas": list(AREAS.keys()),
        "coords": {name: [lat, lon] for name, (lat, lon) in AREAS.items()},
    }


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


# ============================================================
# ここから下：ユーザー登録・ログイン・お気に入り
# ============================================================

class Credentials(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    token: str
    email: str


class MeResponse(BaseModel):
    email: str


class FavoritesResponse(BaseModel):
    favorites: list[str]


class AreaRequest(BaseModel):
    area: str


def current_user_id(authorization: str | None = Header(default=None)) -> int:
    """リクエストのヘッダーからユーザーIDを取り出す。

    Depends() に渡すと、この関数が先に実行される。
    認証が必要なエンドポイントに1行足すだけで守れるようになる。

    ヘッダーの形式: Authorization: Bearer <トークン>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="ログインが必要です")

    user_id = auth.user_id_from_token(authorization[7:])
    if user_id is None:
        raise HTTPException(status_code=401, detail="ログインの有効期限が切れました")
    return user_id


@app.post("/auth/register", response_model=TokenResponse)
def register(body: Credentials):
    """新規登録。成功するとそのままログイン状態になる"""
    email = body.email.strip().lower()   # 大文字小文字の違いで別人にならないよう揃える

    if "@" not in email or len(email) < 5:
        raise HTTPException(status_code=400, detail="メールアドレスの形式が正しくありません")

    problem = auth.check_password_rule(body.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    # 生のパスワードはここで即座にハッシュ化する。変数に残さない
    password_hash = auth.hash_password(body.password)

    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
                (email, password_hash),
            )
            user_id = cur.fetchone()["id"]
            conn.commit()
    except Exception as e:
        # UNIQUE制約に引っかかった＝すでに登録済み
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="このメールアドレスは登録済みです")
        raise HTTPException(status_code=503, detail="データベースに接続できませんでした")

    return {"token": auth.create_token(user_id), "email": email}


@app.post("/auth/login", response_model=TokenResponse)
def login(body: Credentials):
    """ログイン。

    注意: 失敗理由を「メールが無い」「パスワードが違う」と
    分けて返してはいけない。どのメールが登録済みかを
    外部から調べられてしまう。どちらも同じ文言にする。
    """
    email = body.email.strip().lower()

    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash FROM users WHERE email = %s", (email,)
            )
            row = cur.fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="データベースに接続できませんでした")

    if row is None or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=401, detail="メールアドレスまたはパスワードが違います"
        )

    return {"token": auth.create_token(row["id"]), "email": email}


@app.get("/auth/me", response_model=MeResponse)
def me(user_id: int = Depends(current_user_id)):
    """今ログインしているのが誰かを返す。トークンの有効確認にも使う"""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="ユーザーが見つかりません")
    return {"email": row["email"]}


@app.get("/favorites", response_model=FavoritesResponse)
def list_favorites(user_id: int = Depends(current_user_id)):
    """自分のお気に入り一覧。

    WHERE user_id = %s を必ず付けること。
    忘れると全員分が返り、他人のデータが見えてしまう。
    """
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT area FROM favorites WHERE user_id = %s ORDER BY created_at",
            (user_id,),
        )
        return {"favorites": [r["area"] for r in cur.fetchall()]}


@app.post("/favorites", response_model=FavoritesResponse)
def add_favorite(body: AreaRequest, user_id: int = Depends(current_user_id)):
    """お気に入りに追加する"""
    if body.area not in AREAS:
        raise HTTPException(status_code=404, detail=f"地域「{body.area}」は登録されていません")

    with db.get_conn() as conn, conn.cursor() as cur:
        # 既に登録済みでもエラーにせず無視する。
        # 二重クリックでエラーを見せる必要はない
        cur.execute(
            "INSERT INTO favorites (user_id, area) VALUES (%s, %s) "
            "ON CONFLICT (user_id, area) DO NOTHING",
            (user_id, body.area),
        )
        conn.commit()
        cur.execute(
            "SELECT area FROM favorites WHERE user_id = %s ORDER BY created_at",
            (user_id,),
        )
        return {"favorites": [r["area"] for r in cur.fetchall()]}


@app.delete("/favorites", response_model=FavoritesResponse)
def remove_favorite(area: str, user_id: int = Depends(current_user_id)):
    """お気に入りから外す"""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM favorites WHERE user_id = %s AND area = %s",
            (user_id, area),
        )
        conn.commit()
        cur.execute(
            "SELECT area FROM favorites WHERE user_id = %s ORDER BY created_at",
            (user_id,),
        )
        return {"favorites": [r["area"] for r in cur.fetchall()]}