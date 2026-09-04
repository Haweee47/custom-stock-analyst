"""핵심 판정 로직 테스트.

지금까지 나온 버그는 대부분 '분류가 조용히 틀리는' 종류였다.
공시를 안 가져오거나, 계정명이 안 맞거나, 액면병합을 상장폐지로 보거나.
이런 것들은 화면에 에러가 안 나므로 테스트로 막는다.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.disclosure import _score  # noqa: E402
from src.analysis.screens import SCREENS, apply_screens  # noqa: E402
from src.collectors.indicators import bollinger, ichimoku, rsi  # noqa: E402
from src.report.report_view import won  # noqa: E402
from src.analysis import peer  # noqa: E402
from src.analysis.gemini_analyzer import (  # noqa: E402
    _growth,
    _money,
    build_prompt,
)


class TestDisclosureScore:
    @pytest.mark.parametrize(
        "title",
        [
            "주권매매거래정지해제              (상장폐지에 따른 정리매매 개시)",
            "기타시장안내(관리종목지정우려종목)              (시가총액 200억원 미달)",
            "반기검토(감사)의견부적정등사실확인(자본잠식률100분의50이상)",
            "횡령ㆍ배임혐의발생",
        ],
    )
    def test_중대사안은_최고등급(self, title):
        assert _score(title) == 7

    @pytest.mark.parametrize(
        "title",
        [
            "주권매매거래정지해제              (액면병합 주권 변경상장)",
            "주권매매거래정지              (주식의 병합, 분할 등 전자등록 변경, 말소)",
            "불성실공시법인미지정              (지정유예)",
        ],
    )
    def test_기술적_정지는_중대사안이_아니다(self, title):
        assert _score(title) < 6

    def test_불성실공시는_존속위험과_분리(self):
        assert _score("불성실공시법인지정") == 6

    @pytest.mark.parametrize(
        "title",
        ["임원ㆍ주요주주특정증권등소유상황보고서", "일괄신고추가서류", "투자설명서"],
    )
    def test_정기_잡음은_제외(self, title):
        assert _score(title) == 0

    def test_실적공시는_5등급(self):
        assert _score("연결재무제표기준영업(잠정)실적(공정공시)") == 5


class TestWonFormat:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (1_502_493_600_000_000, "1,502조 4,936억원"),
            (503_900_000_000, "5,039억원"),
            (9_900_000_000, "99억원"),
            (10_000_000_000_000, "10조원"),
            (1_000_000_000_000, "1조원"),
        ],
    )
    def test_조억_구분(self, value, expected):
        assert won(value) == expected

    def test_결측은_대시(self):
        assert won(None) == "—"
        assert won(float("nan")) == "—"


class TestScreens:
    @pytest.fixture
    def sample(self):
        return pd.DataFrame(
            {
                "종목코드": ["A", "B", "C"],
                "영업이익": [100, -50, 200],
                "영업이익_전기": [-30, 10, 150],
                "매출액": [1000, 500, 2000],
                "매출액_전기": [800, 400, 1000],
                "PER": [8.0, -3.0, 25.0],
                "ROE_계산": [20.0, 5.0, 18.0],
                "부채비율": [50.0, 300.0, 80.0],
            }
        )

    def test_흑자_필터(self, sample):
        assert set(apply_screens(sample, ["흑자 기업"])["종목코드"]) == {"A", "C"}

    def test_저PER은_적자를_제외(self, sample):
        # PER이 음수인 적자 기업이 '저PER'로 잡히면 안 된다
        assert set(apply_screens(sample, ["저PER (10배 미만)"])["종목코드"]) == {"A"}

    def test_턴어라운드(self, sample):
        assert set(apply_screens(sample, ["턴어라운드"])["종목코드"]) == {"A"}

    def test_조건_조합은_교집합(self, sample):
        result = apply_screens(sample, ["흑자 기업", "고ROE (15% 이상)", "저부채 (100% 미만)"])
        assert set(result["종목코드"]) == {"A", "C"}

    def test_모든_조건이_동작한다(self, sample):
        for name in SCREENS:
            apply_screens(sample, [name])  # 예외 없이 실행되면 통과


class TestIndicators:
    @pytest.fixture
    def prices(self):
        import numpy as np

        n = 200
        base = pd.Series(np.linspace(1000, 2000, n))
        return pd.DataFrame(
            {
                "일자": pd.date_range("2026-01-01", periods=n, freq="D"),
                "종가": base,
                "고가": base * 1.02,
                "저가": base * 0.98,
                "거래량": pd.Series([10000] * n),
            }
        )

    def test_상승_추세면_RSI가_높다(self, prices):
        assert rsi(prices["종가"])["RSI(14)"] > 70

    def test_볼린저_밴드_순서(self, prices):
        band = bollinger(prices["종가"], float(prices["종가"].iloc[-1]))
        assert band["볼린저_하단"] < band["볼린저_중심"] < band["볼린저_상단"]

    def test_상승장에서_주가는_구름대_위(self, prices):
        cloud = ichimoku(prices, float(prices["종가"].iloc[-1]))
        assert "구름대 위" in cloud["일목_위치"]

    def test_데이터가_부족하면_빈값(self):
        short = pd.DataFrame({"종가": [1, 2, 3], "고가": [1, 2, 3], "저가": [1, 2, 3]})
        assert ichimoku(short, 3.0) == {}


class TestPromptMoney:
    """리포트가 '333조'를 '3,336조'로 쓴 사고가 있었다.

    억원 고정 표기(3,336,059.38억원)를 모델이 잘못 읽은 것이 원인이라, 사람이 읽는
    방식대로 조·억을 끊어 주도록 바꿨다. 이 표기가 다시 틀어지면 안 된다.
    """

    @pytest.mark.parametrize(
        "value,expected",
        [
            (333_605_938_000_000, "333조 6,059억원"),
            (43_601_051_000_000, "43조 6,011억원"),
            (95_000_000_000, "950억원"),
            (-12_300_000_000, "-123억원"),
            (5_000_000, "5,000,000원"),
        ],
    )
    def test_조억_표기(self, value, expected):
        assert _money(value) == expected

    def test_결측(self):
        assert _money(None) == "데이터 없음"
        assert _money(float("nan")) == "데이터 없음"

    @pytest.mark.parametrize(
        "current,previous,expected",
        [
            (110, 100, " (+10.0%)"),
            (90, 100, " (-10.0%)"),
            (50, -10, " (흑자 전환)"),
            (-50, 10, " (적자 전환)"),
            (100, 0, ""),
            (100, None, ""),
        ],
    )
    def test_증감률(self, current, previous, expected):
        assert _growth(current, previous) == expected


class TestPeerComparison:
    @pytest.fixture
    def universe(self):
        return pd.DataFrame(
            {
                "종목코드": [f"{i:06d}" for i in range(8)],
                "종목명": list("ABCDEFGH"),
                "업종_소분류": ["반도체"] * 7 + ["의약품"],
                "시가총액": [700, 600, 500, 400, 300, 200, 100, 999],
                "영업이익률": [20.0, 12.0, 10.0, 5.0, 4.0, 2.0, 1.0, 50.0],
                "ROE_계산": [15.0, 12.0, 10.0, 5.0, 4.0, 3.0, 1.0, 40.0],
                "부채비율": [30.0, 40.0, 50.0, 70.0, 80.0, 90.0, 110.0, 10.0],
                "PER": [10.0, 12.0, 15.0, 18.0, 20.0, -5.0, 500.0, 8.0],
            }
        )

    def test_중앙값과_백분위(self, universe):
        stats = peer.sector_stats(universe, "반도체", universe.iloc[0])
        assert stats["종목수"] == 7
        assert stats["지표"]["영업이익률"]["중앙값"] == 5.0
        # 7개 중 최상위 → 자기보다 낮은 6개 = 86백분위 = 상위 14%
        assert stats["지표"]["영업이익률"]["백분위"] == 86

    def test_부채비율은_낮을수록_우수(self, universe):
        best = peer.sector_stats(universe, "반도체", universe.iloc[0])
        worst = peer.sector_stats(universe, "반도체", universe.iloc[6])
        assert best["지표"]["부채비율"]["백분위"] > worst["지표"]["부채비율"]["백분위"]

    def test_PER은_순위를_매기지_않는다(self, universe):
        stats = peer.sector_stats(universe, "반도체", universe.iloc[0])
        assert stats["지표"]["PER"]["백분위"] is None

    def test_적자PER과_극단값은_중앙값에서_제외(self, universe):
        # -5배와 500배가 그대로 들어가면 중앙값이 왜곡된다
        stats = peer.sector_stats(universe, "반도체", universe.iloc[0])
        assert stats["지표"]["PER"]["중앙값"] == 15.0
        assert stats["지표"]["PER"]["표본"] == 5

    def test_표본이_적으면_비교하지_않는다(self, universe):
        assert peer.sector_stats(universe, "의약품", universe.iloc[7]) is None

    def test_미분류는_비교하지_않는다(self, universe):
        assert peer.sector_stats(universe, "미분류", universe.iloc[0]) is None

    def test_시총순위(self, universe):
        assert peer.cap_rank(universe, "반도체", "000000") == (1, 7)
        assert peer.cap_rank(universe, "반도체", "000006") == (7, 7)


class TestPromptContents:
    """프롬프트에 빠진 데이터가 있으면 AI가 독자보다 적게 보게 된다."""

    @pytest.fixture
    def row(self):
        return pd.Series(
            {
                "종목코드": "000000",
                "종목명": "테스트",
                "시장구분": "KOSPI",
                "업종_대분류": "IT·반도체",
                "업종_소분류": "반도체",
                "현재가": 50000.0,
                "등락률": 1.5,
                "시가총액": 1_000_000_000_000,
                "외국인비율": 30.0,
                "기준연도": 2025,
                "보고서": "사업보고서",
                "매출액": 300_000_000_000,
                "매출액_전기": 250_000_000_000,
                "매출액_전전기": 200_000_000_000,
                "영업이익": 30_000_000_000,
                "영업이익_전기": 20_000_000_000,
                "영업이익_전전기": 10_000_000_000,
                "당기순이익": 20_000_000_000,
                "당기순이익_전기": 15_000_000_000,
                "당기순이익_전전기": 10_000_000_000,
                "자산총계": 500_000_000_000,
                "부채총계": 200_000_000_000,
                "자본총계": 300_000_000_000,
                "부채비율": 66.7,
                "영업이익률": 10.0,
                "ROE_계산": 6.7,
                "PER": 50.0,
            }
        )

    def test_3개년_추이가_들어간다(self, row):
        prompt = build_prompt(row, "펀더멘탈", "압축형")
        assert "3개년 추이" in prompt
        assert "2023년 2,000억원" in prompt
        assert "2025년 3,000억원" in prompt

    def test_전년비_증감률이_들어간다(self, row):
        assert "(+20.0%)" in build_prompt(row, "펀더멘탈", "압축형")

    def test_업종과_수급이_들어간다(self, row):
        prompt = build_prompt(row, "펀더멘탈", "압축형")
        assert "IT·반도체 > 반도체" in prompt
        assert "외국인 지분율: 30.00%" in prompt

    def test_PBR을_계산해_넣는다(self, row):
        # 시총 1조 / 자본총계 3,000억 = 3.33배
        assert "PBR: 3.33배" in build_prompt(row, "펀더멘탈", "압축형")

    def test_현재가에_소수점이_붙지_않는다(self, row):
        assert "현재가: 50,000원" in build_prompt(row, "펀더멘탈", "압축형")

    def test_기술적_관점은_재무추이를_넣지_않는다(self, row):
        # 관점별로 필요한 블록만 넣어야 토큰과 비용이 늘지 않는다
        prompt = build_prompt(row, "기술적", "압축형", tech={"배열": "정배열"})
        assert "동종업계 비교" not in prompt
        assert "배열: 정배열" in prompt

    def test_자기점검_지시가_붙는다(self, row):
        assert "조와 억을 바꿔 쓰지" in build_prompt(row, "펀더멘탈", "압축형")


class TestUsageLimit:
    """일일 상한은 비용의 상한선이므로 조용히 새면 안 된다."""

    @pytest.fixture
    def limiter(self, tmp_path, monkeypatch):
        import importlib

        from src.analysis import usage_limit as module

        importlib.reload(module)
        monkeypatch.setattr(module, "USAGE_PATH", tmp_path / "usage.json")
        return module

    def test_파일_카운터는_프로세스를_넘어_누적된다(self, limiter):
        # 방문자가 만든 7건이 파일에 있는 상태에서 배치가 새 프로세스로 30건을 만들면
        # 37건이 되어야 한다. 예전에는 max()를 쓰는 바람에 30건으로 덮여 7건이 사라졌다.
        import json

        limiter.USAGE_PATH.write_text(
            json.dumps({limiter._today(): 7}), encoding="utf-8"
        )
        for _ in range(30):
            limiter.record(session=False)

        stored = json.loads(limiter.USAGE_PATH.read_text(encoding="utf-8"))
        assert stored[limiter._today()] == 37
        assert limiter.used_today() == 37
        assert limiter.remaining_today() == limiter.DAILY_LIMIT - 37

    def test_배치는_세션_상한에_걸리지_않는다(self, limiter, monkeypatch):
        # 세션 카운터가 이미 상한을 넘겨도 배치는 통과해야 한다
        monkeypatch.setattr(limiter, "session_used", lambda: limiter.SESSION_LIMIT + 5)
        limiter.check(session=False)  # 예외가 나지 않으면 통과
        with pytest.raises(limiter.SessionLimitReached):
            limiter.check(session=True)

    def test_일일_상한은_배치에도_걸린다(self, limiter, monkeypatch):
        monkeypatch.setattr(limiter, "used_today", lambda: limiter.DAILY_LIMIT)
        with pytest.raises(limiter.DailyLimitReached):
            limiter.check(session=False)

    def test_배치는_세션_카운터를_건드리지_않는다(self, limiter):
        limiter.record(session=False)
        assert limiter.session_used() == 0


class TestPriceRefresh:
    """시세는 매일, 재무는 분기마다 바뀐다. 매일 갱신이 재무를 건드리면 안 된다."""

    @pytest.fixture
    def collector(self, tmp_path, monkeypatch):
        from src.collectors import financial_collector as module

        raw, processed = tmp_path / "raw", tmp_path / "processed"
        raw.mkdir()
        processed.mkdir()
        monkeypatch.setattr(module, "RAW_DIR", raw)
        monkeypatch.setattr(module, "PROCESSED_DIR", processed)

        pd.DataFrame(
            {
                "종목코드": ["005930", "000660"],
                "종목명": ["삼성전자", "SK하이닉스"],
                "시장구분": ["KOSPI"] * 2,
                "종목구분": ["보통주"] * 2,
                "현재가": [50000, 100000],
                "시가총액": [1e14, 5e13],
                "PER": [10.0, 8.0],
                "매출액": [3e14, 5e13],
                "부채비율": [30.0, 40.0],
                "기준연도": [2025, 2025],
            }
        ).to_csv(processed / "financials_2025.csv", index=False, encoding="utf-8-sig")

        # 다음 날 스냅샷: 주가가 올랐고 시총·PER도 따라 움직였다
        pd.DataFrame(
            {
                "종목코드": ["005930", "000660"],
                "종목명": ["삼성전자", "SK하이닉스"],
                "시장구분": ["KOSPI"] * 2,
                "종목구분": ["보통주"] * 2,
                "현재가": [55000, 110000],
                "시가총액": [1.1e14, 5.5e13],
                "PER": [11.0, 8.8],
            }
        ).to_csv(raw / "stock_snapshot_20260901.csv", index=False, encoding="utf-8-sig")
        return module, processed / "financials_2025.csv"

    def test_시세는_갱신된다(self, collector):
        module, path = collector
        assert module.refresh_prices(2025) == 2

        after = pd.read_csv(path, dtype={"종목코드": str})
        samsung = after[after["종목코드"] == "005930"].iloc[0]
        assert samsung["현재가"] == 55000
        assert samsung["PER"] == 11.0

    def test_재무는_건드리지_않는다(self, collector):
        module, path = collector
        module.refresh_prices(2025)

        after = pd.read_csv(path, dtype={"종목코드": str})
        samsung = after[after["종목코드"] == "005930"].iloc[0]
        assert samsung["매출액"] == 3e14
        assert samsung["부채비율"] == 30.0
        assert samsung["기준연도"] == 2025

    def test_열_순서와_종목코드가_보존된다(self, collector):
        module, path = collector
        before = pd.read_csv(path, dtype={"종목코드": str})
        module.refresh_prices(2025)
        after = pd.read_csv(path, dtype={"종목코드": str})

        assert list(before.columns) == list(after.columns)
        # 앞자리 0이 잘리면 종목 매칭이 통째로 깨진다
        assert (after["종목코드"].str.len() == 6).all()

    def test_재무표가_없으면_조용히_넘어간다(self, collector):
        module, path = collector
        path.unlink()
        assert module.refresh_prices(2025) == 0
