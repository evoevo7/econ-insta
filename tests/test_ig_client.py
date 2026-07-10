"""HTTP 계층을 가짜로 두고 발행 흐름 전체를 구동한다."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from econ_insta import ig_auth, ig_client
from econ_insta.config import AppCredentials, StoredToken
from econ_insta.ig_client import InstagramClient, InstagramError


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """호출을 기록하고 미리 정해둔 응답을 순서대로 돌려준다."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def _next(self, method: str, url: str, params: dict) -> FakeResponse:
        self.calls.append((method, url, params))
        if not self._responses:
            raise AssertionError(f"예상하지 못한 추가 호출: {method} {url}")
        return FakeResponse(self._responses.pop(0))

    def get(self, url, params=None, timeout=None):
        return self._next("GET", url, params or {})

    def post(self, url, data=None, timeout=None):
        return self._next("POST", url, data or {})


def make_token() -> StoredToken:
    return StoredToken(access_token="LONG_TOKEN", user_id="17841400000000000", expires_at=time.time() + 86400)


class CarouselPublishTest(unittest.TestCase):
    def setUp(self):
        # time.sleep을 무력화해 폴링이 즉시 진행되게 한다.
        self._real_sleep = ig_client.time.sleep
        ig_client.time.sleep = lambda _: None

    def tearDown(self):
        ig_client.time.sleep = self._real_sleep

    def test_three_images_publish_as_carousel(self):
        session = FakeSession(
            [
                {"id": "c1"}, {"id": "c2"}, {"id": "c3"},          # 자식 컨테이너 3개
                {"status_code": "FINISHED"},
                {"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"},  # c2는 한 번 대기
                {"status_code": "FINISHED"},
                {"id": "CAROUSEL"},                                # 캐러셀 컨테이너
                {"status_code": "FINISHED"},
                {"id": "MEDIA_123"},                               # media_publish
                {"permalink": "https://www.instagram.com/p/abc/"},
            ]
        )
        client = InstagramClient(token=make_token(), session=session)

        result = client.publish_images(
            ["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"],
            caption="오늘의 경제 브리핑 #경제뉴스",
            alt_texts=["표지", "뉴스1", "지표"],
        )

        self.assertEqual(result.media_id, "MEDIA_123")
        self.assertEqual(result.container_id, "CAROUSEL")
        self.assertEqual(result.permalink, "https://www.instagram.com/p/abc/")

        # 자식 컨테이너는 is_carousel_item=true 로, 캡션 없이 생성되어야 한다.
        child_call = session.calls[0]
        self.assertEqual(child_call[0], "POST")
        self.assertTrue(child_call[1].endswith("/17841400000000000/media"))
        self.assertEqual(child_call[2]["is_carousel_item"], "true")
        self.assertEqual(child_call[2]["alt_text"], "표지")
        self.assertNotIn("caption", child_call[2])

        # 캐러셀 컨테이너에 자식이 콤마로 이어져 들어가고 캡션이 여기 붙는다.
        carousel_call = next(c for c in session.calls if c[2].get("media_type") == "CAROUSEL")
        self.assertEqual(carousel_call[2]["children"], "c1,c2,c3")
        self.assertEqual(carousel_call[2]["caption"], "오늘의 경제 브리핑 #경제뉴스")

        publish_call = next(c for c in session.calls if c[1].endswith("/media_publish"))
        self.assertEqual(publish_call[2]["creation_id"], "CAROUSEL")

    def test_single_image_skips_carousel(self):
        session = FakeSession(
            [
                {"id": "c1"},
                {"status_code": "FINISHED"},
                {"id": "MEDIA_1"},
                {"permalink": "https://www.instagram.com/p/xyz/"},
            ]
        )
        client = InstagramClient(token=make_token(), session=session)
        result = client.publish_images(["https://x/1.jpg"], caption="단일 게시물")

        self.assertEqual(result.media_id, "MEDIA_1")
        self.assertFalse(any(c[2].get("media_type") == "CAROUSEL" for c in session.calls))
        self.assertEqual(session.calls[0][2]["caption"], "단일 게시물")

    def test_container_error_raises(self):
        session = FakeSession([{"id": "c1"}, {"status_code": "ERROR"}])
        client = InstagramClient(token=make_token(), session=session)
        with self.assertRaisesRegex(InstagramError, "status_code=ERROR"):
            client.publish_images(["https://x/1.jpg"], caption="x")

    def test_graph_error_payload_surfaces_message(self):
        session = FakeSession([{"error": {"code": 9, "message": "The user has reached the maximum", "type": "OAuthException"}}])
        client = InstagramClient(token=make_token(), session=session)
        with self.assertRaisesRegex(InstagramError, "maximum"):
            client.publish_images(["https://x/1.jpg"], caption="x")

    def test_expired_token_rejected(self):
        stale = StoredToken(access_token="t", user_id="1", expires_at=time.time() - 1)
        with self.assertRaisesRegex(InstagramError, "만료"):
            InstagramClient(token=stale, session=FakeSession([]))


class ValidationTest(unittest.TestCase):
    def test_caption_length(self):
        with self.assertRaisesRegex(InstagramError, "한도"):
            ig_client.validate_caption("가" * 2201)

    def test_hashtag_count(self):
        with self.assertRaisesRegex(InstagramError, "해시태그"):
            ig_client.validate_caption("#태그 " * 31)

    def test_carousel_needs_at_least_two(self):
        client = InstagramClient(token=make_token(), session=FakeSession([]))
        with self.assertRaisesRegex(InstagramError, "2~10장"):
            client.create_carousel_container(["only-one"], "캡션")

    def test_carousel_max_ten(self):
        client = InstagramClient(token=make_token(), session=FakeSession([]))
        with self.assertRaisesRegex(InstagramError, "2~10장"):
            client.create_carousel_container([f"c{i}" for i in range(11)], "캡션")


class AuthTest(unittest.TestCase):
    creds = AppCredentials(app_id="123", app_secret="secret", redirect_uri="https://example.com/cb")

    def test_authorize_url_contains_scopes(self):
        url = ig_auth.authorize_url(self.creds)
        self.assertIn("https://www.instagram.com/oauth/authorize?", url)
        self.assertIn("client_id=123", url)
        self.assertIn("response_type=code", url)
        self.assertIn("instagram_business_basic%2Cinstagram_business_content_publish", url)
        self.assertIn("redirect_uri=https%3A%2F%2Fexample.com%2Fcb", url)

    def test_extract_code_strips_instagram_hash_suffix(self):
        # Instagram은 code 끝에 '#_' 를 붙여서 돌려준다. 그대로 쓰면 교환이 실패한다.
        self.assertEqual(ig_auth.extract_code("AQBx123#_"), "AQBx123")

    def test_extract_code_from_full_redirect_url(self):
        self.assertEqual(
            ig_auth.extract_code("https://example.com/cb?code=AQBx123#_"),
            "AQBx123",
        )

    def test_extract_code_from_url_without_code(self):
        with self.assertRaisesRegex(ig_auth.AuthError, "code 파라미터가 없습니다"):
            ig_auth.extract_code("https://example.com/cb?error=access_denied")


if __name__ == "__main__":
    unittest.main(verbosity=2)
