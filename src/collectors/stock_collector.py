import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.collectors.progress import track

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
LIST_URL = "https://finance.naver.com/sise/sise_market_sum.naver"
ETF_LIST_URL = "https://finance.naver.com/api/sise/etfItemList.nhn"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MARKETS = {"KOSPI": 0, "KOSDAQ": 1}
REQUEST_DELAY = 0.3

COLUMNS = [
    "순위",
    "종목명",
    "현재가",
    "전일비",
    "등락률",
    "액면가",
    "시가총액",
    "상장주식수",
    "외국인비율",
    "거래량",
    "PER",
    "ROE",
    "토론",
]
NUMERIC_COLUMNS = ["현재가", "액면가", "시가총액", "상장주식수", "거래량", "외국인비율", "PER", "ROE"]
OUTPUT_COLUMNS = [
    "종목코드",
    "종목명",
    "시장구분",
    "종목구분",
    "현재가",
    "등락률",
    "시가총액",
    "상장주식수",
    "거래량",
    "외국인비율",
    "PER",
    "ROE",
]


def _fetch_page(sosok: int, page: int) -> BeautifulSoup:
    response = requests.get(
        LIST_URL, params={"sosok": sosok, "page": page}, headers=HEADERS, timeout=15
    )
    response.raise_for_status()
    response.encoding = "euc-kr"
    return BeautifulSoup(response.text, "lxml")


def _get_last_page(soup: BeautifulSoup) -> int:
    link = soup.select_one("td.pgRR a")
    if link is None:
        return 1
    return int(link["href"].split("page=")[-1])


def _parse_rows(soup: BeautifulSoup) -> list[dict]:
    rows = []
    for tr in soup.select("table.type_2 tbody tr"):
        anchor = tr.select_one("a.tltle")
        if anchor is None:
            continue
        values = [td.get_text(strip=True) for td in tr.select("td")]
        record = dict(zip(COLUMNS, values))
        record["종목코드"] = anchor["href"].split("code=")[-1]
        rows.append(record)
    return rows


def fetch_etf_codes() -> set[str]:
    response = requests.get(ETF_LIST_URL, headers=HEADERS, timeout=15)
    response.raise_for_status()
    items = response.json()["result"]["etfItemList"]
    return {item["itemcode"] for item in items}


def classify(code: str, name: str, etf_codes: set[str]) -> str:
    if code in etf_codes:
        return "ETF"
    if name.endswith("ETN") or "ETN" in name:
        return "ETN"
    # 우선주는 보통주 코드의 끝자리를 1 이상으로 바꿔 부여된다
    if not code.endswith("0"):
        return "우선주"
    return "보통주"


def collect_market(market: str) -> pd.DataFrame:
    sosok = MARKETS[market]
    first = _fetch_page(sosok, 1)
    last_page = _get_last_page(first)

    records = _parse_rows(first)
    for page in track(range(2, last_page + 1), desc=f"{market} 수집"):
        time.sleep(REQUEST_DELAY)
        records.extend(_parse_rows(_fetch_page(sosok, page)))

    df = pd.DataFrame(records)
    df["시장구분"] = market
    return df


def _to_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(
            df[column].str.replace(",", "", regex=False).replace({"": None, "N/A": None}),
            errors="coerce",
        )
    df["등락률"] = pd.to_numeric(
        df["등락률"].str.replace("%", "", regex=False), errors="coerce"
    )
    return df


def collect_market_snapshot() -> pd.DataFrame:
    etf_codes = fetch_etf_codes()
    frames = [collect_market(market) for market in MARKETS]
    df = pd.concat(frames, ignore_index=True)
    df = _to_numeric(df)
    # 네이버는 시가총액을 억원 단위로 제공하므로 원 단위로 환산
    df["시가총액"] = df["시가총액"] * 100_000_000
    df["종목구분"] = [
        classify(code, name, etf_codes)
        for code, name in zip(df["종목코드"], df["종목명"])
    ]
    return df[OUTPUT_COLUMNS]


def save_snapshot(df: pd.DataFrame, date: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"stock_snapshot_{date}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


if __name__ == "__main__":
    import sys

    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    today = datetime.now().strftime("%Y%m%d")
    snapshot = collect_market_snapshot()
    saved_path = save_snapshot(snapshot, today)
    print(f"{len(snapshot)}개 종목 저장 완료: {saved_path}")
    print(snapshot["종목구분"].value_counts().to_string())
