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
