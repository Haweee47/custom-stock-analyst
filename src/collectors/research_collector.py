"""종목별 증권사 리포트 현황을 수집한다.

이 서비스가 있는 이유는 애널리스트가 다루지 않는 종목이다. 그런데 워밍은 시가총액
순으로 채우고 있었다. 시총 상위는 원래 리포트가 가장 많은 쪽이라, 하루 500건인 무료
한도를 이미 커버되는 종목에 쓰고 있던 셈이다. 어느 종목에 최근 리포트가 없는지 알아야
공백부터 채울 수 있다.

국내만 수집한다. 해외 종목의 한국어 리포트 목록은 받을 곳이 없다.

    python -m src.collectors.research_collector
"""
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from src.collectors.progress import track

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "processed" / "research_coverage.csv"
URL = "https://m.stock.naver.com/api/stock/{code}/integration"
HEADERS = {"User-Agent": "Mozilla/5.0"}
DELAY = 0.15

# 이 기간 안에 나온 리포트가 있어야 '다뤄지고 있다'고 본다. measure_coverage.py와 같은 기준.
FRESH_DAYS = 90

COLUMNS = ["종목코드", "리포트수", "최근리포트일", "수집일"]


def fetch_reports(code: str) -> list[dict] | None:
    """증권사 리포트 목록. 조회에 실패하면 None — 빈 목록(리포트 없음)과 구분한다.

    둘을 섞으면 네트워크가 한 번 끊긴 종목이 '리포트 없음'으로 기록되고,
    공백 우선 워밍이 그 종목에 한도를 쓴다.
    """
    try:
        response = requests.get(URL.format(code=code), headers=HEADERS, timeout=15)
        response.raise_for_status()
        return (response.json() or {}).get("researches") or []
    except (requests.RequestException, ValueError):
        return None


def newest_date(reports: list[dict]) -> str | None:
    """가장 최근 리포트 일자('YYYY-MM-DD'). 읽을 수 있는 날짜가 없으면 None."""
    dates = []
    for report in reports:
        try:
            dates.append(datetime.strptime(str(report.get("wdt")), "%Y%m%d").date())
        except ValueError:
            continue
    return max(dates).isoformat() if dates else None


def collect(codes, fetch=fetch_reports, delay: float = DELAY) -> pd.DataFrame:
    """종목마다 리포트 수와 가장 최근 일자를 모은다. 조회에 실패한 종목은 기록하지 않는다."""
    today = date.today().isoformat()
    rows, failed = [], 0
    for code in track(list(codes), desc="증권사 리포트 현황"):
        reports = fetch(str(code))
        if delay:
            time.sleep(delay)
        if reports is None:
            failed += 1
            continue
        rows.append(
            {
                "종목코드": str(code),
                "리포트수": len(reports),
                "최근리포트일": newest_date(reports),
                "수집일": today,
            }
        )
    if failed:
        print(f"조회 실패 {failed}건은 기록하지 않았습니다. 다음 수집 때 다시 확인합니다.")
    return pd.DataFrame(rows, columns=COLUMNS)


def load() -> pd.DataFrame:
    """저장된 현황. 없으면 빈 표를 돌려준다."""
    if not OUT.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(OUT, dtype={"종목코드": str}, encoding="utf-8-sig")


def main() -> int:
    from src.analysis.gemini_analyzer import load_universe
    from src.collectors import markets

    universe = load_universe()
    codes = universe.loc[universe["국가"] == markets.KOREA, "종목코드"]
    print(f"국내 {len(codes):,}종목의 증권사 리포트 현황을 수집합니다.")

    frame = collect(codes)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT, index=False, encoding="utf-8-sig")

    newest = pd.to_datetime(frame["최근리포트일"], errors="coerce")
    fresh = int(((pd.Timestamp(date.today()) - newest).dt.days <= FRESH_DAYS).sum())
    print(
        f"\n저장: {OUT}\n"
        f"수집 {len(frame):,}종목 · 리포트 있음 {int((frame['리포트수'] > 0).sum()):,} · "
        f"최근 {FRESH_DAYS}일 안에 있음 {fresh:,} · 공백 {len(frame) - fresh:,}"
    )
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
