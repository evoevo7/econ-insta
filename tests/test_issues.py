import unittest
from datetime import datetime, timezone, timedelta
from econ_insta.collector import Article
from econ_insta.issues import keywords, rank_issues


KST = timezone(timedelta(hours=9))


def art(title, source, summary=""):
    return Article(
        title=title,
        link="http://x",
        source=source,
        summary=summary,
        language="ko",
        published=datetime(2026, 7, 16, 12, 0, 0, tzinfo=KST),
    )


class KeywordsTest(unittest.TestCase):
    def test_extracts_korean_and_drops_stopwords(self):
        kw = keywords("삼성전자 반도체 실적 오늘 발표")
        self.assertIn("삼성전자", kw)
        self.assertIn("반도체", kw)
        self.assertNotIn("오늘", kw)  # 불용어

    def test_single_char_dropped(self):
        self.assertNotIn("이", keywords("이 반도체"))

    def test_스톱워드가_바이라인_토큰을_거른다(self):
        """방어선: strip_byline이 새는 변형이 와도 2단어 문턱의 절반을 깎는다.

        기자 이름(김준태)은 열거 불가라 남는 것이 맞다 — 그래서 주 수정은 collector다.
        """
        self.assertEqual(keywords("김준태 기자 연합뉴스 특파원 매일경제 한국경제"), {"김준태"})


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
