"""ai_brief: 해시태그 허구 차단, 캡션.

모델은 수치만 지어내는 게 아니라 해시태그도 지어낸다 — 어느 기사에도 없는 #픽버스를
붙였다. 같은 성질의 오류이므로 같은 방식으로 막는다.
"""

import unittest
from datetime import datetime

from econ_insta.ai_brief import AIBriefing, build_caption, filter_hashtags
from econ_insta.summarizer import Card

SOURCE = """오늘: 2026-07-14

기사 후보:
[1] (The Verge) 애플, 오픈AI 상대로 소송 제기
    애플이 오픈AI를 상대로 소송을 냈다.
[2] (AI타임스) 앤스로픽, 새 연구 공개
"""


class HashtagTest(unittest.TestCase):
    def test_기사에_없는_고유명사는_버린다(self):
        # '픽버스'는 실제로 모델이 지어냈던 태그다.
        self.assertEqual(filter_hashtags(["픽버스"], SOURCE), [])

    def test_기사에_있는_고유명사는_남긴다(self):
        self.assertEqual(filter_hashtags(["애플", "오픈AI"], SOURCE), ["애플", "오픈AI"])

    def test_일반명사는_기사에_없어도_남긴다(self):
        self.assertEqual(filter_hashtags(["인공지능", "LLM"], SOURCE), ["인공지능", "LLM"])

    def test_샵과_공백을_정리한다(self):
        self.assertEqual(filter_hashtags(["#애플", " ", ""], SOURCE), ["애플"])

    def test_띄어쓰기가_달라도_기사에_있으면_남긴다(self):
        self.assertEqual(filter_hashtags(["앤스로픽"], SOURCE), ["앤스로픽"])


class CaptionTest(unittest.TestCase):
    def _brief(self):
        return AIBriefing(
            headline="h",
            cards=[Card("제목", "본문", "The Verge"), Card("제목2", "본문2", "AI타임스")],
            caption_hook="hook",
            hashtags=["애플"],
        )

    def test_출처와_해시태그가_들어간다(self):
        caption = build_caption(self._brief(), datetime(2026, 7, 14))
        self.assertIn("The Verge", caption)
        self.assertIn("AI타임스", caption)
        self.assertIn("#애플", caption)
        self.assertIn("#인공지능", caption)  # BASE_HASHTAGS

    def test_투자유의_문구는_넣지_않는다(self):
        # 경제 콘텐츠의 의무지 AI 소식에는 맞지 않는다.
        caption = build_caption(self._brief(), datetime(2026, 7, 14))
        self.assertNotIn("투자", caption)

    def test_사진_크레딧은_주면_붙는다(self):
        caption = build_caption(self._brief(), datetime(2026, 7, 14), credits=("촬영자 (CC BY 4.0)",))
        self.assertIn("📷", caption)
        self.assertIn("CC BY 4.0", caption)


if __name__ == "__main__":
    unittest.main()
