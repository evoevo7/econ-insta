# econ-insta

경제뉴스 데일리 브리핑을 인스타그램에 자동 발행하는 파이프라인.

현재 완료된 범위는 **Instagram 발행 연동(1단계)** 이다. 뉴스 수집·요약·카드 이미지 생성은 다음 단계.

```
[수집] RSS + 지표      (예정)
[요약] Claude API      (예정)
[렌더] Pillow 카드     (예정)
[호스팅] GitHub raw    (예정)
[발행] Instagram API   ← 완료
```

## 왜 이미지 호스팅이 필요한가

Instagram 발행 API는 이미지 파일을 직접 업로드받지 않는다. `image_url`에 **공개 접근 가능한 JPEG URL**을 넘기면 Instagram이 그 주소로 이미지를 가져간다. 그래서 카드 이미지를 어딘가(GitHub 저장소 raw URL 등)에 먼저 올려야 한다.

발행은 항상 2단계다: 컨테이너 생성 → `media_publish`. 캐러셀은 자식 컨테이너를 각각 만든 뒤 부모 컨테이너로 묶는다.

---

## 사용자가 직접 해야 하는 설정

### 1. 인스타그램 프로페셔널 계정 만들기

1. 인스타그램 앱에서 새 계정 생성 (경제뉴스 전용)
2. 설정 → 계정 유형 및 도구 → **프로페셔널 계정으로 전환**
3. 카테고리는 `뉴스 및 미디어` 또는 `개인 블로그` 선택
4. 비즈니스/크리에이터 중 아무거나 무방

> Facebook 페이지 연결은 **필요 없다.** Instagram Login 방식을 쓰기 때문이다.
> (Facebook Login 방식은 페이지가 필요하지만 이 프로젝트는 쓰지 않는다.)

### 2. Meta 개발자 앱 등록

1. https://developers.facebook.com → 로그인 → **내 앱 → 앱 만들기**
2. 사용 사례에서 **"Instagram API 설정"** 계열 선택
3. 앱 대시보드 → **Instagram → API 설정** 진입
4. **"Instagram 로그인이 있는 Instagram API"** 섹션에서:
   - `Instagram 앱 ID` / `Instagram 앱 시크릿` 확인 → `.env`에 기록
   - **비즈니스 로그인 설정** → **OAuth 리디렉션 URI** 등록
5. 앱에 인스타 계정 연결 (테스트 사용자로 본인 계정 추가 후 수락)

#### 리디렉션 URI는 뭘 넣어야 하나

HTTPS만 허용된다. 서버가 없어도 되며, 코드를 주소창에서 복사할 것이므로 **404가 떠도 상관없다.**
GitHub Pages 주소나 `https://localhost/callback`를 넣고, `.env`의 `IG_REDIRECT_URI`와 **문자 하나까지 동일하게** 맞춘다.

### 3. 권한 신청 (앱 심사)

`instagram_business_basic`, `instagram_business_content_publish` 두 개를 신청한다.
심사에 **2~4주** 걸리므로 지금 바로 넣어두는 게 좋다.

개발 모드에서는 심사 없이도 **본인(앱 관리자/테스터) 계정에 한해** 발행이 동작한다.
즉 심사를 기다리는 동안 이 코드로 실제 테스트를 할 수 있다.

---

## 설치와 토큰 발급

```powershell
cd C:\Users\user\econ-insta
pip install -r requirements.txt
copy .env.example .env    # 그리고 APP_ID / APP_SECRET / REDIRECT_URI 채우기
```

토큰 발급:

```powershell
python -m econ_insta.ig_auth login
```

출력된 주소를 브라우저에서 열고 승인하면 리디렉션 URI로 돌아온다.
**주소창 내용을 통째로 복사해서 붙여넣으면 된다** (페이지가 404여도 정상).

내부적으로는 `code`(1시간) → 단기 토큰(1시간) → **장기 토큰(60일)** 으로 교환해 `tokens.json`에 저장한다.

> Instagram은 `code` 끝에 `#_`를 붙여서 돌려준다. 이걸 그대로 쓰면 교환이 실패하는데,
> `extract_code()`가 자동으로 제거한다.

확인 / 갱신:

```powershell
python -m econ_insta.ig_auth status
python -m econ_insta.ig_auth refresh   # 60일마다. 발급 후 24시간 지나야 가능
```

---

## 발행

```python
from econ_insta.ig_client import InstagramClient

client = InstagramClient()
result = client.publish_images(
    image_urls=[
        "https://raw.githubusercontent.com/USER/REPO/main/out/2026-07-10/1.jpg",
        "https://raw.githubusercontent.com/USER/REPO/main/out/2026-07-10/2.jpg",
    ],
    caption="7월 10일 경제 브리핑\n\n#경제뉴스 #주식",
    alt_texts=["표지", "코스피 지표"],
)
print(result.permalink)
```

이미지가 1장이면 단일 게시물, 2장 이상이면 자동으로 캐러셀이 된다.

### 제약

| 항목 | 값 |
|---|---|
| 이미지 포맷 | JPEG만 |
| 캐러셀 | 2~10장 |
| 캡션 | 2,200자, 해시태그 30개 |
| 발행 한도 | 24시간 롤링 100건 (캐러셀은 1건) |
| 컨테이너 수명 | 생성 후 24시간 |

캡션·캐러셀 장수는 API를 호출하기 전에 `validate_caption()` 등이 먼저 거른다.

---

## 테스트

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests -v
```

HTTP 계층을 가짜 세션으로 바꿔 발행 흐름 전체(자식 컨테이너 → 폴링 → 캐러셀 → publish)를 구동한다.
네트워크와 토큰 없이 돈다.

---

## 저작권 주의

뉴스 기사 본문을 카드에 그대로 옮기면 저작권 침해가 된다.
**사실관계만 추출해 자체 문장으로 재작성하고 출처 매체명을 표기**하는 구조로 갈 것.
