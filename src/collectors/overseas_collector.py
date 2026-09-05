"""해외 주식 시세·재무를 모은다. 지금은 미국(나스닥·뉴욕)만 켜져 있다.

국내와 같은 계열의 네이버 API를 쓴다. 다행히 계정명이 한국어로 오고(매출액,
당기순이익, PER) 종목명도 한글이라 국내 스키마와 어휘가 거의 맞는다.

다만 국내와 다른 점이 셋 있다.
  1) 통화가 다르다. 원화 환산값을 따로 들고 다녀야 시장을 섞어 비교할 수 있다.
  2) 계정이 다르다. 영업이익·자본총계·부채총계가 없고 EBIT·EBITDA·ROA가 온다.
     그래서 부채비율과 ROE는 해외에서 계산할 수 없다.
  3) 공시가 없다. DART는 국내 전용이다.

수집은 두 단계다. 목록(시총순)은 페이지당 100개라 미국 전체가 68회로 끝나지만,
재무는 종목마다 한 번씩 불러야 해서 6,775회가 든다. 재무는 분기마다만 바뀌므로
매일 돌릴 필요가 없다.
"""
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.collectors.progress import track  # noqa: E402

PROCESSED_DIR = ROOT / "data" / "processed"
BASE = "https://api.stock.naver.com/stock"
HEADERS = {"User-Agent": "Mozilla/5.0"}

REQUEST_DELAY = 0.1
RETRIES = 3
BACKOFF = 2
PAGE_SIZE = 100

# 나라별로 어느 거래소를 담을지. 전부 같은 API로 열린다.
# 홍콩은 목록 API가 400을 뱉어 개별 조회만 되므로 아직 넣지 않았다.
MARKETS = {
    "미국": ["NASDAQ", "NYSE"],
    "일본": ["TOKYO"],
    "중국": ["SHANGHAI", "SHENZHEN"],
}

EXCHANGE_LABELS = {
    "NASDAQ": "나스닥",
    "NYSE": "뉴욕",
    "TOKYO": "도쿄",
    "SHANGHAI": "상해",
    "SHENZHEN": "심천",
}

# 재무 응답의 계정명 → 우리 컬럼명. 없는 계정은 그대로 비워 둔다.
ACCOUNTS = {
    "매출액": "매출액",
    "당기순이익": "당기순이익",
    "EBIT": "영업이익",  # 해외는 영업이익 대신 EBIT을 준다. 가장 가까운 항목이다.
    "EBITDA": "EBITDA",
    "PER": "PER",
    "PBR": "PBR",
    "ROA": "ROA",
    "배당수익률": "배당수익률",
}

# 금액 계정과 비율 계정은 단위가 다르다. 섞으면 조용히 틀린다.
MONEY_ACCOUNTS = {"매출액", "당기순이익", "영업이익", "EBITDA"}

# 재무 응답의 단위: value는 현지통화 백만, krw는 억원. 검산으로 확인했다.
# (NVDA 매출 60,922 USD백만 × 1,350 = 82.2조원 = 823,117억원 = krw 필드값)
VALUE_UNIT = 1e6
KRW_UNIT = 1e8


class OverseasFetchError(RuntimeError):
    """재시도까지 했는데도 못 받았을 때."""


def _get(url: str, params: dict | None = None) -> dict:
    for attempt in range(1, RETRIES + 1):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=20)
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            if attempt == RETRIES:
                raise OverseasFetchError(f"{type(exc).__name__}: {url}") from exc
            time.sleep(BACKOFF * attempt)
    raise OverseasFetchError("도달할 수 없는 경로")


def _number(text) -> float | None:
    """'5,505,645,000' 같은 문자열을 숫자로. 빈 값과 '-'는 결측으로 본다."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    cleaned = str(text).replace(",", "").strip()
    if cleaned in ("", "-", "N/A"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def list_exchange(exchange: str, limit: int | None = None) -> pd.DataFrame:
    """한 거래소의 종목을 시가총액 순으로 받는다.

    목록 응답에 시총·통화·업종·거래량이 다 들어 있어서, 시세만 필요하면
    이 호출만으로 끝난다.
    """
    first = _get(f"{BASE}/exchange/{exchange}/marketValue", {"page": 1, "pageSize": PAGE_SIZE})
    total = int(first.get("totalCount", 0))
    if limit:
        total = min(total, limit)

    rows = list(first.get("stocks", []))
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    for page in track(range(2, pages + 1), desc=f"{EXCHANGE_LABELS.get(exchange, exchange)} 목록"):
        time.sleep(REQUEST_DELAY)
        payload = _get(f"{BASE}/exchange/{exchange}/marketValue", {"page": page, "pageSize": PAGE_SIZE})
        rows.extend(payload.get("stocks", []))
        if limit and len(rows) >= limit:
            break

    if limit:
        rows = rows[:limit]

    records = []
    for item in rows:
        industry = item.get("industryCodeType") or {}
        currency = item.get("currencyType") or {}
        records.append(
            {
                "종목코드": item.get("symbolCode"),
                "조회코드": item.get("reutersCode"),
                "종목명": item.get("stockName"),
                "영문명": item.get("stockNameEng"),
                "시장구분": EXCHANGE_LABELS.get(exchange, exchange),
                "통화": currency.get("code") or "USD",
                "현재가": _number(item.get("closePriceRaw") or item.get("closePrice")),
                "등락률": _number(item.get("fluctuationsRatioRaw") or item.get("fluctuationsRatio")),
                "시가총액": _number(item.get("marketValueRaw")),
                "거래량": _number(
                    item.get("accumulatedTradingVolumeRaw") or item.get("accumulatedTradingVolume")
                ),
                "배당수익률": _number(item.get("dividendYield")),
                "업종_소분류": industry.get("industryGroupKor") or "미분류",
                "상장폐지여부": bool(item.get("tradeStopType")),
            }
        )

    df = pd.DataFrame(records)
    return df[df["종목코드"].notna()].drop_duplicates(subset="종목코드").reset_index(drop=True)


def fetch_financials(code: str) -> dict:
    """한 종목의 3개년 연간 재무. 최신 연도를 당기로 보고 전기·전전기를 붙인다."""
    payload = _get(f"{BASE}/{code}/finance/annual")
    years = [t.get("title") for t in payload.get("trTitleList", [])]
    if not years:
        return {}

    # 응답이 연도순을 보장하지 않으므로 직접 정렬한다
    years = sorted(years)
    latest = years[-1]
    suffixes = {latest: ""}
    if len(years) >= 2:
        suffixes[years[-2]] = "_전기"
    if len(years) >= 3:
        suffixes[years[-3]] = "_전전기"

    result: dict = {"기준연도": int(str(latest)[:4]), "결산월": str(latest)[5:]}

    for row in payload.get("rowList", []):
        column = ACCOUNTS.get(row.get("title"))
        if not column:
            continue
        for year, cell in (row.get("columns") or {}).items():
            suffix = suffixes.get(year)
            if suffix is None:
                continue
            value = _number((cell or {}).get("value"))
            if value is None:
                continue
            # 금액은 현지통화 백만 단위로 오므로 원 단위로 편다. 비율은 그대로 쓴다.
            if column in MONEY_ACCOUNTS:
                result[f"{column}{suffix}"] = value * VALUE_UNIT
                krw = _number((cell or {}).get("krw"))
                if krw is not None:
                    result[f"{column}_원화{suffix}"] = krw * KRW_UNIT
            else:
                result[f"{column}{suffix}"] = value

    return result


def add_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """해외는 자본총계가 없어 부채비율·ROE를 구할 수 없다. 가능한 것만 계산한다."""
    if "영업이익" in df and "매출액" in df:
        df["영업이익률"] = (df["영업이익"] / df["매출액"] * 100).round(2)
    return df


def collect(country: str = "미국", limit: int | None = None, with_financials: bool = True) -> pd.DataFrame:
    frames = [list_exchange(exchange, limit) for exchange in MARKETS[country]]
    listing = pd.concat(frames, ignore_index=True)
    listing["국가"] = country
    print(f"{country} 목록 {len(listing):,}개 종목")

    if not with_financials:
        return listing

    records, failed = [], 0
    for code in track(listing["조회코드"], desc=f"{country} 재무"):
        time.sleep(REQUEST_DELAY)
        try:
            records.append(fetch_financials(code))
        except OverseasFetchError:
            records.append({})
            failed += 1
    if failed:
        print(f"재무를 받지 못한 종목 {failed:,}개 (시세는 남아 있다)")

    financials = pd.DataFrame(records, index=listing.index)

    # 목록과 재무에 같은 이름의 열이 있다(배당수익률). 그대로 이어 붙이면 열 이름이
    # 겹쳐서 row.get()이 값 대신 Series를 돌려주고, 그때부터 조용히 깨진다.
    # 목록 쪽이 현재 시점 값이므로 그쪽을 남긴다.
    duplicated = [c for c in financials.columns if c in listing.columns]
    if duplicated:
        financials = financials.drop(columns=duplicated)

    merged = pd.concat([listing, financials], axis=1)
    return add_derived_metrics(merged)


CHART_URL = BASE.replace("/stock", "/chart/foreign/item/{code}/day")


def fetch_price_history(code: str, days: int = 400) -> pd.DataFrame:
    """일봉 시세. 국내 수집기와 같은 열 이름으로 맞춰 지표 계산을 그대로 쓴다.

    국내는 페이지를 25번 넘겨야 1년치가 되는데, 해외는 기간을 주면 한 번에 온다.
    """
    end = datetime.now()
    begin = end - timedelta(days=days)
    payload = _get(
        CHART_URL.format(code=code),
        {
            "startDateTime": begin.strftime("%Y%m%d0000"),
            "endDateTime": end.strftime("%Y%m%d0000"),
        },
    )
    if not isinstance(payload, list) or not payload:
        return pd.DataFrame()

    df = pd.DataFrame(payload)
    out = pd.DataFrame(
        {
            "일자": pd.to_datetime(df["localDate"], format="%Y%m%d", errors="coerce"),
            "종가": pd.to_numeric(df["closePrice"], errors="coerce"),
            "시가": pd.to_numeric(df.get("openPrice"), errors="coerce"),
            "고가": pd.to_numeric(df["highPrice"], errors="coerce"),
            "저가": pd.to_numeric(df["lowPrice"], errors="coerce"),
            "거래량": pd.to_numeric(df.get("accumulatedTradingVolume"), errors="coerce"),
        }
    )
    return out.dropna(subset=["일자", "종가"]).sort_values("일자").reset_index(drop=True)


def path_for(country: str) -> Path:
    return PROCESSED_DIR / f"overseas_{country}.csv"


def save(df: pd.DataFrame, country: str = "미국") -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = path_for(country)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out


def load(country: str = "미국") -> pd.DataFrame:
    path = path_for(country)
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path, dtype={"종목코드": str})
    # 예전에 저장된 파일에 열 이름이 겹쳐 들어간 적이 있다. pandas가 '배당수익률.1'
    # 처럼 이름을 바꿔 읽으므로, 그런 잔재는 버린다.
    junk = [c for c in df.columns if c.rsplit(".", 1)[-1].isdigit() and c.rsplit(".", 1)[0] in df.columns]
    return df.drop(columns=junk) if junk else df


def refresh_prices(country: str = "미국") -> int:
    """시세만 목록 API로 갈아 끼운다. 재무는 건드리지 않는다(국내와 같은 구조)."""
    existing = load(country)
    if existing.empty:
        return 0

    frames = [list_exchange(exchange) for exchange in MARKETS[country]]
    fresh = pd.concat(frames, ignore_index=True)

    columns = ["현재가", "등락률", "시가총액", "거래량", "배당수익률", "종목명"]
    columns = [c for c in columns if c in fresh.columns and c in existing.columns]
    order = list(existing.columns)
    updated = existing.drop(columns=columns).merge(
        fresh[["종목코드", *columns]], on="종목코드", how="left"
    )
    save(updated[order], country)
    return int(updated["현재가"].notna().sum())


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    country = sys.argv[1] if len(sys.argv) > 1 else "미국"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if country not in MARKETS:
        sys.exit(f"모르는 시장입니다: {country} (가능: {', '.join(MARKETS)})")

    result = collect(country, limit=limit)
    out = save(result, country)
    filled = int(result["매출액"].notna().sum()) if "매출액" in result else 0
    print(f"{len(result):,}개 종목 저장 (재무 확보 {filled:,}개): {out}")
