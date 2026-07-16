# 단일 이슈 후크형 콘텐츠 구현 계획 (3단계a — 핵심)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 경제 브리핑을 "여러 기사 모음집"에서 **하나의 이슈를 훅→전개→마무리로 끌고 가는 단일 이슈 캐러셀**로 바꾼다. 이슈 선정은 **크로스소스 빈도**(이미 수집한 기사만으로 계산하는 1차 인기도 신호)로 후보를 좁힌 뒤 모델이 그 안에서 고른다.

**Architecture:** 새 순수 모듈 `econ_insta/issues.py`가 기사들을 이슈로 묶고 매체 수로 랭크한다. `summarizer.py`는 이 랭킹을 프롬프트에 실어 모델이 **리드 이슈 하나**를 골라 서사 카드를 쓰게 한다. `Card`에 **선택적** `role` 필드를 추가(기본 `None`)해 서사 국면을 표시하되, `render()`·다른 호출부는 건드리지 않는다(선택 필드라 무해). 팩트체크 전 계층 유지.

**Tech Stack:** Python 3.13, `anthropic`(구조화 출력), 표준 `unittest`. 외부 스크래핑·API 키 없음(그건 3단계b).

## Global Constraints

- 테스트 러너 표준 `unittest`(`python -m unittest discover -s tests -q`). 파이썬 실행 시 `PYTHONIOENCODING=utf-8`.
- **모델을 호출하는 테스트를 쓰지 않는다.** `summarize()` 테스트는 가짜 클라이언트(`_generate`가 호출하는 `caller.messages.create`를 스텁)로 결정적으로 돈다. 순수 함수(`issues.py`, `_validate`, `audit`)는 직접 테스트.
- **팩트체크 전부 유지**: `headline`·`indicator_note` 숫자 금지(`has_digits`), 본문 수치=자료 내 값(`unsupported_amounts`), 원/달러 방향(`wrong_won_direction`), 1회 재생성 후 남은 위반 카드 폐기, 폐기 후 `MIN_CARDS` 미달이면 발행 실패. 이 흐름을 바꾸지 말 것.
- `Card` 필드 추가는 **뒤에 기본값 있는 선택 필드**로만(`role: str | None = None`). `ai_brief.py`/`blog_brief.py`의 `Card(title=,body=,source=)` 생성이 그대로 동작해야 한다.
- `render()`(renderer.py)·발행 흐름은 이번 스코프에서 **수정하지 않는다**. 콘텐츠만 좋아진다. `role`의 시각 표시는 후속(4단계 이후).
- 커밋은 각 태스크 끝. 메시지 한국어 + 트레일러 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **단일 이슈 규칙을 프롬프트에 명시**(안 넣으면 모음집으로 회귀 — ai_brief에서 실증됨).

---

### Task 1: `issues.py` — 크로스소스 빈도 이슈 클러스터링

**Files:**
- Create: `econ_insta/issues.py`
- Test: `tests/test_issues.py`

**Interfaces:**
- Consumes: `econ_insta.collector.Article` (필드 `title: str`, `summary: str | None`, `source: str`).
- Produces:
  - `keywords(text: str) -> set[str]`
  - `@dataclass class Issue: articles: list[Article]; keywords: set[str]` + property `sources -> set[str]`, property `score -> tuple[int, int]` (= `(서로 다른 매체 수, 기사 수)`).
  - `rank_issues(articles: list[Article], *, min_shared: int = 2) -> list[Issue]` — 이슈를 `score` 내림차순으로 반환.

- [ ] **Step 1: 실패 테스트**

Create `tests/test_issues.py`:
```python
import unittest
from econ_insta.collector import Article
from econ_insta.issues import keywords, rank_issues


def art(title, source, summary=""):
    return Article(title=title, url="http://x", source=source, summary=summary, language="ko")


class KeywordsTest(unittest.TestCase):
    def test_extracts_korean_and_drops_stopwords(self):
        kw = keywords("삼성전자 반도체 실적 오늘 발표")
        self.assertIn("삼성전자", kw)
        self.assertIn("반도체", kw)
        self.assertNotIn("오늘", kw)  # 불용어

    def test_single_char_dropped(self):
        self.assertNotIn("이", keywords("이 반도체"))


class RankIssuesTest(unittest.TestCase):
    def test_same_event_across_sources_clusters(self):
        arts = [
            art("삼성전자 반도체 4분기 어닝 쇼크", "연합뉴스"),
            art("삼성전자 반도체 실적 급감 어닝", "매일경제"),
            art("한은 기준금리 동결 결정", "한국경제"),
        ]
        issues = rank_issues(arts)
        top = issues[0]
        self.assertEqual(len(top.articles), 2)          # 삼성 두 건이 한 이슈
        self.assertEqual(top.sources, {"연합뉴스", "매일경제"})

    def test_ranked_by_distinct_sources_first(self):
        arts = [
            art("A사 A사 A사 신제품 공개 이벤트", "연합뉴스"),   # 단일 매체 1건
            art("금리 인상 우려 확산 채권", "한국경제"),
            art("금리 인상 우려 채권 급등", "매일경제"),
            art("금리 인상 우려 코스피 하락", "WSJ"),
        ]
        issues = rank_issues(arts)
        self.assertEqual(issues[0].sources, {"한국경제", "매일경제", "WSJ"})  # 3개 매체가 최상위

    def test_no_shared_keywords_stay_separate(self):
        arts = [art("반도체 수출 증가", "연합뉴스"), art("배추 가격 폭등", "매일경제")]
        self.assertEqual(len(rank_issues(arts)), 2)

    def test_empty(self):
        self.assertEqual(rank_issues([]), [])
```

- [ ] **Step 2: 실행(실패)**

Run: `PYTHONIOENCODING=utf-8 python -m unittest tests.test_issues -v`
Expected: FAIL — `econ_insta.issues` 없음.

- [ ] **Step 3: 구현**

Create `econ_insta/issues.py`:
```python
"""기사들을 '이슈'로 묶고 크로스소스 빈도로 랭크한다.

외부 신호(네이버/다음 '많이 본 뉴스'·데이터랩) 없이, **이미 수집한 기사만으로** 계산하는
1차 인기도 신호다. 여러 매체가 같은 사건을 동시에 다룰수록 큰 이슈로 본다.
정확한 클러스터링이 목적이 아니라, 모델에 줄 **랭킹 힌트**를 만드는 게 목적이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .collector import Article

# 한글 2글자 이상 또는 영문 토큰. ai_brief._WORD_RE와 같은 계열.
_WORD_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9.\-]{1,}")

# 제목에 흔한 일반어. 이슈를 가르는 신호가 아니다.
_STOPWORDS = frozenset(
    """오늘 하루 이번 최근 요즘 올해 내년 지난 관련 대한 위한 통해 밝혀 밝혔다 전망 분석
    가능성 우려 기대 확산 논란 이슈 소식 뉴스 정리 발표 공개 예정 계획 추진 방침 결정
    시장 국내 해외 업계 세계 곳곳 그리고 그러나 한편 다시 함께 모두 최대 최고 역대""".split()
)


def keywords(text: str) -> set[str]:
    """제목·요약에서 이슈를 가르는 핵심어만 뽑는다."""
    out: set[str] = set()
    for word in _WORD_RE.findall(text):
        key = word.lower()
        if len(key) < 2 or key in _STOPWORDS:
            continue
        out.add(key)
    return out


@dataclass
class Issue:
    articles: list[Article]
    keywords: set[str] = field(default_factory=set)
    """시드 기사의 핵심어. 클러스터가 커져도 드리프트하지 않도록 시드만 유지한다."""

    @property
    def sources(self) -> set[str]:
        return {a.source for a in self.articles}

    @property
    def score(self) -> tuple[int, int]:
        """크로스소스 빈도: (서로 다른 매체 수, 기사 수). 큰 것이 큰 이슈."""
        return (len(self.sources), len(self.articles))


def rank_issues(articles: list[Article], *, min_shared: int = 2) -> list[Issue]:
    """기사를 이슈로 묶어 score 내림차순으로 반환한다.

    탐욕적 클러스터링: 각 기사를 핵심어가 가장 많이 겹치는(>= min_shared) 기존 이슈에
    붙이고, 없으면 새 이슈를 연다. 매칭은 각 이슈의 **시드 핵심어**에만 한다(과합병 방지).
    """
    issues: list[Issue] = []
    for article in articles:
        kw = keywords(f"{article.title} {article.summary or ''}")
        best: Issue | None = None
        best_overlap = 0
        for issue in issues:
            overlap = len(kw & issue.keywords)
            if overlap >= min_shared and overlap > best_overlap:
                best, best_overlap = issue, overlap
        if best is None:
            issues.append(Issue(articles=[article], keywords=kw))
        else:
            best.articles.append(article)
    return sorted(issues, key=lambda i: i.score, reverse=True)
```

- [ ] **Step 4: 실행(통과)**

Run: `PYTHONIOENCODING=utf-8 python -m unittest tests.test_issues -v`
Expected: PASS 6건.

> 주의: `Article` 생성자 인자 순서·필드명은 `collector.py`의 실제 정의를 따를 것(테스트의 `art()` 헬퍼가 키워드 인자를 쓰므로 필드명만 맞으면 된다). `Article`에 `language` 등 추가 필수 필드가 있으면 `art()` 헬퍼에 채워 넣어라(구현 전 `collector.py`의 `class Article` 확인).

- [ ] **Step 5: 커밋**

```bash
git add econ_insta/issues.py tests/test_issues.py
git commit -m "issues.py: 크로스소스 빈도로 기사→이슈 클러스터링·랭크"
```

---

### Task 2: 스키마·`Card.role`·본문 상한·검증

**Files:**
- Modify: `econ_insta/summarizer.py` (`Card`, `SCHEMA`, `CARD_BODY_MAX`, `_validate`)
- Test: `tests/test_summarizer_schema.py`

**Interfaces:**
- Produces: `Card(title, body, source, role=None)` — `role: str | None = None`. `SCHEMA.cards.items`에 `role`(선택) 추가. `CARD_BODY_MAX = 160`.

- [ ] **Step 1: 실패 테스트**

Create `tests/test_summarizer_schema.py`:
```python
import unittest
from econ_insta.summarizer import Card, CARD_BODY_MAX, _validate, SummarizeError


class CardRoleTest(unittest.TestCase):
    def test_role_defaults_none(self):
        self.assertIsNone(Card(title="t", body="b", source="s").role)

    def test_role_accepts_value(self):
        self.assertEqual(Card(title="t", body="b", source="s", role="무슨 일").role, "무슨 일")

    def test_legacy_three_arg_still_works(self):
        # ai_brief / blog_brief 가 이렇게 만든다
        Card(title="t", body="b", source="s")


class BodyMaxTest(unittest.TestCase):
    def test_body_max_is_160(self):
        self.assertEqual(CARD_BODY_MAX, 160)

    def test_validate_accepts_150_char_body(self):
        payload = {
            "headline": "짧은 훅",
            "indicator_note": "지표 흐름 코멘트",
            "cards": [
                {"title": "제목", "body": "가" * 150, "source": "연합뉴스"}
                for _ in range(3)
            ],
        }
        _validate(payload)  # 예외 없어야 함 (기존 120 상한이면 여기서 터졌다)

    def test_validate_rejects_over_limit_body(self):
        payload = {
            "headline": "짧은 훅",
            "indicator_note": "코멘트",
            "cards": [{"title": "제목", "body": "가" * (CARD_BODY_MAX + 1), "source": "연합뉴스"}] * 3,
        }
        with self.assertRaises(SummarizeError):
            _validate(payload)
```

- [ ] **Step 2: 실행(실패)**

Run: `PYTHONIOENCODING=utf-8 python -m unittest tests.test_summarizer_schema -v`
Expected: FAIL — `Card`에 `role` 없음 / `CARD_BODY_MAX`가 120.

- [ ] **Step 3: 구현**

`summarizer.py`에서:

1) `Card`에 선택 필드 추가:
```python
@dataclass(frozen=True)
class Card:
    title: str
    body: str
    source: str
    role: str | None = None
    """서사 국면 라벨(무슨 일/왜/반응/앞으로). 없어도 된다."""
```

2) `CARD_BODY_MAX = 120` → `CARD_BODY_MAX = 160`.

3) `SCHEMA`의 카드 아이템에 `role`을 **선택 속성**으로 추가(‘required’에는 넣지 않는다):
```python
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "source": {"type": "string", "description": "출처 매체명(복수면 대표 1곳 또는 'A·B')"},
                    "role": {"type": "string", "description": "서사 국면: 무슨 일 | 왜 | 반응 | 앞으로 (선택)"},
                },
                "required": ["title", "body", "source"],
```

`_validate`는 길이만 보므로 `CARD_BODY_MAX` 상수만 바뀌면 자동 반영된다(코드 수정 불필요). 확인만 할 것.

- [ ] **Step 4: 실행(통과) + 회귀**

Run: `PYTHONIOENCODING=utf-8 python -m unittest tests.test_summarizer_schema -v`
Then: `PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -q`
Expected: 신규 통과 + 기존 전부 통과(`ai_brief`/`blog_brief`의 `Card(...)` 3-인자 생성 포함).

- [ ] **Step 5: 커밋**

```bash
git add econ_insta/summarizer.py tests/test_summarizer_schema.py
git commit -m "summarizer 스키마: Card.role 선택 필드 + 본문 상한 120→160"
```

---

### Task 3: 단일 이슈 프롬프트 + `summarize()` 통합

**Files:**
- Modify: `econ_insta/summarizer.py` (`SYSTEM`, `build_prompt`, `summarize`)
- Test: `tests/test_summarize_single_issue.py`

**Interfaces:**
- Consumes: `econ_insta.issues.rank_issues`, `DailyBrief`(`articles`, `quotes`, `collected_at`).
- Produces: `summarize(brief, client=None, model=MODEL) -> Briefing` (시그니처 유지). 내부적으로 이슈 랭킹을 프롬프트에 실어 **단일 이슈 서사**를 생성. 카드에 `role`이 오면 `Card.role`에 채운다.

- [ ] **Step 1: 실패 테스트 (가짜 클라이언트, 모델 미호출)**

Create `tests/test_summarize_single_issue.py`:
```python
import json
import unittest
from datetime import datetime
from types import SimpleNamespace

from econ_insta.collector import Article, DailyBrief, Quote
from econ_insta.summarizer import summarize, build_prompt


def art(title, source, summary=""):
    return Article(title=title, url="http://x", source=source, summary=summary, language="ko")


class FakeMessages:
    """caller.messages.create 를 흉내낸다. 넘어온 프롬프트를 기록하고 고정 JSON을 돌려준다."""
    def __init__(self, payload):
        self._payload = payload
        self.last_prompt = None

    def create(self, *, model, max_tokens, system, thinking, output_config, messages):
        self.last_prompt = messages[0]["content"]
        text = json.dumps(self._payload, ensure_ascii=False)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        )


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


PAYLOAD = {
    "headline": "삼성 반도체, 시장이 얼어붙었다",
    "indicator_note": "위험 회피 심리가 지표 전반에 번졌다",
    "cards": [
        {"title": "무슨 일", "body": "삼성전자가 어닝 쇼크를 냈다.", "source": "연합뉴스", "role": "무슨 일"},
        {"title": "왜", "body": "메모리 가격 급락이 원인으로 지목됐다.", "source": "매일경제", "role": "왜"},
        {"title": "앞으로", "body": "업계는 감산 여부를 주시하고 있다.", "source": "한국경제", "role": "앞으로"},
    ],
}


def sample_brief():
    arts = [
        art("삼성전자 반도체 어닝 쇼크", "연합뉴스"),
        art("삼성전자 반도체 실적 급감", "매일경제"),
        art("한은 기준금리 동결", "한국경제"),
    ]
    quotes = [Quote(symbol="^KS11", name="코스피", price=2981.4, change_pct=-2.14)]
    return DailyBrief(articles=arts, quotes=quotes, collected_at=datetime(2026, 7, 16), errors=[])


class SummarizeSingleIssueTest(unittest.TestCase):
    def test_returns_cards_with_roles(self):
        client = FakeClient(PAYLOAD)
        briefing = summarize(sample_brief(), client=client)
        self.assertEqual(briefing.headline, PAYLOAD["headline"])
        self.assertEqual(len(briefing.cards), 3)
        self.assertEqual(briefing.cards[0].role, "무슨 일")

    def test_prompt_contains_single_issue_instruction(self):
        client = FakeClient(PAYLOAD)
        summarize(sample_brief(), client=client)
        prompt = client.messages.last_prompt
        self.assertIn("이슈", prompt)          # 이슈 후보가 프롬프트에 실렸다
        self.assertIn("삼성전자", prompt)       # 크로스소스 상위 이슈가 후보로 보인다

    def test_build_prompt_ranks_issues(self):
        prompt = build_prompt(sample_brief())
        # 삼성(2매체) 이슈가 금리(1매체)보다 먼저 온다
        self.assertLess(prompt.index("삼성전자"), prompt.index("기준금리"))
```

- [ ] **Step 2: 실행(실패)**

Run: `PYTHONIOENCODING=utf-8 python -m unittest tests.test_summarize_single_issue -v`
Expected: FAIL — 현재 `build_prompt`는 이슈 랭킹을 안 실음 / `Card`에 `role` 미연결.

- [ ] **Step 3: 구현**

`summarizer.py`에서:

1) `SYSTEM`을 단일 이슈 훅형으로 교체(팩트체크 문구는 유지). 핵심 추가:
```
오늘의 후보 이슈는 **여러 매체가 함께 다룬 순서(인기도)**로 정렬돼 제시됩니다.

만드는 법:
- **가장 화제성이 큰 이슈 하나**를 고르십시오(대개 첫 번째 후보). 그 이슈 하나만 다룹니다.
- **여러 이슈를 한 게시물에 섞지 마십시오.** 표지와 모든 카드가 같은 사건이어야 합니다.
- 고른 이슈에 묶인 기사들을 재료로, 표지=훅 한 문장, 카드=서사로 풀어냅니다:
  · 카드1 무슨 일: 핵심 사실(무엇이·얼마나)
  · 카드2 왜/배경: 맥락
  · 카드3 반응/파장: 시장·업계 반응
  · 카드4 앞으로: 다음 관전 포인트(마무리 한 방)
  각 카드 role에 국면 라벨(무슨 일|왜|반응|앞으로)을 넣으십시오.
- headline은 밋밋한 요약이 아니라 **스크롤을 멈추게 하는 훅 카피**로. (숫자 금지는 유지)
- 한 이슈로 3장을 채울 재료가 부족하면, 다음 후보 이슈로 바꾸십시오. 억지로 추측해 채우지 마십시오.
```
(기존 저작권·사실정확성·수치 규칙 블록은 그대로 둔다. "카드는 3~5장, 파급력 큰 것부터 고르십시오" 같은 **모음집 지시 문장은 삭제**한다.)

2) `build_prompt`를 이슈 랭킹 기반으로 교체:
```python
def render_issue(issue, index: int) -> str:
    sources = ", ".join(sorted(issue.sources))
    lines = [f"[이슈 {index}] 매체 {len(issue.sources)}곳({sources}), 기사 {len(issue.articles)}건"]
    for article in issue.articles:
        has_body = bool(article.summary)
        lines.append(f"  - ({article.source}) {article.title}  [본문:{'있음' if has_body else '없음'}]")
        if has_body:
            lines.append(f"      {article.summary}")
    return "\n".join(lines)


def build_prompt(brief: DailyBrief) -> str:
    if not brief.articles:
        raise SummarizeError("요약할 기사가 없습니다.")

    from .issues import rank_issues
    issues = rank_issues(brief.articles)

    quotes = "\n".join(
        f"  {q.name}: {q.price_text} ({q.change_text})" for q in brief.quotes
    ) or "  (지표 수집 실패)"
    blocks = "\n\n".join(render_issue(iss, i) for i, iss in enumerate(issues, 1))

    return (
        f"오늘 날짜: {brief.collected_at:%Y년 %m월 %d일}\n\n"
        f"[시장지표]\n{quotes}\n\n"
        f"[후보 이슈 {len(issues)}개 — 화제성(매체 수) 내림차순]\n{blocks}\n\n"
        "가장 화제성이 큰 이슈 하나를 골라 단일 이슈 브리핑을 만드십시오."
    )
```

3) `summarize()`에서 카드 생성 시 `role`을 전달(있으면):
```python
    cards = [
        Card(title=c["title"], body=c["body"], source=c["source"], role=c.get("role"))
        for i, c in enumerate(payload["cards"]) if i not in dropped
    ]
```
(나머지 `summarize` 로직 — 생성·감사·재시도·폐기·`MIN_CARDS` 검사 — 은 그대로 둔다. `audit`/`_validate`/`_describe`는 손대지 않는다.)

- [ ] **Step 4: 실행(통과)**

Run: `PYTHONIOENCODING=utf-8 python -m unittest tests.test_summarize_single_issue -v`
Expected: PASS 3건.

- [ ] **Step 5: 전체 회귀**

Run: `PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -q`
Expected: 전부 통과. 기존 `summarizer` 관련 테스트가 옛 `build_prompt` 문자열 형식을 하드코딩해 깨지면, **단일 이슈 형식에 맞게 단언을 갱신**한다(계약: 이슈 후보가 실리고, 지표가 실리고, 날짜가 실린다). 단언을 지우지 말고 고칠 것.

- [ ] **Step 6: 커밋**

```bash
git add econ_insta/summarizer.py tests/test_summarize_single_issue.py
git commit -m "summarize: 단일 이슈 후크형(크로스소스 랭킹 프롬프트 + role 연결)"
```

---

## 이 계획이 커버하는 스펙 항목 (자기 점검)

- §4.1 크로스소스 빈도로 이슈 후보 좁히기 → Task 1, 3 ✅ (네이버/다음 스크래핑·데이터랩·소스 확대·하루 3건은 **3단계b로 분리** — 이 계획 밖)
- §4.1 N기사→1이슈 묶기, 재료 부족 시 폴백(모델이 다음 후보로) → Task 3 프롬프트 ✅
- §4.2 훅→전개→마무리 서사, role 국면 라벨 → Task 2(role), Task 3(프롬프트) ✅
- §4.3 스키마 role 추가, 본문 상한 160, 팩트체크 유지, 단일 이슈 규칙 명시 → Task 2, 3 ✅
- §4.4 조용한 날 폴백은 모델 지시로 처리(재료 부족 시 다음 이슈). 데이터 형태 변경(`Card.role`)은 선택 필드라 렌더·발행 무파급 → Task 2 ✅

## 스코프 밖 (후속)
- **3단계b:** 네이버/다음 '많이 본 뉴스' 스크래핑·네이버 데이터랩·소스 9곳 확대·하루 3건 발행(`render()`/발행 다건화). 외부 데이터·키·레이트리밋 → 별도 계획.
- **4단계:** 이미지 소싱(`backgrounds.py` 인물>로고>실사>그래픽, 사물사진 차단, 케빈 워시 소싱) — A→B의 B. 단일 이슈가 생겼으니 이제 인물/실사 커버가 가능.
- `Card.role`의 **시각 표시**(카드에 국면 라벨 렌더) — 원하면 4단계 이후 render_card에 소폭 추가.
