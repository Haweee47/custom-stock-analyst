"""전 종목 공시를 한 번에 받아 종목별 최고 등급을 정리한다.

종목마다 DART를 호출하면 2,655회지만, 기간으로 전체 공시를 받으면
수백 회로 끝난다. 시장 구분(corp_cls)별로 페이지를 넘기며 모은다.
"""
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.api.disclosure import _score  # noqa: E402

PROCESSED_DIR = ROOT / "data" / "processed"
FLAG_PATH = PROCESSED_DIR / "disclosure_flags.csv"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
REQUEST_DELAY = 0.12
# corp_code 없이 조회하면 DART가 검색기간을 3개월로 제한한다
SEARCH_DAYS = 89

# 숫자 등급은 종목 평가처럼 읽힐 수 있으므로 화면에는 공시 성격을 그대로 쓴다
TIER_LABELS = {
    7: "중대 공시",
    6: "공시 위반",
    5: "실적·계약",
    4: "주요 결정",
    3: "정기 보고",
    2: "안내 공시",
    1: "일반 공시",
}
TIER_HELP = {
    "중대 공시": "상장폐지·관리종목 지정우려·자본잠식·감사의견 거절·횡령배임·영업정지 등",
    "공시 위반": "불성실공시법인 지정·공시 번복 등 공시 신뢰성 문제",
    "실적·계약": "실적공시·공급계약·증자·사채 발행 등",
    "주요 결정": "자기주식·배당·신규투자·소송 등",
    "정기 보고": "사업·반기·분기보고서",
    "안내 공시": "자율공시·공정공시",
    "일반 공시": "그 밖의 공시",
}


def _fetch_page(market: str, begin: str, end: str, page: int) -> dict:
    response = requests.get(
        LIST_URL,
        params={
            "crtfc_key": os.getenv("DART_API_KEY"),
            "bgn_de": begin,
            "end_de": end,
            "corp_cls": market,
            "page_no": page,
            "page_count": 100,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def collect(days: int = SEARCH_DAYS) -> pd.DataFrame:
    end = date.today()
    begin = end - timedelta(days=days)
    begin_text, end_text = begin.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    records = []
    for market in ("Y", "K"):  # 유가증권, 코스닥
        first = _fetch_page(market, begin_text, end_text, 1)
        if first.get("status") != "000":
            print(f"[{market}] 조회 실패: {first.get('status')} {first.get('message')}")
            continue
        total_pages = int(first.get("total_page", 1))
        records.extend(first.get("list", []))

        for page in tqdm(
            range(2, total_pages + 1), desc=f"공시 수집 {'KOSPI' if market == 'Y' else 'KOSDAQ'}"
        ):
            time.sleep(REQUEST_DELAY)
            payload = _fetch_page(market, begin_text, end_text, page)
            if payload.get("status") == "000":
                records.extend(payload.get("list", []))

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["종목코드", "공시등급", "공시성격", "해당공시", "공시일자"])

    df = df[df["stock_code"].str.len() == 6].copy()
    df["등급"] = df["report_nm"].map(_score)
    df = df[df["등급"] > 0]

    # 종목별로 가장 높은 등급을 남기고, 같은 등급이면 최근 것을 쓴다
    df = df.sort_values(["등급", "rcept_dt"], ascending=[False, False])
    top = df.drop_duplicates("stock_code", keep="first")

    latest = (
        df.sort_values("rcept_dt", ascending=False)
        .drop_duplicates("stock_code", keep="first")[["stock_code", "rcept_dt"]]
        .rename(columns={"rcept_dt": "최근공시일"})
    )

    out = top.merge(latest, on="stock_code")
    return pd.DataFrame(
        {
            "종목코드": out["stock_code"],
            "공시등급": out["등급"],
            "공시성격": out["등급"].map(TIER_LABELS),
            "해당공시": out["report_nm"].str.strip(),
            "공시일자": pd.to_datetime(out["rcept_dt"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
            "최근공시일": pd.to_datetime(out["최근공시일"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
        }
    ).reset_index(drop=True)


def save(df: pd.DataFrame) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(FLAG_PATH, index=False, encoding="utf-8-sig")
    return FLAG_PATH


def load() -> pd.DataFrame:
    if not FLAG_PATH.exists():
        return pd.DataFrame(columns=["종목코드", "공시등급", "공시성격", "해당공시", "공시일자"])
    return pd.read_csv(FLAG_PATH, dtype={"종목코드": str})


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    result = collect()
    path = save(result)
    print(f"\n{len(result)}개 종목 공시 등급 저장: {path}")
    print(result["공시성격"].value_counts().to_string())
