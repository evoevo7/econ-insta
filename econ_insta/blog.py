"""매크로 비욘드(성상현) 네이버 블로그 글 수집.

블로거 승인을 받아 「요약 + 출처 표기 + 원문 링크」 형태로만 발행한다.
내용이 뉴스 사실이 아니라 분석·견해(창작물)이므로, 요약할 때는 견해를 필자에게
귀속시켜 서술해야 한다 ("필자는 ~라고 본다").

RSS description은 약 360자에서 잘린다. 전문은 모바일 페이지(m.blog.naver.com)를
모바일 UA로 받아 SmartEditor ONE 컨테이너(se-main-container)에서 뽑는다.
PC 주소(blog.naver.com)는 iframe이라 직접 파싱이 안 된다.

CLI:
    python -m econ_insta.blog          # 최신 시황 글 목록 + 전문 미리보기
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser

import requests

from .collector import CollectError, clean_text, parse_pubdate

BLOG_ID = "ssh_fedinsight"
BLOG_NAME = "매크로 비욘드"
AUTHOR = "성상현"
RSS_URL = f"https://rss.blog.naver.com/{BLOG_ID}.xml"

# 시황·매크로 분석 글만 발행 대상이다. 「투자에 대한 관점」 같은 투자심리 에세이는 제외.
MARKET_CATEGORY_KEYWORD = "매크로 인사이트"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
TIMEOUT = 20

_POST_LINK = re.compile(r"blog\.naver\.com/([\w.-]+)/(\d+)")
# 글 끝 맺음말("이상입니다 … P.S …")은 요약 재료가 아니다. 후반부에서만 자른다.
_CLOSING = re.compile(r"(이상입니다|P\.?S[.:）)]?\s)", re.IGNORECASE)


class BlogError(RuntimeError):
    """블로그 수집 실패."""


@dataclass(frozen=True)
class BlogPost:
    title: str
    link: str
    """원문 링크 (추적 파라미터 제거된 정규형)."""
    published: datetime
    category: str = ""
    description: str = ""
    body: str = ""

    @property
    def is_market_post(self) -> bool:
        return MARKET_CATEGORY_KEYWORD in self.category


def canonical_link(link: str) -> str:
    """RSS 링크의 ?fromRss=... 추적 파라미터를 걷어낸 원문 주소."""
    match = _POST_LINK.search(link)
    if not match:
        raise BlogError(f"글 주소 형식이 아닙니다: {link}")
    return f"https://blog.naver.com/{match.group(1)}/{match.group(2)}"


def mobile_link(link: str) -> str:
    match = _POST_LINK.search(link)
    if not match:
        raise BlogError(f"글 주소 형식이 아닙니다: {link}")
    return f"https://m.blog.naver.com/{match.group(1)}/{match.group(2)}"


def parse_rss(xml_bytes: bytes) -> list[BlogPost]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise BlogError(f"RSS 파싱 실패 ({exc})") from exc

    posts: list[BlogPost] = []
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        try:
            published = parse_pubdate(item.findtext("pubDate") or "")
        except CollectError:
            continue
        posts.append(
            BlogPost(
                title=title,
                link=canonical_link(link),
                published=published,
                category=clean_text(item.findtext("category") or ""),
                description=clean_text(item.findtext("description") or ""),
            )
        )
    return posts


def fetch_posts(session: requests.Session | None = None) -> list[BlogPost]:
    caller = session or requests
    try:
        response = caller.get(RSS_URL, headers={"User-Agent": MOBILE_UA}, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BlogError(f"RSS 요청 실패 ({exc})") from exc
    return parse_rss(response.content)


class _MainContainerParser(HTMLParser):
    """se-main-container 안의 텍스트만 모은다. 블록 태그 경계는 줄바꿈으로 바꾼다."""

    _BLOCK_TAGS = frozenset({"p", "div", "h1", "h2", "h3", "h4", "li", "br", "table", "tr"})
    _SKIP_TAGS = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        classes = dict(attrs).get("class", "")
        if self._depth == 0:
            if tag == "div" and "se-main-container" in classes:
                self._depth = 1
            return
        self._depth += 1
        if tag in self._SKIP_TAGS:
            self._skip_depth = self._depth
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 0:
            return
        if self._skip_depth and self._depth <= self._skip_depth:
            self._skip_depth = 0
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth > 0 and not self._skip_depth:
            self._chunks.append(data)

    @property
    def text(self) -> str:
        raw = "".join(self._chunks).replace("​", "").replace("\xa0", " ")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
        return "\n".join(line for line in lines if line)


def strip_closing(text: str) -> str:
    """글 후반부의 맺음말("이상입니다 … P.S …")을 잘라낸다.

    본문 중간의 우연한 일치를 자르지 않도록 뒤쪽 40%에서만 찾는다.
    """
    start = int(len(text) * 0.6)
    match = _CLOSING.search(text, start)
    return text[: match.start()].rstrip() if match else text


def fetch_body(link: str, session: requests.Session | None = None) -> str:
    caller = session or requests
    url = mobile_link(link)
    try:
        response = caller.get(url, headers={"User-Agent": MOBILE_UA}, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BlogError(f"본문 요청 실패 ({exc})") from exc

    parser = _MainContainerParser()
    parser.feed(response.text)
    body = strip_closing(parser.text)
    if len(body) < 200:
        raise BlogError(f"본문 추출 결과가 너무 짧습니다 ({len(body)}자): {url}")
    return body


def latest_market_post(session: requests.Session | None = None) -> BlogPost:
    """가장 최근의 시황·매크로 글을 전문과 함께 돌려준다."""
    posts = fetch_posts(session=session)
    for post in posts:  # RSS는 최신순
        if post.is_market_post:
            body = fetch_body(post.link, session=session)
            return BlogPost(
                title=post.title,
                link=post.link,
                published=post.published,
                category=post.category,
                description=post.description,
                body=body,
            )
    raise BlogError("시황·매크로 카테고리 글을 찾지 못했습니다.")


def main() -> int:
    posts = fetch_posts()
    print(f"최근 글 {len(posts)}건")
    for post in posts[:8]:
        marker = "●" if post.is_market_post else " "
        print(f"  {marker} {post.published:%m-%d %H:%M}  [{post.category}] {post.title}")

    post = latest_market_post()
    print(f"\n■ 최신 시황 글: {post.title} ({post.published:%Y-%m-%d})")
    print(f"  {post.link}")
    print(f"  전문 {len(post.body)}자, 앞부분:\n")
    print(post.body[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
