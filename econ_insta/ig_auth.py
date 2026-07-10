"""Instagram Business Login (OAuth 2.0) 토큰 발급 및 갱신.

흐름:
    1) authorize URL을 브라우저로 열어 로그인/권한 승인
    2) redirect_uri로 돌아온 주소의 ?code=... 를 복사 (페이지가 404여도 무방)
    3) code -> 단기 토큰(1시간) -> 장기 토큰(60일)
    4) 60일마다 refresh (24시간 이상 지난 토큰만 갱신 가능)

CLI:
    python -m econ_insta.ig_auth login
    python -m econ_insta.ig_auth refresh
    python -m econ_insta.ig_auth status
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.parse

import requests

from .config import (
    AUTHORIZE_URL,
    DEFAULT_SCOPES,
    GRAPH_HOST,
    TOKEN_EXCHANGE_URL,
    AppCredentials,
    ConfigError,
    StoredToken,
    load_token,
    save_token,
)

TIMEOUT = 30


class AuthError(RuntimeError):
    """토큰 발급/갱신 실패."""


def _check(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        raise AuthError(f"JSON이 아닌 응답 (HTTP {response.status_code}): {response.text[:300]}") from None

    if "error" in payload or "error_message" in payload:
        raise AuthError(f"Instagram 오류 (HTTP {response.status_code}): {payload}")
    if not response.ok:
        raise AuthError(f"HTTP {response.status_code}: {payload}")
    return payload


def authorize_url(creds: AppCredentials, scopes=DEFAULT_SCOPES, state: str | None = None) -> str:
    params = {
        "client_id": creds.app_id,
        "redirect_uri": creds.redirect_uri,
        "response_type": "code",
        "scope": ",".join(scopes),
    }
    if state:
        params["state"] = state
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def extract_code(raw: str) -> str:
    """사용자가 붙여넣은 값에서 authorization code만 뽑는다.

    전체 리다이렉트 URL을 붙여넣어도 되고 code 값만 붙여넣어도 된다.
    Instagram은 code 끝에 '#_' 를 붙여서 돌려주므로 반드시 제거해야 한다.
    """
    raw = raw.strip()
    if not raw:
        raise AuthError("빈 값입니다.")

    if raw.startswith("http://") or raw.startswith("https://"):
        query = urllib.parse.urlparse(raw).query
        values = urllib.parse.parse_qs(query).get("code")
        if not values:
            raise AuthError(f"URL에 code 파라미터가 없습니다: {raw[:120]}")
        raw = values[0]

    return raw.split("#")[0]


def exchange_code(creds: AppCredentials, code: str) -> dict:
    """authorization code -> 단기 토큰. {access_token, user_id, permissions} 반환."""
    response = requests.post(
        TOKEN_EXCHANGE_URL,
        data={
            "client_id": creds.app_id,
            "client_secret": creds.app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": creds.redirect_uri,
            "code": code,
        },
        timeout=TIMEOUT,
    )
    return _check(response)


def exchange_long_lived(creds: AppCredentials, short_token: str) -> dict:
    """단기 토큰 -> 장기 토큰(60일). {access_token, token_type, expires_in} 반환."""
    response = requests.get(
        f"{GRAPH_HOST}/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": creds.app_secret,
            "access_token": short_token,
        },
        timeout=TIMEOUT,
    )
    return _check(response)


def refresh_long_lived(long_token: str) -> dict:
    """장기 토큰 갱신. 발급 후 24시간이 지나야 하고 만료 전이어야 한다."""
    response = requests.get(
        f"{GRAPH_HOST}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": long_token},
        timeout=TIMEOUT,
    )
    return _check(response)


def login(code: str | None = None) -> StoredToken:
    creds = AppCredentials.from_env()

    if code is None:
        url = authorize_url(creds)
        print("\n1) 아래 주소를 브라우저에서 여세요:\n")
        print(f"   {url}\n")
        print("2) 로그인·권한 승인 후 돌아온 주소창의 내용을 통째로 복사해 붙여넣으세요.")
        print(f"   ({creds.redirect_uri} 페이지가 404로 보여도 정상입니다.)\n")
        code = input("리다이렉트된 URL 또는 code: ")

    code = extract_code(code)

    short = exchange_code(creds, code)
    print(f"단기 토큰 발급 완료 (user_id={short.get('user_id')}, 권한={short.get('permissions')})")

    long = exchange_long_lived(creds, short["access_token"])
    expires_in = int(long.get("expires_in", 60 * 86400))

    token = StoredToken(
        access_token=long["access_token"],
        user_id=str(short.get("user_id", "")),
        expires_at=time.time() + expires_in,
    )
    path = save_token(token)
    print(f"장기 토큰 저장 완료: {path} (약 {token.days_left:.0f}일 유효)")
    return token


def refresh() -> StoredToken:
    current = load_token()
    result = refresh_long_lived(current.access_token)
    expires_in = int(result.get("expires_in", 60 * 86400))

    token = StoredToken(
        access_token=result["access_token"],
        user_id=current.user_id,
        expires_at=time.time() + expires_in,
    )
    save_token(token)
    print(f"토큰 갱신 완료 (약 {token.days_left:.0f}일 유효)")
    return token


def status() -> None:
    token = load_token()
    state = "만료됨" if token.is_expired else f"{token.days_left:.1f}일 남음"
    print(f"user_id : {token.user_id or '(미상)'}")
    print(f"토큰    : ...{token.access_token[-8:]}")
    print(f"상태    : {state}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="econ_insta.ig_auth", description="Instagram 토큰 관리")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="최초 토큰 발급")
    p_login.add_argument("--code", help="authorization code 또는 리다이렉트 URL (생략 시 대화형)")

    sub.add_parser("refresh", help="장기 토큰 갱신 (60일마다)")
    sub.add_parser("status", help="현재 토큰 상태 확인")
    sub.add_parser("url", help="authorize URL만 출력")

    args = parser.parse_args(argv)

    try:
        if args.command == "login":
            login(args.code)
        elif args.command == "refresh":
            refresh()
        elif args.command == "status":
            status()
        elif args.command == "url":
            print(authorize_url(AppCredentials.from_env()))
    except (AuthError, ConfigError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
