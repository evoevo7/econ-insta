"""환경변수 및 토큰 저장소."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = Path(os.environ.get("IG_TOKEN_PATH", PROJECT_ROOT / "tokens.json"))

GRAPH_HOST = "https://graph.instagram.com"
API_VERSION = "v25.0"
GRAPH_BASE = f"{GRAPH_HOST}/{API_VERSION}"

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"

DEFAULT_SCOPES = ("instagram_business_basic", "instagram_business_content_publish")


class ConfigError(RuntimeError):
    """필수 환경변수가 없을 때."""


def _load_dotenv() -> None:
    """.env 파일이 있으면 os.environ에 채운다 (기존 값은 덮어쓰지 않음)."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def require_env(name: str) -> str:
    _load_dotenv()
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"환경변수 {name} 가 설정되지 않았습니다. .env 또는 셸에서 지정하세요.")
    return value


@dataclass(frozen=True)
class AppCredentials:
    app_id: str
    app_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> "AppCredentials":
        return cls(
            app_id=require_env("IG_APP_ID"),
            app_secret=require_env("IG_APP_SECRET"),
            redirect_uri=require_env("IG_REDIRECT_URI"),
        )


@dataclass
class StoredToken:
    access_token: str
    user_id: str
    expires_at: float
    """유닉스 타임스탬프. 장기 토큰은 발급 시점 + 60일."""

    @property
    def seconds_left(self) -> float:
        return self.expires_at - time.time()

    @property
    def days_left(self) -> float:
        return self.seconds_left / 86400

    @property
    def is_expired(self) -> bool:
        return self.seconds_left <= 0

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "user_id": self.user_id,
            "expires_at": self.expires_at,
        }


def save_token(token: StoredToken, path: Path | None = None) -> Path:
    target = path or TOKEN_PATH
    target.write_text(json.dumps(token.to_dict(), indent=2), encoding="utf-8")
    return target


def load_token(path: Path | None = None) -> StoredToken:
    """저장된 토큰을 읽는다. 없으면 IG_ACCESS_TOKEN 환경변수로 폴백(CI용)."""
    target = path or TOKEN_PATH
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
        return StoredToken(
            access_token=data["access_token"],
            user_id=str(data["user_id"]),
            expires_at=float(data["expires_at"]),
        )

    _load_dotenv()
    env_token = os.environ.get("IG_ACCESS_TOKEN")
    if env_token:
        # CI(GitHub Actions)에서는 시크릿으로 토큰만 주입한다.
        # 만료 시각을 알 수 없으므로 60일 뒤로 낙관적으로 둔다.
        return StoredToken(
            access_token=env_token,
            user_id=os.environ.get("IG_USER_ID", ""),
            expires_at=time.time() + 60 * 86400,
        )

    raise ConfigError(
        f"토큰이 없습니다. `python -m econ_insta.ig_auth login` 을 먼저 실행하세요. (찾은 경로: {target})"
    )
