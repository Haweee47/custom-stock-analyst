"""종목별 최근 뉴스 제목과 일별 시세를 수집한다.

뉴스는 제목·날짜·언론사만 가져온다. 기사 본문은 언론사 저작물이므로
수집하거나 저장하지 않고, AI에도 제목만 전달한다.
"""
import time
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

NEWS_URL = "https://finance.naver.com/item/news_news.naver"
PRICE_URL = "https://finance.naver.com/item/sise_day.naver"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
REQUEST_DELAY = 0.3


def _soup(url: str, params: dict) -> BeautifulSoup:
    response = requests.get(url, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    response.encoding = "euc-kr"
    return BeautifulSoup(response.text, "lxml")


def fetch_news(stock_code: str, limit: int = 15) -> list[dict]:
    """최근 뉴스 제목 목록. 본문은 가져오지 않는다."""
    soup = _soup(
        NEWS_URL,
        {"code": stock_code, "page": 1, "sm": "title_entity_id.basic", "clusterId": ""},
    )

    items, seen = [], set()
    for tr in soup.select("table.type5 tr"):
        link = tr.select_one("td.title a")
        if link is None:
            continue
        title = link.get_text(strip=True)
        # 같은 기사가 여러 매체로 중복 노출되므로 제목 기준으로 걸러낸다
        if title in seen:
            continue
        seen.add(title)

        press = tr.select_one("td.info")
        date = tr.select_one("td.date")
        items.append(
            {
                "제목": title,
                "언론사": press.get_text(strip=True) if press else "",
                "일자": date.get_text(strip=True) if date else "",
            }
        )
        if len(items) >= limit:
            break
    return items


def fetch_price_history(stock_code: str, pages: int = 7) -> pd.DataFrame:
    """일별 시세. 한 페이지가 10거래일이므로 기본 7페이지는 약 70거래일."""
    records = []
    for page in range(1, pages + 1):
        soup = _soup(PRICE_URL, {"code": stock_code, "page": page})
        for tr in soup.select("table.type2 tr"):
            cells = [x.get_text(strip=True) for x in tr.select("span.tah")]
            if len(cells) != 7:
                continue
            records.append(
                {
                    "일자": cells[0],
                    "종가": cells[1],
                    "시가": cells[3],
                    "고가": cells[4],
                    "저가": cells[5],
                    "거래량": cells[6],
                }
            )
        time.sleep(REQUEST_DELAY)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["일자"] = pd.to_datetime(df["일자"], format="%Y.%m.%d")
    for col in ["종가", "시가", "고가", "저가", "거래량"]:
        df[col] = pd.to_numeric(df[col].str.replace(",", "", regex=False), errors="coerce")
    return df.sort_values("일자").reset_index(drop=True)


def technical_summary(df: pd.DataFrame) -> dict:
    """기술적 분석용 지표. 지표 계산은 코드가 하고 해석만 AI에 맡긴다."""
    if df.empty or len(df) < 20:
        return {}

    close = df["종가"]
    latest = close.iloc[-1]
    ma5, ma20 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None

    # RSI(14) - 상승분과 하락분의 비율로 과열·침체를 본다
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
    rsi = 100 - 100 / (1 + gain / loss) if loss and loss > 0 else None

    period_high, period_low = close.max(), close.min()
    return {
        "기간": f"{df['일자'].iloc[0]:%Y-%m-%d} ~ {df['일자'].iloc[-1]:%Y-%m-%d}",
        "거래일수": len(df),
        "현재가": int(latest),
        "5일이평": round(ma5),
        "20일이평": round(ma20),
        "60일이평": round(ma60) if ma60 else None,
        "기간고가": int(period_high),
        "기간저가": int(period_low),
        "고가대비": round((latest / period_high - 1) * 100, 2),
        "저가대비": round((latest / period_low - 1) * 100, 2),
        "RSI14": round(rsi, 1) if rsi else None,
        "20일변동성": round(close.pct_change().rolling(20).std().iloc[-1] * 100, 2),
        "거래량20일평균대비": round(
            df["거래량"].iloc[-1] / df["거래량"].rolling(20).mean().iloc[-1], 2
        ),
    }


def price_performance(df: pd.DataFrame) -> dict:
    """리포트 좌측 박스에 넣을 기간별 주가 등락률. 거래일 기준으로 되짚는다."""
    if df.empty:
        return {}
    close = df["종가"]
    latest = close.iloc[-1]
    periods = {"1개월": 20, "3개월": 60, "6개월": 120, "12개월": 240}
    out = {}
    for label, days in periods.items():
        if len(close) > days:
            out[label] = round((latest / close.iloc[-1 - days] - 1) * 100, 1)
        else:
            out[label] = None
    return out


if __name__ == "__main__":
    import sys

    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    news = fetch_news(code, limit=5)
    print(f"뉴스 {len(news)}건")
    for item in news:
        print(f"  [{item['일자']}] ({item['언론사']}) {item['제목'][:50]}")

    prices = fetch_price_history(code)
    print(f"\n시세 {len(prices)}거래일")
    for key, value in technical_summary(prices).items():
        print(f"  {key}: {value}")
