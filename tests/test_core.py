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
from src.report.report_view import shares as share_count  # noqa: E402
from src.analysis import peer  # noqa: E402
from src.analysis.verify import verify as verify_report  # noqa: E402
from src.analysis.money import money as money_of  # noqa: E402
from src.analysis.money import price as price_of  # noqa: E402
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


class TestKrwFormat:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (1_502_493_600_000_000, "1,502조 4,936억원"),
            (503_900_000_000, "5,039억원"),
            (9_900_000_000, "99억원"),
            # 딱 떨어지는 조 단위는 '10조 0억원'이 아니라 '10조원'으로
            (10_000_000_000_000, "10조원"),
            (1_000_000_000_000, "1조원"),
        ],
    )
    def test_조억_구분(self, value, expected):
        assert money_of(value) == expected

    def test_결측은_안내문(self):
        assert money_of(None) == "데이터 없음"
        assert money_of(float("nan")) == "데이터 없음"


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

        # 예전 형식(날짜: 정수)도 그대로 읽을 수 있어야 한다
        limiter.USAGE_PATH.write_text(
            json.dumps({limiter._today(): 7}), encoding="utf-8"
        )
        for _ in range(30):
            limiter.record(session=False)

        stored = json.loads(limiter.USAGE_PATH.read_text(encoding="utf-8"))
        assert stored[limiter._today()][limiter.TOTAL] == 37
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


class TestCurrencyMoney:
    """시장이 섞이면 단위 오류가 가장 위험하다. 달러를 원으로 적으면 안 된다."""

    @pytest.mark.parametrize(
        "value,currency,expected",
        [
            (333_605_938_000_000, "KRW", "333조 6,059억원"),
            (215_938_000_000, "USD", "2,159억달러"),
            (5_505_645_000_000, "USD", "5조 5,056억달러"),
            (95_000_000_000, "JPY", "950억엔"),
        ],
    )
    def test_통화별_표기(self, value, currency, expected):
        assert money_of(value, currency) == expected

    def test_원화_주가는_소수점을_쓰지_않는다(self):
        assert price_of(255500, "KRW") == "255,500원"

    def test_달러_주가는_센트까지_남긴다(self):
        # 228.45를 228로 적으면 정보가 사라진다
        assert price_of(228.45, "USD") == "228.45달러"

    def test_모르는_통화도_깨지지_않는다(self):
        assert money_of(1_000_000_000, "XYZ").endswith("XYZ")


class TestMarketAwarePrompt:
    @pytest.fixture
    def us_row(self):
        return pd.Series(
            {
                "종목코드": "NVDA",
                "종목명": "엔비디아",
                "영문명": "NVIDIA Corporation",
                "시장구분": "나스닥",
                "국가": "미국주식",
                "통화": "USD",
                "업종_소분류": "반도체",
                "업종_대분류": "반도체",
                "현재가": 228.45,
                "시가총액": 5.505645e12,
                "매출액": 215938e6,
                "매출액_전기": 130497e6,
                "매출액_전전기": 60922e6,
                "영업이익": 134887e6,
                "당기순이익": 120067e6,
                "PER": 43.05,
                "ROA": 75.42,
                "영업이익률": 62.47,
                "기준연도": 2026,
            }
        )

    def test_해외_금액은_달러로_적힌다(self, us_row):
        prompt = build_prompt(us_row, "펀더멘탈", "압축형")
        assert "2,159억달러" in prompt
        assert "2,159억원" not in prompt

    def test_통화를_명시한다(self, us_row):
        assert "원화가 아니다" in build_prompt(us_row, "펀더멘탈", "압축형")

    def test_없는_계정은_줄을_넣지_않는다(self, us_row):
        # '자본총계: 데이터 없음'을 늘어놓으면 모델이 빈칸을 근거처럼 다룬다.
        # 제약 안내문에는 그 이름이 나와도 되므로 데이터 구간만 본다.
        data = build_prompt(us_row, "펀더멘탈", "압축형").split("[분석 관점")[0]
        assert "데이터 없음" not in data
        assert "- 자본총계" not in data
        assert "- 부채비율" not in data

    def test_해외에는_공시블록을_넣지_않는다(self, us_row):
        assert "[최근 공시]" not in build_prompt(us_row, "펀더멘탈", "압축형")

    def test_시장_제약을_알려준다(self, us_row):
        prompt = build_prompt(us_row, "펀더멘탈", "압축형")
        assert "부채비율과 ROE는 알 수 없다" in prompt

    def test_국내는_제약문구가_붙지_않는다(self):
        row = pd.Series(
            {
                "종목코드": "005930",
                "종목명": "삼성전자",
                "시장구분": "KOSPI",
                "국가": "국내주식",
                "통화": "KRW",
                "현재가": 255500.0,
                "시가총액": 1.5e15,
                "매출액": 3.3e14,
                "부채비율": 29.94,
                "기준연도": 2025,
            }
        )
        assert "이 시장의 데이터 제약" not in build_prompt(row, "펀더멘탈", "압축형")


class TestPeerMarketScope:
    @pytest.fixture
    def mixed(self):
        rows = []
        for i in range(6):
            rows.append(
                {
                    "종목코드": f"K{i}",
                    "국가": "국내주식",
                    "업종_소분류": "반도체",
                    "시가총액": 100 - i,
                    "영업이익률": 5.0 + i,
                }
            )
        for i in range(6):
            rows.append(
                {
                    "종목코드": f"U{i}",
                    "국가": "미국주식",
                    "업종_소분류": "반도체",
                    "시가총액": 900 - i,
                    "영업이익률": 40.0 + i,
                }
            )
        return pd.DataFrame(rows)

    def test_같은_나라끼리만_비교한다(self, mixed):
        """국내 반도체를 미국 반도체와 섞으면 중앙값이 뜻을 잃는다."""
        korean = mixed[mixed["종목코드"] == "K0"].iloc[0]
        stats = peer.sector_stats(mixed, "반도체", korean)
        assert stats["종목수"] == 6
        assert stats["지표"]["영업이익률"]["중앙값"] == 7.5

    def test_시총순위도_같은_나라_안에서(self, mixed):
        korean = mixed[mixed["종목코드"] == "K0"].iloc[0]
        assert peer.cap_rank(peer.same_market(mixed, korean), "반도체", "K0") == (1, 6)


class TestLengthLimit:
    """상세형은 출력이 길어 1건 5.03원. 전체 상한과 별개로 따로 조인다."""

    @pytest.fixture
    def limiter(self, tmp_path, monkeypatch):
        import importlib

        from src.analysis import usage_limit as module

        importlib.reload(module)
        monkeypatch.setattr(module, "USAGE_PATH", tmp_path / "usage.json")
        return module

    def test_상세형_상한에_걸린다(self, limiter):
        cap = limiter.LENGTH_LIMITS["상세형"]
        for _ in range(cap):
            limiter.check("상세형", session=False)
            limiter.record("상세형", session=False)

        with pytest.raises(limiter.DailyLimitReached):
            limiter.check("상세형", session=False)

    def test_상세형이_막혀도_압축형은_열려_있다(self, limiter):
        for _ in range(limiter.LENGTH_LIMITS["상세형"]):
            limiter.record("상세형", session=False)

        limiter.check("압축형", session=False)  # 예외 없이 통과해야 한다
        assert limiter.remaining_today("압축형") > 0
        assert limiter.remaining_today("상세형") == 0

    def test_분량별로_따로_센다(self, limiter):
        limiter.record("압축형", session=False)
        limiter.record("압축형", session=False)
        limiter.record("상세형", session=False)

        assert limiter.used_today() == 3
        assert limiter.used_today("압축형") == 2
        assert limiter.used_today("상세형") == 1

    def test_전체_상한이_먼저_걸리면_분량과_무관하게_막힌다(self, limiter, monkeypatch):
        monkeypatch.setattr(limiter, "used_today", lambda length=None: limiter.DAILY_LIMIT)
        with pytest.raises(limiter.DailyLimitReached):
            limiter.check("압축형", session=False)

    def test_남은_건수는_더_작은_쪽을_따른다(self, limiter):
        for _ in range(8):
            limiter.record("상세형", session=False)
        # 전체는 92건 남았지만 상세형은 2건뿐이다
        assert limiter.remaining_today() == limiter.DAILY_LIMIT - 8
        assert limiter.remaining_today("상세형") == 2


class TestMarketMerge:
    """국내와 해외를 합칠 때 공시 열이 밀려나 국내 공시 필터가 죽은 적이 있다."""

    def test_공시열을_미리_만들지_않는다(self):
        # markets가 '공시성격'을 미리 채우면, 뒤에서 공시 표를 merge할 때
        # 이름이 겹쳐 '공시성격_공시'로 밀려나고 국내 공시가 통째로 사라진다.
        from src.collectors import markets

        universe = markets.load_all()
        if universe.empty:
            pytest.skip("수집된 데이터가 없습니다")
        assert "공시성격" not in universe.columns

    def test_국가별로_쓸_수_있는_것이_다르다(self):
        from src.collectors import markets

        assert "ROE_계산" in markets.available_metrics(markets.KOREA)
        assert "ROE_계산" not in markets.available_metrics("미국주식")

        assert markets.has_disclosure(markets.KOREA)
        assert not markets.has_disclosure("미국주식")

        assert "이슈·트렌드" in markets.available_perspectives(markets.KOREA)
        assert "이슈·트렌드" not in markets.available_perspectives("미국주식")


class TestExchangeRate:
    """엔화 고시는 100엔 기준이다. 1엔당으로 착각하면 일본 종목 시총이 100배가 된다."""

    def test_엔화는_100단위_고시를_풀어준다(self):
        from src.collectors import markets

        assert markets.FX_QUOTE_UNITS["JPY"] == 100
        # 862.25원/100엔 → 8.6225원/엔
        assert abs(862.25 / markets.FX_QUOTE_UNITS["JPY"] - 8.6225) < 1e-6

    def test_달러와_위안은_1단위_고시다(self):
        from src.collectors import markets

        assert markets.FX_QUOTE_UNITS.get("USD", 1) == 1
        assert markets.FX_QUOTE_UNITS.get("CNY", 1) == 1

    def test_원화는_환산하지_않는다(self):
        from src.collectors import markets

        assert markets.fx_rate("KRW") == (1.0, True)

    def test_대체값도_1단위_기준이다(self):
        # 폴백이 100엔 기준이면 환율 조회 실패 시 조용히 100배가 된다
        from src.collectors import markets

        assert 5 < markets.FX_FALLBACK["JPY"] < 15
        assert 100 < markets.FX_FALLBACK["CNY"] < 300


class TestMarketRegistry:
    def test_해외_시장은_같은_지표_구성을_쓴다(self):
        from src.collectors import markets

        for label in markets.COUNTRIES.values():
            assert markets.available_metrics(label) == markets.OVERSEAS_METRICS
            assert "이슈·트렌드" not in markets.available_perspectives(label)
            assert not markets.has_disclosure(label)

    def test_거래소가_국가에_모두_매핑되어_있다(self):
        from src.collectors.overseas_collector import EXCHANGE_LABELS, MARKETS

        for exchanges in MARKETS.values():
            for exchange in exchanges:
                assert exchange in EXCHANGE_LABELS, f"{exchange} 한글 이름이 없다"


class TestShareCount:
    """상장주식수는 수집 시점에 이미 천주 단위다. 표시할 때 또 나누면 1,000배 작아진다."""

    @pytest.mark.parametrize(
        "thousands,expected",
        [
            (5_846_279, "58억 4,627만주"),  # 삼성전자. 5,846천주로 나오던 값
            (728_002, "7억 2,800만주"),
            (1_500, "150만주"),
            (3, "3,000주"),
        ],
    )
    def test_주식수_표기(self, thousands, expected):
        assert share_count(thousands) == expected

    def test_결측(self):
        assert share_count(None) == "—"
        assert share_count(float("nan")) == "—"

    def test_시총과_앞뒤가_맞는다(self):
        # 상장주식수 × 주가 ≈ 시가총액이어야 한다
        thousands, price, cap = 5_846_279, 255_500, 1_493_724_200_000_000
        assert abs(thousands * 1_000 * price - cap) / cap < 0.01


class TestProgressOutput:
    """터미널이 아니면 tqdm이 줄을 쌓는다. CI 로그가 진행률로 덮이면 안 된다."""

    def test_로그모드는_줄단위로_찍는다(self, capsys, monkeypatch):
        from src.collectors import progress

        monkeypatch.setattr(progress, "is_terminal", lambda: False)
        items = list(progress.track(range(10), desc="수집", interval=0))

        assert items == list(range(10))
        out = capsys.readouterr().out
        assert "수집:" in out
        # 되감기 문자가 섞이면 로그가 한 줄로 뭉친다
        assert "\r" not in out
        assert out.endswith("\n")

    def test_진행_건수가_로그에_남는다(self, capsys, monkeypatch):
        from src.collectors import progress

        monkeypatch.setattr(progress, "is_terminal", lambda: False)
        list(progress.track(range(5), desc="수집", interval=999))

        # 간격이 길어도 마지막 완료 줄은 반드시 남아야 한다
        assert "완료 5건" in capsys.readouterr().out

    def test_길이를_모르는_것도_처리한다(self, capsys, monkeypatch):
        from src.collectors import progress

        monkeypatch.setattr(progress, "is_terminal", lambda: False)
        assert list(progress.track(iter(range(3)), desc="스트림", interval=0)) == [0, 1, 2]
        assert "완료 3건" in capsys.readouterr().out

    def test_모든_수집기가_track을_쓴다(self):
        # tqdm을 직접 부르는 곳이 남아 있으면 그 단계만 로그를 덮는다
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        offenders = []
        for path in list((root / "src").rglob("*.py")):
            if path.name == "progress.py":
                continue
            if re.search(r"\btqdm\(", path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        assert not offenders, f"tqdm을 직접 쓰는 파일: {offenders}"


class TestMixedCurrency:
    """한 시장에 통화가 하나라고 가정하면 언젠가 조용히 틀린다."""

    def test_행마다_그_종목의_통화로_환산한다(self, monkeypatch):
        from src.collectors import markets

        rates = {"HKD": 172.0, "CNY": 200.0}
        monkeypatch.setattr(markets, "fx_rate", lambda c, force=False: (rates.get(c, 1.0), True))

        # 홍콩처럼 한 거래소에 HKD와 CNY가 섞인 경우
        frame = pd.DataFrame(
            {"통화": ["HKD", "CNY", "HKD"], "시가총액": [100.0, 100.0, 200.0]}
        )
        converted = frame["시가총액"] * frame["통화"].map(
            {c: markets.fx_rate(c)[0] for c in frame["통화"].unique()}
        )
        assert converted.tolist() == [17_200.0, 20_000.0, 34_400.0]

    def test_통합표는_통화별로_환율이_하나씩만_쓰인다(self):
        from src.collectors import markets

        df = markets.load_all()
        if df.empty:
            pytest.skip("수집된 데이터가 없습니다")

        priced = df[df["시가총액"].notna() & df["시가총액_원화"].notna()]
        for currency, group in priced.groupby("통화"):
            ratios = (group["시가총액_원화"] / group["시가총액"]).round(4)
            assert ratios.nunique() == 1, f"{currency}에 환율이 여러 개 적용됐다"


class TestBatchCoverage:
    """시장 이름을 배치 코드에 박아 두면 새 시장을 추가할 때마다 빠뜨린다."""

    def test_해외_배치가_모든_시장을_돈다(self):
        # 일본·중국을 넣고도 갱신 단계는 미국만 돌던 적이 있다
        import inspect

        import update_all
        from src.collectors.overseas_collector import MARKETS

        for function in (update_all.update_overseas_prices, update_all.update_overseas_full):
            source = inspect.getsource(function)
            assert "MARKETS" in source, f"{function.__name__}이 시장 목록을 참조하지 않는다"
            for country in MARKETS:
                assert f'"{country}"' not in source, (
                    f"{function.__name__}에 '{country}'가 하드코딩돼 있다"
                )

    def test_워크플로가_모든_시장을_워밍한다(self):
        from pathlib import Path

        from src.collectors import markets

        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/daily-update.yml"
        ).read_text(encoding="utf-8")

        for label in [markets.KOREA, *markets.COUNTRIES.values()]:
            assert label in workflow, f"워크플로에 {label} 워밍이 빠졌다"


class TestNumberVerification:
    """실제로 겪은 네 가지 숫자 오류를 검증기가 잡아내는지 확인한다.

    금융 리포트에서 문장이 어색한 건 참을 수 있어도 숫자가 틀리면 못 쓴다.
    넷 다 화면에는 멀쩡해 보였고 원본과 대조해야만 드러났다.
    """

    @pytest.fixture
    def row(self):
        return pd.Series(
            {
                "종목코드": "005930",
                "종목명": "삼성전자",
                "통화": "KRW",
                "시가총액": 1_493_724_200_000_000,
                "매출액": 333_605_938_000_000,
                "매출액_전기": 300_870_903_000_000,
                "매출액_전전기": 258_935_494_000_000,
                "영업이익": 43_601_051_000_000,
                "영업이익_전기": 32_725_961_000_000,
                "당기순이익": 45_206_805_000_000,
                "당기순이익_전기": 34_451_400_000_000,
                "자본총계": 436_320_337_000_000,
                "부채총계": 130_621_773_000_000,
                "부채비율": 29.94,
                "영업이익률": 13.07,
                "ROE_계산": 10.36,
                "PER": 11.53,
            }
        )

    def _report(self, *lines):
        return {"헤드라인": lines[0], "핵심포인트": list(lines[1:]), "섹션": [], "데이터한계": ""}

    def test_금액_10배_오독을_잡는다(self, row):
        # 실제 사고: 333조 6,059억원을 '3,336조원'으로 적었다
        result = verify_report(self._report("삼성전자 실적", "매출액 3,336조원을 기록"), row)
        assert not result["통과"]
        assert any(u["종류"] == "금액" and "3,336조" in u["표기"] for u in result["미확인"])

    def test_올바른_금액은_통과한다(self, row):
        result = verify_report(
            self._report("삼성전자 실적", "매출액 333조 6,059억원, 영업이익 43조 6,011억원"), row
        )
        assert result["통과"], result["미확인"]

    def test_반올림_표기도_통과한다(self, row):
        # '약 333조원'처럼 끊어 쓰는 것은 정당하다
        assert verify_report(self._report("실적", "매출은 약 333조원 수준"), row)["통과"]

    def test_다른_계정의_증감률을_잡는다(self, row):
        # 실제 사고: 영업이익 증감률 자리에 당기순이익 값을 적었다.
        # 영업이익 전년비는 +33.2%인데 엉뚱한 -46.8%를 쓰면 출처를 못 찾는다.
        result = verify_report(self._report("실적", "영업이익이 46.8% 감소"), row)
        assert not result["통과"]
        assert any("46.8" in u["표기"] for u in result["미확인"])

    def test_실제_증감률은_통과한다(self, row):
        # 매출 전년비 +10.9%, 영업이익 전년비 +33.2%는 데이터에서 계산된다
        result = verify_report(
            self._report("실적", "매출 10.9% 증가", "영업이익 33.2% 증가"), row
        )
        assert result["통과"], result["미확인"]

    def test_2년_전_대비도_정당한_인용이다(self, row):
        # 258조 → 333조는 +28.8%. 전년비가 아니어도 데이터에서 나온다
        assert verify_report(self._report("실적", "2년 만에 28.8% 성장"), row)["통과"]

    def test_지어낸_비율을_잡는다(self, row):
        result = verify_report(self._report("실적", "영업이익률이 55.5%에 달한다"), row)
        assert not result["통과"]

    def test_업종_중앙값도_출처로_인정한다(self, row):
        peers = {"지표": {"영업이익률": {"중앙값": 4.75, "백분위": 74}}}
        result = verify_report(
            self._report("비교", "업종 중앙값 4.75% 대비 높다", "업종 내 상위 26%"),
            row,
            peers=peers,
        )
        assert result["통과"], result["미확인"]

    def test_대조율을_계산한다(self, row):
        result = verify_report(
            self._report("실적", "매출 333조 6,059억원", "영업이익률 99.9%"), row
        )
        assert result["전체"] == 2
        assert result["확인"] == 1
        assert result["대조율"] == 50.0


class TestCacheKeyCollision:
    """한국과 중국(심천)이 6자리 종목코드를 공유한다. 실제로 54개가 겹친다."""

    def test_시장이_다르면_캐시_파일도_다르다(self):
        from src.analysis.gemini_analyzer import _cache_path

        korean = _cache_path("000810", "펀더멘탈", "압축형", "국내주식")
        chinese = _cache_path("000810", "펀더멘탈", "압축형", "중국주식")

        # 같은 파일을 쓰면 삼성화재를 열었는데 창유디지털 리포트가 나온다
        assert korean != chinese
        assert korean.name.startswith("KR_")
        assert chinese.name.startswith("CN_")

    def test_국가를_안_주면_국내로_본다(self):
        from src.analysis.gemini_analyzer import _cache_path

        assert _cache_path("005930", "펀더멘탈", "압축형").name.startswith("KR_")

    def test_모든_시장에_코드가_있다(self):
        from src.analysis.gemini_analyzer import MARKET_CODES
        from src.collectors import markets

        for label in [markets.KOREA, *markets.COUNTRIES.values()]:
            assert label in MARKET_CODES, f"{label}의 시장 코드가 없다"
        assert len(set(MARKET_CODES.values())) == len(MARKET_CODES), "시장 코드가 겹친다"

    def test_실제로_코드가_겹친다(self):
        # 이 전제가 깨지면(예: 중국을 뺀다면) 접두어가 필요 없어진다
        from src.collectors import markets

        df = markets.load_all()
        if df.empty:
            pytest.skip("수집된 데이터가 없습니다")

        codes = df["종목코드"].astype(str)
        overlapping = codes[codes.duplicated()].nunique()
        assert overlapping > 0, "코드 충돌이 사라졌다면 접두어 규칙을 다시 검토할 것"


class TestVerifierSigns:
    """한국어 리포트는 '21.5% 감소'처럼 방향을 말로 쓰고 숫자에 부호를 안 붙인다."""

    @pytest.fixture
    def row(self):
        return pd.Series(
            {
                "종목코드": "7203",
                "종목명": "토요타자동차",
                "통화": "JPY",
                "영업이익": 3_766_200_000_000,
                "영업이익_전기": 4_795_600_000_000,
                "당기순이익": 3_848_100_000_000,
                "당기순이익_전기": 4_765_100_000_000,
            }
        )

    def test_감소를_양수로_써도_통과한다(self, row):
        # 영업이익 -21.5%, 당기순이익 -19.2%를 부호 없이 인용한 경우
        report = {
            "헤드라인": "토요타",
            "핵심포인트": ["영업이익이 21.5%, 당기순이익이 19.2% 줄었다"],
            "섹션": [],
            "데이터한계": "",
        }
        assert verify_report(report, row)["통과"]

    def test_지표의_부호도_양쪽_다_본다(self, row):
        # '60일선_대비: -7.7%'를 본문은 '7.7% 낮은'이라고 쓴다
        tech = {"60일선_대비": "-7.7%", "고가대비": -28.28}
        report = {
            "헤드라인": "주가",
            "핵심포인트": ["60일선 대비 7.7% 낮고 기간 고가 대비 28.28% 하락"],
            "섹션": [],
            "데이터한계": "",
        }
        assert verify_report(report, row, tech=tech)["통과"]

    def test_뉴스에_실린_숫자는_인용으로_본다(self, row):
        news = [{"일자": "2026-08-21", "제목": "자기주식 1.7조원 취득 결정"}]
        report = {
            "헤드라인": "자기주식",
            "핵심포인트": ["1.7조원 규모의 자기주식 취득을 결정했다"],
            "섹션": [],
            "데이터한계": "",
        }
        assert verify_report(report, row, news=news)["통과"]
        # 뉴스를 안 주면 출처를 알 수 없으므로 잡힌다
        assert not verify_report(report, row)["통과"]
