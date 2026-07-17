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
    시장 국내 해외 업계 세계 곳곳 그리고 그러나 한편 다시 함께 모두 최대 최고 역대
    기자 특파원 연합뉴스 한국경제 매일경제""".split()
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
