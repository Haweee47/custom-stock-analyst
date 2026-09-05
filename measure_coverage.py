"""애널리스트 리포트 커버리지 공백을 측정한다.

이 서비스가 푸는 문제가 실제로 존재하는지 숫자로 확인한다.
'소형주는 리포트가 없다'는 말은 누구나 하지만, 몇 %가 없는지는 세어 봐야 안다.

네이버 종목 화면의 증권사 리포트 목록을 시가총액 구간별로 표본 조사한다.
결과는 기획서에 그대로 들어가므로 표본 수와 시점을 함께 남긴다.

    python measure_coverage.py            구간별 100종목씩
    python measure_coverage.py 50         구간별 50종목씩
"""
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.collectors import markets  # noqa: E402
from src.collectors.progress import track  # noqa: E402

OUT = ROOT / "data" / "processed" / "coverage.json"
URL = "https://m.stock.naver.com/api/stock/{code}/integration"
HEADERS = {"User-Agent": "Mozilla/5.0"}
DELAY = 0.15

# 시가총액 구간 (억원). 커버리지가 규모를 따라간다는 것을 보이려면 나눠 세야 한다.
TIERS = [
    ("초대형 (10조 이상)", 100_000, None),
    ("대형 (1조~10조)", 10_000, 100_000),
    ("중형 (3천억~1조)", 3_000, 10_000),
    ("소형 (1천억~3천억)", 1_000, 3_000),
    ("초소형 (1천억 미만)", None, 1_000),
]


def fetch_reports(code: str) -> list[dict]:
    try:
        response = requests.get(URL.format(code=code), headers=HEADERS, timeout=15)
        response.raise_for_status()
        return (response.json() or {}).get("researches") or []
    except (requests.RequestException, ValueError):
        return []


def days_since(stamp: str | None) -> int | None:
    if not stamp or len(str(stamp)) != 8:
        return None
    try:
        written = datetime.strptime(str(stamp), "%Y%m%d").date()
    except ValueError:
        return None
    return (date.today() - written).days


def measure(pool, sample_size: int) -> dict:
    caps = pool["시가총액_원화"] / 1e8
    summary = {}

    for label, low, high in TIERS:
        tier = pool[(caps >= (low or 0)) & (caps < (high or float("inf")))]
        picked = tier.nlargest(min(sample_size, len(tier)), "시가총액_원화")
        if picked.empty:
            continue

        covered, fresh, ages = 0, 0, []
        for code in track(picked["종목코드"].tolist(), desc=f"{label} 표본 {len(picked)}"):
            time.sleep(DELAY)
            reports = fetch_reports(str(code))
            if not reports:
                continue
            covered += 1
            newest = min(
                (d for d in (days_since(r.get("wdt")) for r in reports) if d is not None),
                default=None,
            )
            if newest is not None:
                ages.append(newest)
                if newest <= 90:
                    fresh += 1

        total = len(picked)
        summary[label] = {
            "표본": total,
            "리포트있음": covered,
            "보유율": round(covered / total * 100, 1),
            "최근3개월": fresh,
            "최신율": round(fresh / total * 100, 1),
            "경과일_중앙값": sorted(ages)[len(ages) // 2] if ages else None,
        }
        item = summary[label]
        print(
            f"  {label:20} 표본 {total:3} · 리포트 {item['보유율']:5.1f}% · "
            f"최근3개월 {item['최신율']:5.1f}%"
        )

    return summary


def main() -> int:
    sample_size = int(sys.argv[1]) if len(sys.argv) > 1 else 100

    universe = markets.load_all()
    pool = universe[universe["국가"] == markets.KOREA].dropna(subset=["시가총액_원화"])
    print(f"국내 {len(pool):,}종목 중 구간별 상위 {sample_size}종목 표본 조사\n")

    summary = measure(pool, sample_size)
    payload = {
        "측정일": date.today().isoformat(),
        "대상": "국내 (코스피·코스닥)",
        "출처": "네이버 금융 종목별 증권사 리포트 목록",
        "구간별": summary,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
