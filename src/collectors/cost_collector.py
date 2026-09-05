"""국내 종목의 원가 구조(매출원가·판관비)를 모은다.

'영업이익률이 왜 올랐나'에 답하려면 매출과 영업이익만으로는 부족하다.
DART 주요계정 API(fnlttSinglAcnt)는 매출액·영업이익·당기순이익만 주지만,
전체 재무제표 API(fnlttSinglAcntAll)에는 매출원가와 판매비와관리비가 들어 있다.

이 둘이 있으면 마진 변화를 쪼갤 수 있다.
    영업이익률 = 100% - 원가율 - 판관비율
    삼성전자 2024→2025: 영업이익률 +2.19%p = 원가율 -1.39%p + 판관비율 -0.80%p
'마진이 좋아졌다'가 아니라 '원가율이 내려가서 좋아졌다'까지 말할 수 있다.

여기까지가 이 데이터의 한계다. 원가율이 왜 내려갔는지(단가·물량·환율)는
사업보고서 본문을 읽어야 알 수 있고, 전 종목에 적용할 수 없다.

한 종목당 한 번 호출한다. 국내 2,655개면 DART 일일 한도(20,000) 안에서 끝난다.
재무는 분기마다 바뀌므로 매일 돌릴 필요가 없다.
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.api.dart_client import BASE_URL, _api_key, map_stock_to_corp  # noqa: E402
from src.collectors.progress import track  # noqa: E402

PROCESSED_DIR = ROOT / "data" / "processed"
REQUEST_DELAY = 0.12
RETRIES = 3
BACKOFF = 3

# DART 계정명 → 우리 열 이름. 회사마다 표기가 조금씩 다르다.
ACCOUNT_ALIASES = {
    "매출원가": "매출원가",
    "판매비와관리비": "판매비와관리비",
    "판매비와 관리비": "판매비와관리비",
}

# 당기 / 전기 / 전전기가 한 응답에 함께 온다
PERIODS = {
    "thstrm_amount": "",
    "frmtrm_amount": "_전기",
    "bfefrmtrm_amount": "_전전기",
}


def _amount(text) -> float | None:
    if text in (None, "", "-"):
        return None
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def fetch_costs(corp_code: str, year: int, report: str = "11011") -> dict:
    """한 회사의 원가 구조. 연결(CFS)이 없으면 개별(OFS)로 물러선다."""
    for fs_div in ("CFS", "OFS"):
        payload = _request(corp_code, year, report, fs_div)
        rows = payload.get("list") or []
        if not rows:
            continue

        found = {}
        for row in rows:
            column = ACCOUNT_ALIASES.get(str(row.get("account_nm", "")).strip())
            if not column or row.get("sj_div") not in ("IS", "CIS"):
                continue
            for field, suffix in PERIODS.items():
                value = _amount(row.get(field))
                if value is not None:
                    found.setdefault(f"{column}{suffix}", value)
        if found:
            return found
    return {}


def _request(corp_code: str, year: int, report: str, fs_div: str) -> dict:
    params = {
        "crtfc_key": _api_key(),
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": report,
        "fs_div": fs_div,
    }
    for attempt in range(1, RETRIES + 1):
        try:
            response = requests.get(f"{BASE_URL}/fnlttSinglAcntAll.json", params=params, timeout=30)
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("application/json"):
                return {}
            return response.json()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError):
            if attempt == RETRIES:
                return {}
            time.sleep(BACKOFF * attempt)
    return {}


def path_for(year: int) -> Path:
    return PROCESSED_DIR / f"costs_{year}.csv"


def collect(year: int = 2025, limit: int | None = None) -> pd.DataFrame:
    financials = pd.read_csv(
        PROCESSED_DIR / f"financials_{year}.csv", dtype={"종목코드": str}
    )
    codes = financials["종목코드"].dropna().tolist()
    if limit:
        codes = codes[:limit]

    mapping = map_stock_to_corp(codes)
    print(f"원가 구조 수집 대상 {len(mapping):,}개")

    records = []
    for code, corp in track(list(mapping.items()), desc="원가 수집"):
        time.sleep(REQUEST_DELAY)
        found = fetch_costs(corp, year)
        if found:
            records.append({"종목코드": code, **found})

    result = pd.DataFrame(records)
    print(f"원가 확보 {len(result):,}개")
    return result


def save(df: pd.DataFrame, year: int = 2025) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = path_for(year)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out


def load(year: int = 2025) -> pd.DataFrame:
    path = path_for(year)
    if not path.exists():
        return pd.DataFrame(columns=["종목코드"])
    return pd.read_csv(path, dtype={"종목코드": str})


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = collect(2025, limit=limit)
    if not result.empty:
        print(f"저장: {save(result, 2025)}")
