"""국내와 해외 종목을 한 표로 합친다.

앱은 지금까지 국내 종목만 다뤘기 때문에 '시가총액'이 곧 원화였다. 해외가 들어오면
같은 열에 달러가 섞이므로, 정렬·필터·업종 비교에 쓸 원화 환산 열을 따로 둔다.
표시는 현지 통화로 하고, 비교는 원화로 한다.

국가마다 갖고 있는 항목이 다르다는 점이 이 모듈의 핵심이다.
  국내: 자산·부채·자본총계가 있어 부채비율과 ROE를 구할 수 있고, DART 공시가 붙는다.
  해외: 그 세 계정이 없다. 대신 EBITDA·ROA·PBR·배당수익률이 온다. 공시는 없다.
없는 값을 있는 척하지 않도록, 어떤 지표를 쓸 수 있는지 국가별로 선언해 둔다.
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PROCESSED_DIR = ROOT / "data" / "processed"
FX_PATH = PROCESSED_DIR / "fx_rates.json"
FX_URL = "https://api.stock.naver.com/marketindex/exchange/FX_{code}KRW"
FX_TTL_HOURS = 12

# 환율을 못 받았을 때 쓰는 값(1단위당 원). 정렬 기준이 통째로 무너지는 것보다는
# 낫지만, 화면에는 '환율 갱신 실패'를 알려야 한다.
FX_FALLBACK = {"USD": 1350.0, "JPY": 8.6, "CNY": 200.0, "HKD": 172.0}

# 고시 단위. 원화 고시는 관행상 엔화만 100단위로 적는다(862.25원 = 100엔).
# 이걸 1엔당으로 착각하면 일본 종목 시가총액이 100배가 되어 전부 최상위로 올라간다.
FX_QUOTE_UNITS = {"JPY": 100}

KOREA = "국내주식"
COUNTRIES = {
    "미국": "미국주식",
    "일본": "일본주식",
    "중국": "중국주식",
}

# 국가별로 쓸 수 있는 재무 지표. 화면과 프롬프트가 이걸 보고 항목을 정한다.
# 해외는 어느 시장이든 자산·부채·자본총계가 없어 지표 구성이 같다
OVERSEAS_METRICS = ["PER", "PBR", "영업이익률", "ROA"]
METRICS = {
    KOREA: ["PER", "부채비율", "영업이익률", "ROE_계산"],
    **{label: OVERSEAS_METRICS for label in COUNTRIES.values()},
}

# 공시는 DART 기반, 뉴스는 네이버 국내 금융 기사라 둘 다 국내에만 붙는다
HAS_DISCLOSURE = {KOREA}
HAS_NEWS = {KOREA}

# 국가별로 고를 수 있는 분석 관점.
# '이슈·트렌드'는 뉴스와 공시가 재료인데 해외는 둘 다 없다. 재료 없이 관점만
# 열어 두면 재무 얘기만 하는 엉뚱한 리포트가 나오므로 아예 빼는 편이 정직하다.
OVERSEAS_PERSPECTIVES = ["펀더멘탈", "기술적", "종합"]
PERSPECTIVES = {
    KOREA: ["펀더멘탈", "기술적", "이슈·트렌드", "종합"],
    **{label: OVERSEAS_PERSPECTIVES for label in COUNTRIES.values()},
}


def _read_cache() -> dict:
    if not FX_PATH.exists():
        return {}
    try:
        return json.loads(FX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def fx_rate(currency: str = "USD", force: bool = False) -> tuple[float, bool]:
    """1단위당 원화. (환율, 최신여부)를 돌려준다.

    하루에도 몇 번씩 부를 자리라 12시간 캐시를 둔다. 실패하면 캐시된 값을,
    그것도 없으면 고정값을 쓰되 '최신 아님'으로 표시한다.
    """
    currency = currency.upper()
    if currency == "KRW":
        return 1.0, True

    cache = _read_cache()
    entry = cache.get(currency)
    if entry and not force:
        stamped = datetime.fromisoformat(entry["갱신"])
        if datetime.now() - stamped < timedelta(hours=FX_TTL_HOURS):
            return float(entry["환율"]), True

    try:
        response = requests.get(
            FX_URL.format(code=currency),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        quoted = float(response.json()["exchangeInfo"]["calcPrice"])
        rate = quoted / FX_QUOTE_UNITS.get(currency, 1)
        cache[currency] = {"환율": rate, "갱신": datetime.now().isoformat(timespec="seconds")}
        try:
            PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
            FX_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        return rate, True
    except Exception:
        if entry:
            return float(entry["환율"]), False
        return FX_FALLBACK.get(currency, 1.0), False


def _domestic() -> pd.DataFrame:
    from src.analysis.gemini_analyzer import load_financials
    from src.collectors.sector_collector import load as load_sectors

    try:
        df = load_financials()
    except FileNotFoundError:
        return pd.DataFrame()

    sectors = load_sectors()
    if not sectors.empty:
        df = df.merge(sectors, on="종목코드", how="left")
    for column in ("업종_대분류", "업종_소분류"):
        if column not in df:
            df[column] = "미분류"
        df[column] = df[column].fillna("미분류")

    df["국가"] = KOREA
    df["통화"] = "KRW"
    df["조회코드"] = df["종목코드"]
    df["시가총액_원화"] = df["시가총액"]
    return df


def _overseas() -> pd.DataFrame:
    from src.collectors.overseas_collector import load as load_overseas

    frames = []
    for country, label in COUNTRIES.items():
        df = load_overseas(country)
        if df.empty:
            continue
        df = df.copy()
        df["국가"] = label
        # 해외는 네이버 업종 하나뿐이라 대분류를 따로 두지 않는다
        df["업종_소분류"] = df.get("업종_소분류", pd.Series("미분류", index=df.index)).fillna("미분류")
        df["업종_대분류"] = df["업종_소분류"]

        # 환율은 행마다 그 종목의 통화로 건다. 시장 하나에 통화가 하나라고 보면
        # 언젠가 조용히 틀린다(홍콩은 한 거래소에 HKD와 CNY가 섞여 있다).
        rates = {code: fx_rate(str(code))[0] for code in df["통화"].dropna().unique()}
        df["시가총액_원화"] = df["시가총액"] * df["통화"].map(rates)
        frames.append(df)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_all() -> pd.DataFrame:
    """국내 + 해외를 하나로. 없는 열은 결측으로 남는다."""
    frames = [df for df in (_domestic(), _overseas()) if not df.empty]
    if not frames:
        return pd.DataFrame()

    # 공시는 여기서 채우지 않는다. 미리 열을 만들어 두면 나중에 공시 표를 merge할 때
    # 이름이 겹쳐 '공시성격_공시'로 밀려나고, 국내 공시 필터가 통째로 죽는다.
    return pd.concat(frames, ignore_index=True, sort=False)


def available_metrics(country: str) -> list[str]:
    return METRICS.get(country, METRICS[KOREA])


def has_disclosure(country: str) -> bool:
    return country in HAS_DISCLOSURE


def has_news(country: str) -> bool:
    return country in HAS_NEWS


def available_perspectives(country: str) -> list[str]:
    return PERSPECTIVES.get(country, PERSPECTIVES[KOREA])


def price_history(country: str, code: str, lookup: str | None = None) -> pd.DataFrame:
    """국가에 맞는 경로로 1년치 일봉을 받는다.

    국내는 네이버 금융 페이지를 25번 넘겨 긁고, 해외는 기간을 주면 한 번에 온다.
    돌려주는 열 이름이 같아서 지표 계산은 양쪽이 같은 코드를 쓴다.
    """
    if country == KOREA:
        from src.collectors.news_collector import fetch_price_history

        return fetch_price_history(code, pages=25)

    from src.collectors.overseas_collector import fetch_price_history as fetch_overseas

    return fetch_overseas(lookup or code)
