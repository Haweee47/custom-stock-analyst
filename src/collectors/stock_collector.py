"""국내 시세를 모은다. 네이버 모바일 증권 API를 쓴다.

2026-09에 네이버가 시가총액 페이지(finance.naver.com/sise/sise_market_sum.naver)를
새 주소로 옮기면서 HTML 표를 없앴다. 옛 주소는 이제 JS로 그리는 페이지로 넘어가고,
표를 긁던 파서는 0행을 돌려준다. 그 결과 9월 중순 내내 국내 시세가 갱신되지 않았고
(화면에 '데이터 기준 2026-08-31'이 떠 있었다), 갱신 배치는 KeyError로 죽었다.

HTML을 긁는 대신 그 페이지가 쓰는 JSON API를 그대로 쓴다. 표가 아니라 값이 오므로
구조가 조금 바뀌어도 덜 깨지고, 43번 호출이면 코스피·코스닥 전체가 들어온다.

    python -m src.collectors.stock_collector

이 API가 주지 않는 값(외국인비율·PER·ROE)은 빈 칸으로 둔다. 지우지 않고 빈 칸으로
두는 이유는 financial_collector.refresh_prices()가 빈 칸을 이전 값으로 되돌리기
때문이다. PER은 거기서 오늘 시가총액으로 다시 계산한다 — 3주 전 PER을 오늘 주가
옆에 놓으면 둘이 어긋난다.
"""
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from src.collectors.progress import track

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
LIST_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}"
ETF_LIST_URL = "https://finance.naver.com/api/sise/etfItemList.nhn"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
MARKETS = ["KOSPI", "KOSDAQ"]
PAGE_SIZE = 100
REQUEST_DELAY = 0.2

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

# 이 API가 주지 않는 값. 빈 칸으로 넘겨야 이전 값이 살아남는다.
MISSING_COLUMNS = ["외국인비율", "PER", "ROE"]


def _fetch_page(market: str, page: int) -> dict:
    response = requests.get(
        LIST_URL.format(market=market),
        params={"page": page, "pageSize": PAGE_SIZE},
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _number(value) -> float | None:
    """'15,042,569' 같은 문자열을 숫자로. 값이 없으면 None."""
    if value in (None, "", "N/A", "-"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").replace("+", ""))
    except ValueError:
        return None


def _parse_stocks(payload: dict, market: str) -> list[dict]:
    """응답 한 쪽을 우리 열 이름으로 옮긴다.

    Raw가 붙은 필드를 쓴다. 쉼표가 없는 원본 값이라 자릿수를 잘못 읽을 일이 없다.
    """
    rows = []
    for item in payload.get("stocks") or []:
        price = _number(item.get("closePriceRaw"))
        cap = _number(item.get("marketValueRaw"))
        rows.append(
            {
                "종목코드": str(item.get("itemCode", "")).zfill(6),
                "종목명": item.get("stockName"),
                "시장구분": market,
                "현재가": price,
                "등락률": _number(item.get("fluctuationsRatio")),
                "시가총액": cap,
                # API가 주식수를 주지 않는다. 시가총액 ÷ 주가로 구한다.
                # 저장 단위는 천주다 — 화면이 그 단위를 전제로 표시한다.
                "상장주식수": round(cap / price / 1000) if price and cap else None,
                "거래량": _number(item.get("accumulatedTradingVolumeRaw")),
                "종류": item.get("stockEndType"),
            }
        )
    return rows


def fetch_etf_codes() -> set[str]:
    response = requests.get(ETF_LIST_URL, headers=HEADERS, timeout=15)
    response.raise_for_status()
    items = response.json()["result"]["etfItemList"]
    return {item["itemcode"] for item in items}


def classify(code: str, name: str, etf_codes: set[str], kind: str | None = None) -> str:
    """보통주·우선주·ETF·ETN을 가른다. 재무제표가 없는 것은 분석 대상에서 빠진다."""
    if kind and kind.lower() != "stock":
        return "ETF" if kind.lower() == "etf" else kind.upper()
    if code in etf_codes:
        return "ETF"
    if name and (name.endswith("ETN") or "ETN" in name):
        return "ETN"
    # 우선주는 보통주 코드의 끝자리를 1 이상으로 바꿔 부여된다
    if not code.endswith("0"):
        return "우선주"
    return "보통주"


def collect_market(market: str) -> pd.DataFrame:
    first = _fetch_page(market, 1)
    total = int(first.get("totalCount") or 0)
    records = _parse_stocks(first, market)

    pages = range(2, (total + PAGE_SIZE - 1) // PAGE_SIZE + 1)
    for page in track(list(pages), desc=f"{market} 시세"):
        time.sleep(REQUEST_DELAY)
        records.extend(_parse_stocks(_fetch_page(market, page), market))

    if not records:
        raise RuntimeError(
            f"{market} 시세가 비어 있습니다. 네이버 응답 형식이 또 바뀌었는지 확인하세요."
        )
    return pd.DataFrame(records)


def collect_market_snapshot() -> pd.DataFrame:
    etf_codes = fetch_etf_codes()
    df = pd.concat([collect_market(market) for market in MARKETS], ignore_index=True)
    df = df.drop_duplicates(subset="종목코드", keep="first")

    df["종목구분"] = [
        classify(code, name, etf_codes, kind)
        for code, name, kind in zip(df["종목코드"], df["종목명"], df["종류"])
    ]
    for column in MISSING_COLUMNS:
        df[column] = pd.NA
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
