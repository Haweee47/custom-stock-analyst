"""이미 만들어 둔 리포트에 숫자 대조 결과를 채워 넣는다.

검증은 저장된 리포트와 원본 데이터만 있으면 되므로 Gemini를 다시 부르지 않는다.
즉 비용이 0이다. 검증 기능을 넣기 전에 만든 캐시도 같은 표시를 갖게 된다.

관점에 따라 재료가 더 필요하다. '기술적'은 주가 지표가, '이슈·트렌드'는 뉴스와
공시가 있어야 인용을 인용으로 알아본다. 둘 다 무료로 다시 받을 수 있으므로
필요한 관점에서만 받아 온다.

    python backfill_verify.py            채워 넣는다
    python backfill_verify.py --dry-run  결과만 본다
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.analysis import peer, verify  # noqa: E402
from src.analysis.gemini_analyzer import CACHE_DIR, MARKET_CODES  # noqa: E402
from src.analysis.report_spec import PERSPECTIVES  # noqa: E402
from src.collectors import markets  # noqa: E402

# 파일 이름 앞의 시장 코드 → 국가
COUNTRY_OF = {code: country for country, code in MARKET_CODES.items()}


def split_name(name: str) -> tuple[str | None, str, str, str] | None:
    """'KR_005930_펀더멘탈_압축형' → (국내주식, 005930, 펀더멘탈, 압축형)"""
    parts = name.removesuffix(".json").split("_")
    if len(parts) != 4 or parts[0] not in COUNTRY_OF:
        return None
    return COUNTRY_OF[parts[0]], parts[1], parts[2], parts[3]


def gather(row, country: str, perspective: str) -> tuple[dict | None, list | None, list | None]:
    """검증에 필요한 재료를 다시 모은다. 전부 무료 경로다."""
    needed = PERSPECTIVES.get(perspective, {}).get("데이터", [])
    tech = news = disclosures = None

    if "기술" in needed:
        try:
            prices = markets.price_history(country, row["종목코드"], row.get("조회코드"))
            if not prices.empty:
                from src.collectors.news_collector import technical_summary

                tech = technical_summary(prices)
        except Exception:
            pass

    if "뉴스" in needed and markets.has_news(country):
        try:
            from src.collectors.news_collector import fetch_news

            news = fetch_news(row["종목코드"])
        except Exception:
            pass

    if "공시" in needed and markets.has_disclosure(country):
        try:
            from src.api.disclosure import fetch_important

            disclosures = fetch_important(row["종목코드"])
        except Exception:
            pass

    return tech, news, disclosures


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    universe = markets.load_all()
    if universe.empty:
        sys.exit("종목 데이터가 없습니다. 먼저 수집을 돌리세요.")

    # 한국과 중국이 6자리 코드를 공유하므로 국가까지 넣어야 같은 종목을 찾는다
    universe = universe.reset_index(drop=True)
    by_key = {
        (str(r["국가"]), str(r["종목코드"])): index
        for index, r in universe.iterrows()
    }

    files = sorted(CACHE_DIR.glob("*.json"))
    print(f"캐시 {len(files)}건 검증{' (모의 실행)' if dry_run else ''}")

    passed, flagged, skipped = 0, 0, []
    for path in files:
        parsed = split_name(path.name)
        if parsed is None:
            skipped.append(path.name)
            continue

        country, code, perspective, _ = parsed
        index = by_key.get((country, code))
        if index is None:
            skipped.append(path.name)
            continue

        row = universe.iloc[index]
        data = json.loads(path.read_text(encoding="utf-8"))
        peers = peer.sector_stats(universe, row.get("업종_소분류"), row)
        tech, news, disclosures = gather(row, country, perspective)
        checked = verify.verify(data["리포트"], row, peers, tech, news, disclosures)

        if checked["통과"]:
            passed += 1
        else:
            flagged += 1
            items = ", ".join(u["표기"] for u in checked["미확인"][:4])
            print(f"  [{checked['대조율']:5.1f}%] {row['종목명']} {perspective} — {items}")

        if not dry_run:
            data["검증"] = checked
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n통과 {passed}건 · 확인 필요 {flagged}건 · 건너뜀 {len(skipped)}건")
    if skipped:
        print("건너뜀:", skipped)
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
