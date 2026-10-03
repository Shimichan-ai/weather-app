"""
データベース接続とテーブル定義
------------------------------------------
PostgreSQL（Neon）に接続する部分をここに集める。

なぜファイルを分けるか:
  main.py は「HTTPの入口」、weather_app.py は「天気の取得」、
  db.py は「データの保存」。役割ごとに分けておくと、
  問題が起きたときにどのファイルを見るか迷わない。

必要なライブラリ:
  pip install "psycopg[binary]"
"""

import os

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

# Neonの管理画面で発行される接続文字列。
# postgresql://ユーザー名:パスワード@ホスト/DB名?sslmode=require という形。
# パスワードが含まれるので、APIキーと同じく環境変数で扱う。
DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    """DBへの接続を1つ作って返す。

    row_factory=dict_row を指定すると、取得結果が
    ("tokyo", 1) のようなタプルではなく
    {"area": "tokyo", "user_id": 1} の辞書で返る。
    列の順番を覚えなくて済むので、読み違いが減る。
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "環境変数 DATABASE_URL が設定されていません。"
            "ローカルなら .env、本番ならRenderのEnvironmentで設定してください。"
        )
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


# ============================================================
# テーブル定義
#
#   users     … 登録したユーザー
#   favorites … 誰がどの地域をお気に入りにしたか
#
#   IF NOT EXISTS を付けてあるので、何度実行しても安全。
#   既にあれば何もしない。
# ============================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS favorites (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    area       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, area)
);
"""


def init_db() -> None:
    """テーブルを作る。アプリ起動時に1回呼ぶ"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()


if __name__ == "__main__":
    # python3 db.py で直接実行するとテーブルを作成する
    init_db()
    print("テーブルを作成しました。")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position
            """)
            current = None
            for r in cur.fetchall():
                if r["table_name"] != current:
                    current = r["table_name"]
                    print(f"\n[{current}]")
                print(f"  {r['column_name']:<15} {r['data_type']}")