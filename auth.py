"""
認証まわり（パスワードの扱いとトークン）
------------------------------------------
ここだけは「なんとなく動く」で済ませてはいけない部分。
間違えると利用者のパスワードが漏れる。

必要なライブラリ:
  pip install bcrypt PyJWT
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from dotenv import load_dotenv

load_dotenv()

# トークンに署名するための秘密鍵。
# これが漏れると、誰でも他人になりすましたトークンを作れる。
JWT_SECRET = os.environ.get("JWT_SECRET")
JWT_ALGORITHM = "HS256"
TOKEN_DAYS = 14          # ログイン状態を保つ日数

# bcryptは72バイトまでしか扱えない。超える分は黙って切り捨てられる仕様なので、
# 長いパスワードの末尾が無視される事故を防ぐため、入口で弾く。
MIN_PASSWORD_BYTES = 8
MAX_PASSWORD_BYTES = 72


# ============================================================
# パスワード
# ============================================================
def check_password_rule(password: str) -> str | None:
    """問題があればその理由を、無ければ None を返す"""
    size = len(password.encode("utf-8"))
    if size < MIN_PASSWORD_BYTES:
        return "パスワードは8文字以上にしてください"
    if size > MAX_PASSWORD_BYTES:
        return "パスワードが長すぎます（72バイトまで）"
    return None


def hash_password(password: str) -> str:
    """パスワードをハッシュ化する。

    ハッシュ化は一方向の変換で、元に戻せない。
    DBが漏れても、そこからパスワードは復元できない。

    gensalt() が毎回違うランダム値を混ぜるので、
    同じパスワードでも保存される文字列は毎回変わる。
    これにより「同じ文字列＝同じパスワード」という推測を防ぐ。
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """入力されたパスワードが、保存されたハッシュと一致するか。

    「ハッシュを元に戻して比べる」のではなく、
    「入力を同じ手順で変換して比べる」という考え方。
    """
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        # 保存されている値が壊れている場合。例外にせず不一致として扱う
        return False


# ============================================================
# トークン
# ============================================================
def create_token(user_id: int) -> str:
    """ログイン成功時に渡す通行証を作る。

    中身は誰でも読めるので、秘密の情報は入れない。
    入れるのは「誰か（user_id）」と「いつまで有効か（exp）」だけ。
    改ざんすると署名が合わなくなるので、偽造はできない。
    """
    _require_secret()
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def user_id_from_token(token: str) -> int | None:
    """トークンからユーザーIDを取り出す。

    期限切れ・改ざん・形式違いは全て None を返す。
    呼び出す側は「Noneなら拒否」とだけ考えればよい。
    """
    _require_secret()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


def _require_secret() -> None:
    if not JWT_SECRET:
        raise RuntimeError(
            "環境変数 JWT_SECRET が設定されていません。"
            "python3 -c \"import secrets; print(secrets.token_urlsafe(32))\" "
            "で生成して .env とRenderのEnvironmentに設定してください。"
        )