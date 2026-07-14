"""2026-07-14 증시 변동성 마켓 브리핑.

'반등'이 아니라 '변동성'이다. 7/14 코스피는 반등(+0.73%)했지만 코스닥은 사이드카가
걸렸고(-1.92%) 장중 변동폭이 531포인트에 달했다. 급락(7/13)과 반등이 뒤섞인 국면
전체를 '변동성'으로 잡는 것이 사실에 맞다.

수치는 모두 실제 보도(이투데이·비즈니스코리아·파이낸셜뉴스 등)에서 확인한 값이다.
지수 종가는 yfinance(7/13까지) + 뉴스 확인값(7/14)으로 구성한다 — yfinance가 장 마감
직후 지수를 아직 안 주기 때문이다.
"""

from __future__ import annotations

from datetime import datetime

import yfinance as yf

from econ_insta.config import PROJECT_ROOT
from econ_insta.renderer import (
    PAPER,
    JPEG_QUALITY,
    FontSet,
    render_card,
    render_cover,
)
from econ_insta.stock_brief import Series, render_chart
from econ_insta.summarizer import Card

WHEN = datetime(2026, 7, 14)
OUT = PROJECT_ROOT / "out" / "2026-07-14-market"
THEME = PAPER

# 뉴스에서 확인한 7/14 코스피 종가. yfinance가 아직 안 주는 마지막 한 점.
KOSPI_0714 = 6856.83

HEADLINE = "요동친 증시, 롤러코스터 하루"

CARDS = [
    Card(
        title="하루에 531포인트를 오갔다",
        body=(
            "코스피는 장중 6,448까지 밀렸다가 6,979까지 되올랐다. 위아래 폭이 531포인트에 "
            "달한 극심한 변동성 끝에, 지수는 전날보다 0.73% 오른 6,856에 마감했다."
        ),
        source="이투데이",
    ),
    Card(
        title="코스피는 웃고, 코스닥은 울었다",
        body=(
            "같은 날 코스닥은 1.92% 내리며 매도 사이드카가 걸렸다. 대형 반도체주가 지수를 "
            "떠받친 코스피와 달리, 중소형주 중심의 코스닥은 반등에 올라타지 못했다."
        ),
        source="뉴스토마토",
    ),
    Card(
        title="개인이 던진 물량을 기관·외국인이 받았다",
        body=(
            "전날 급락장에서 개인은 대규모 매도에 나섰지만, 기관과 외국인이 순매수로 방향을 "
            "틀며 지수를 끌어올렸다. 하루 만에 수급의 주체가 뒤바뀐 셈이다."
        ),
        source="파이낸셜투데이",
    ),
    Card(
        title="무엇이 시장을 흔들었나",
        body=(
            "반도체 업황이 정점을 지난 것 아니냐는 의구심이 바탕에 깔린 가운데, 급등장에서 "
            "쌓인 레버리지의 후폭풍과 중동 지정학 리스크가 겹치며 변동성을 키웠다."
        ),
        source="디지털데일리",
    ),
    Card(
        title="올해가 유독 심하다",
        body=(
            "코스닥 사이드카는 올해 스무 번째로, 2008년 금융위기 당시 기록을 이미 넘어섰다. "
            "코스피 서킷브레이커도 제도 도입 이후 절반이 올해에 몰렸다."
        ),
        source="파이낸셜뉴스",
    ),
]


def build_series() -> Series:
    history = yf.Ticker("^KS11").history(period="3mo", auto_adjust=False)
    closes = [float(v) for v in history["Close"]]
    dates = [d.to_pydatetime() for d in history.index]
    # yfinance가 아직 안 준 7/14 종가를 뉴스 확인값으로 덧붙인다.
    closes.append(KOSPI_0714)
    dates.append(WHEN)
    return Series(name="코스피", ticker="KOSPI", closes=closes, dates=dates, currency="")


def main() -> None:
    fonts = FontSet.discover()
    OUT.mkdir(parents=True, exist_ok=True)
    series = build_series()

    images = [render_cover(HEADLINE, WHEN, fonts, kicker="마켓 브리핑", theme=THEME)]
    images += [render_card(c, i, len(CARDS), fonts, theme=THEME) for i, c in enumerate(CARDS, 1)]
    images.append(render_chart(series, fonts, WHEN, label="지수 추이", theme=THEME))

    paths = []
    for index, image in enumerate(images):
        path = OUT / f"{index:02d}.jpg"
        image.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        paths.append(path)

    (OUT / "caption.txt").write_text(CAPTION, encoding="utf-8")
    print(f"코스피 3개월 최고 {max(series.closes):,.0f} / 7-13 저점 {min(series.closes[-10:]):,.0f} "
          f"/ 7-14 {series.last:,.0f}")
    print(f"카드 {len(paths)}장 → {OUT}")


CAPTION = """어제 코스피는 하루에만 531포인트를 오간 끝에 반등에 성공했습니다. 하지만 코스닥은 사이드카가 걸리며 엇갈렸습니다. 요동친 하루를 정리했습니다.

2026년 07월 14일 마켓 브리핑

· 코스피, 장중 531포인트 오간 끝에 +0.73% 반등
· 코스닥은 -1.92%, 매도 사이드카 발동
· 개인 매도를 기관·외국인이 받아 반등
· 반도체 의구심·레버리지 후폭풍·중동 리스크가 변동성 키워
· 코스닥 사이드카 올해 20번째, 2008년 기록 넘어서

출처 · 이투데이 · 뉴스토마토 · 파이낸셜투데이 · 디지털데일리 · 파이낸셜뉴스

※ 투자 판단의 근거로 삼지 마십시오. 투자 책임은 본인에게 있습니다.

#코스피 #코스닥 #증시 #변동성 #반도체 #경제뉴스 #주식 #카드뉴스"""


if __name__ == "__main__":
    main()
