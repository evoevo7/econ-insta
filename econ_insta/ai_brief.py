"""AI 뉴스 브리핑: 수집 → 요약 → 카드 → 발행.

경제 데일리와 같은 계정에 올리되 **다른 시리즈**로 읽히게 한다(kicker "AI 브리핑").
경제 쪽과 다른 점:
- 지표 카드가 없다. AI 뉴스에는 종가·환율이 없다.
- **투자유의 문구를 넣지 않는다.** 그건 경제 콘텐츠의 의무지 AI 소식에는 안 맞는다.
  대신 '기업 발표는 발표 주체를 밝힌다'는 규칙이 여기서의 정직성 장치다.
- 홍보성 보도자료가 훨씬 많다. 프롬프트에서 걸러낸다.

기사 저작권 원칙은 같다: 본문을 옮기지 말고 사실만 추출해 재작성, 출처 매체명 표기.

CLI:
    python -m econ_insta.ai_brief            # 수집·요약·렌더
    python -m econ_insta.ai_brief --publish out/2026-07-14-ai
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic
import requests

from .backgrounds import build_background
from .collector import Article, CollectError, FeedSpec, collect_articles, now_kst
from .config import PROJECT_ROOT, _load_dotenv
from .factcheck import unsupported_amounts
from .renderer import JPEG_QUALITY, FontSet, render_card, render_cover
from .summarizer import MAX_TOKENS, MODEL, Card, SummarizeError

EFFORT = "medium"

MIN_CARDS, MAX_CARDS = 3, 5
MAX_HASHTAGS = 6
HEADLINE_MAX, CARD_TITLE_MAX, CARD_BODY_MAX = 28, 34, 150

# 실측(2026-07-14)으로 살아 있는 것만 남겼다.
# - VentureBeat AI(venturebeat.com/category/ai/feed/)는 200을 주지만 **55일째 갱신이 없는 죽은
#   피드**다. 넣지 말 것.
# - AI타임스는 pubDate가 '2026-07-14 15:53:25'(RFC822 아님)라 파서를 고쳐야 읽힌다.
# - The Verge는 RSS가 아니라 Atom이다.
AI_FEEDS: dict[str, FeedSpec] = {
    "AI타임스": FeedSpec("https://www.aitimes.com/rss/allArticle.xml", quota=4),
    "TechCrunch": FeedSpec(
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        language="en",
        quota=3,
    ),
    "The Verge": FeedSpec(
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        language="en",
        max_age_hours=72,
        quota=2,
    ),
    "MIT Technology Review": FeedSpec(
        "https://www.technologyreview.com/feed/",
        language="en",
        max_age_hours=72,
        quota=2,
    ),
}

SYSTEM = f"""당신은 한국어 AI 카드뉴스의 에디터입니다.

오늘의 AI·기술 소식 후보 중 중요한 것을 골라 카드뉴스로 만듭니다.

고르는 기준:
- 실제로 무언가 **일어난** 소식을 고르십시오: 모델·제품 출시, 기능 공개, 정책·규제, 투자·인수,
  연구 결과, 사고·논란.
- **홍보성 보도자료를 배제하십시오**: 수상, 협약(MOU), 후원, 행사 개최, 인사, 단순 도입 사례,
  "업계 최초"를 자칭하는 자료. AI 뉴스에는 이런 것이 특히 많습니다.
- 같은 사건을 다룬 기사가 여럿이면 하나만 쓰십시오.

작성 원칙:
- 기사 문장을 그대로 옮기지 말고 완전히 새로운 문장으로 다시 쓰십시오 (저작권).
- **기업이 발표한 내용은 발표 주체를 밝히십시오** ("오픈AI는 ~라고 밝혔다"). 회사의 주장을
  검증된 사실처럼 단정하지 마십시오. 벤치마크·성능 수치는 특히 그렇습니다.
- 영어 기사는 한국어로 옮기되, 고유명사·모델명은 원문 표기를 함께 적어도 좋습니다.
- source에는 출처 매체명을 그대로 쓰십시오.

수치 규칙 (기계적으로 검증되며, 위반 시 카드가 폐기됩니다):
- headline에는 숫자를 쓰지 마십시오.
- 카드의 모든 수치는 제공된 기사 목록에 있는 값이어야 합니다. 단위 환산은 괜찮지만
  값을 바꾸거나 없는 값을 만들지 마십시오.

형식:
- headline은 표지 제목, {HEADLINE_MAX}자 이내.
- cards는 {MIN_CARDS}~{MAX_CARDS}장. title {CARD_TITLE_MAX}자 이내, body {CARD_BODY_MAX}자 이내 2~3문장.
- caption_hook은 캡션 첫머리 1~2문장. 숫자 없이 쓰십시오.
- bg_query: 표지 배경 사진을 찾을 영어 검색어 2~4단어. **사진으로 찍을 수 있는 구체적 대상**을
  쓰십시오 (예: "data center servers", "semiconductor wafer", "robot arm factory").
  "artificial intelligence" 같은 추상어는 엉뚱한 사진이 나옵니다."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,  # 구조화 출력은 이걸 명시하지 않으면 400을 준다
    "properties": {
        "headline": {"type": "string", "description": f"표지 제목, {HEADLINE_MAX}자 이내, 숫자 금지"},
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "source": {"type": "string", "description": "출처 매체명"},
                },
                "required": ["title", "body", "source"],
            },
        },
        "caption_hook": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "bg_query": {"type": "string"},
    },
    "required": ["headline", "cards", "caption_hook", "hashtags", "bg_query"],
}


@dataclass(frozen=True)
class AIBriefing:
    headline: str
    cards: list[Card]
    caption_hook: str
    hashtags: list[str] = field(default_factory=list)
    bg_query: str = ""
    dropped_cards: int = 0


def collect_ai(limit: int = 20) -> list[Article]:
    errors: list[str] = []
    articles = collect_articles(limit=limit, feeds=AI_FEEDS, errors=errors)
    for message in errors:
        print(f"  ! {message}")
    if not articles:
        raise CollectError("AI 기사를 한 건도 모으지 못했습니다.")
    return articles


def build_prompt(articles: list[Article]) -> str:
    lines = [f"오늘: {now_kst():%Y-%m-%d}", "", "기사 후보:"]
    for index, article in enumerate(articles, 1):
        lines.append(f"[{index}] ({article.source}) {article.title}")
        if article.summary:
            lines.append(f"    {article.summary}")
    return "\n".join(lines)


def _generate(client: anthropic.Anthropic, prompt: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "max_tokens":
        raise SummarizeError(f"응답이 max_tokens({MAX_TOKENS})에서 잘렸습니다.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise SummarizeError("응답에 텍스트 블록이 없습니다.")
    return json.loads(text)


def audit(payload: dict, source_text: str) -> dict[str, list[str]]:
    """근거 없는 수치를 찾는다. 경제 쪽 factcheck를 그대로 쓴다."""
    problems: dict[str, list[str]] = {}
    for bad in unsupported_amounts(payload["headline"], source_text):
        problems.setdefault("headline", []).append(bad)
    for index, card in enumerate(payload["cards"]):
        found = unsupported_amounts(f"{card['title']} {card['body']}", source_text)
        if found:
            problems[f"cards:{index}"] = found
    return problems


def summarize_ai(articles: list[Article], client: anthropic.Anthropic | None = None) -> AIBriefing:
    _load_dotenv()
    caller = client or anthropic.Anthropic()
    prompt = build_prompt(articles)

    payload = _generate(caller, prompt)
    problems = audit(payload, prompt)

    if problems:
        retry = (
            f"{prompt}\n\n[직전 시도의 문제 — 반드시 고칠 것]\n"
            f"{json.dumps(problems, ensure_ascii=False)}\n"
            "수치는 기사에 있는 값만 쓰고, headline에는 숫자를 쓰지 마십시오."
        )
        payload = _generate(caller, retry)
        problems = audit(payload, prompt)

    if "headline" in problems:
        raise SummarizeError(f"headline에 근거 없는 숫자가 남았습니다: {payload['headline']!r}")

    cards, dropped = [], 0
    for index, card in enumerate(payload["cards"]):
        if f"cards:{index}" in problems:
            dropped += 1
            continue
        cards.append(Card(title=card["title"], body=card["body"], source=card["source"]))

    if len(cards) < MIN_CARDS:
        raise SummarizeError(f"수치 검증 후 카드가 {len(cards)}장뿐입니다 (최소 {MIN_CARDS}장).")

    return AIBriefing(
        headline=payload["headline"],
        cards=cards[:MAX_CARDS],
        caption_hook=payload["caption_hook"],
        hashtags=filter_hashtags(payload["hashtags"], prompt)[:MAX_HASHTAGS],
        bg_query=payload["bg_query"].strip(),
        dropped_cards=dropped,
    )


BASE_HASHTAGS = ("AI", "인공지능", "테크뉴스", "카드뉴스")

# 기사에 없어도 허용하는 일반명사. 이 목록 밖의 태그는 기사에 실제로 나온 말이어야 한다.
GENERIC_TAGS = frozenset(
    {"AI", "인공지능", "테크뉴스", "카드뉴스", "머신러닝", "딥러닝", "LLM", "생성형AI",
     "챗봇", "빅테크", "반도체", "스타트업", "테크"}
)


def _clean_key(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def filter_hashtags(tags: list[str], source_text: str) -> list[str]:
    """기사에 없는 고유명사 태그를 버린다.

    모델은 해시태그도 지어낸다 — 실제로 어느 기사에도 없는 **#픽버스**를 붙였다.
    수치 허구와 같은 성질이다. 일반명사는 통과시키고, 그 밖의 태그는 기사 텍스트에
    실제로 등장할 때만 남긴다.
    """
    haystack = _clean_key(source_text)
    kept = []
    for tag in tags:
        clean = tag.lstrip("#").strip()
        if not clean:
            continue
        if clean in GENERIC_TAGS or _clean_key(clean) in haystack:
            kept.append(clean)
    return kept


def build_caption(brief: AIBriefing, when: datetime, credits: tuple[str, ...] = ()) -> str:
    lines = [brief.caption_hook, "", f"{when:%Y년 %m월 %d일} AI 브리핑", ""]
    lines += [f"· {card.title} ({card.source})" for card in brief.cards]

    sources = sorted({card.source for card in brief.cards})
    lines += ["", f"출처 · {' · '.join(sources)}"]
    if credits:
        lines += ["", f"📷 사진: {' · '.join(credits)}"]

    tags = list(dict.fromkeys([*brief.hashtags, *BASE_HASHTAGS]))
    lines += ["", " ".join(f"#{tag}" for tag in tags)]
    return "\n".join(lines)


def render(brief: AIBriefing, when: datetime, out_dir: Path) -> list[Path]:
    fonts = FontSet.discover()
    out_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    background = build_background([], brief.bg_query, errors=errors)
    for message in errors:
        print(f"  ! {message}")

    images = [
        render_cover(
            brief.headline,
            when,
            fonts,
            kicker="AI 브리핑",
            background=background.image if background else None,
        )
    ]
    images += [
        render_card(card, i, len(brief.cards), fonts) for i, card in enumerate(brief.cards, 1)
    ]

    paths = []
    for index, image in enumerate(images):
        path = out_dir / f"{index:02d}.jpg"
        image.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        paths.append(path)

    credits = background.credits if background else ()
    (out_dir / "caption.txt").write_text(build_caption(brief, when, credits), encoding="utf-8")
    return paths


RAW_BASE = "https://raw.githubusercontent.com/hakusancode/econ-insta/main"


def publish_rendered(out_dir: Path) -> int:
    from .ig_client import InstagramClient

    out_dir = out_dir.resolve()
    caption_path = out_dir / "caption.txt"
    images = sorted(out_dir.glob("[0-9][0-9].jpg"))
    if not caption_path.exists() or not images:
        print(f"카드나 캡션이 없습니다: {out_dir}")
        return 1

    rel = out_dir.relative_to(PROJECT_ROOT.resolve()).as_posix()
    urls = [f"{RAW_BASE}/{rel}/{path.name}" for path in images]
    for url in urls:
        response = requests.get(url, timeout=20, allow_redirects=False)
        if response.status_code != 200 or response.headers.get("Content-Type") != "image/jpeg":
            print(f"호스팅 확인 실패 ({response.status_code}): {url}")
            print("커밋·push 후 잠시 기다렸다가 다시 시도하세요 (raw CDN 전파에 시간이 걸립니다).")
            return 1

    result = InstagramClient().publish_images(urls, caption_path.read_text(encoding="utf-8"))
    print(f"발행 완료: media_id={result.media_id}")
    print(f"  {result.permalink}")
    return 0


def main() -> int:
    import sys

    if "--publish" in sys.argv:
        index = sys.argv.index("--publish")
        if index + 1 >= len(sys.argv):
            print("사용법: python -m econ_insta.ai_brief --publish out/<날짜>-ai")
            return 1
        return publish_rendered(Path(sys.argv[index + 1]))

    when = now_kst()
    articles = collect_ai()
    print(f"기사 {len(articles)}건 수집")

    brief = summarize_ai(articles)
    print(f"\n표지: {brief.headline}")
    for card in brief.cards:
        print(f"  · {card.title} ({card.source})")
    if brief.dropped_cards:
        print(f"  (수치 검증으로 {brief.dropped_cards}장 폐기)")

    out_dir = PROJECT_ROOT / "out" / f"{when:%Y-%m-%d}-ai"
    paths = render(brief, when, out_dir)
    print(f"\n카드 {len(paths)}장 → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
