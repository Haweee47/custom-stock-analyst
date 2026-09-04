"""매일 돌리는 데이터 갱신 배치.

시세 → 재무 → 업종 → 공시 순서로 돈다. 재무는 시세 목록(보통주)을 쓰고,
공시 등급은 종목코드가 필요하므로 순서가 중요하다.

    python update_all.py            전체 갱신
    python update_all.py --quick    시세와 공시만 (재무·업종은 자주 안 바뀐다)
"""
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.collectors import dataset_meta  # noqa: E402


def _run(label: str, function) -> tuple[bool, str]:
    print(f"\n{'=' * 56}\n[{label}] 시작\n{'=' * 56}")
    started = time.time()
    try:
        note = function()
        elapsed = time.time() - started
        dataset_meta.stamp(label, note)
        print(f"[{label}] 완료 — {note} ({elapsed:.0f}초)")
        return True, note
    except Exception as exc:
        print(f"[{label}] 실패 — {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False, str(exc)


def update_prices() -> str:
    from src.collectors.financial_collector import refresh_prices
    from src.collectors.stock_collector import collect_market_snapshot, save_snapshot

    snapshot = collect_market_snapshot()
    save_snapshot(snapshot, datetime.now().strftime("%Y%m%d"))
    counts = snapshot["종목구분"].value_counts()

    # 스냅샷은 data/raw에 쌓이는데 화면이 읽는 표는 data/processed에 있다.
    # 여기서 시세 열만 옮겨 담아야 --quick 갱신이 실제로 화면에 반영된다.
    refreshed = refresh_prices(datetime.now().year - 1)
    note = f"{len(snapshot):,}개 종목 (보통주 {counts.get('보통주', 0):,})"
    return f"{note}, 리포트 표 시세 반영 {refreshed:,}개" if refreshed else note


def update_financials() -> str:
    from src.collectors.financial_collector import collect, save

    year = datetime.now().year - 1
    result = collect(year)
    if result.empty:
        raise RuntimeError(f"{year}년 재무 데이터가 비어 있습니다")
    save(result, year)
    return f"{len(result):,}개 종목, 재무 확보 {int(result['매출액'].notna().sum()):,}개"


def update_sectors() -> str:
    from src.collectors.sector_collector import collect, save

    result = collect()
    save(result)
    return f"{len(result):,}개 종목 업종 매핑"


def update_overseas_prices() -> str:
    """해외 시세만 갈아 끼운다. 목록 API 68회면 끝나서 매일 돌려도 부담이 없다."""
    from src.collectors.overseas_collector import refresh_prices

    updated = refresh_prices("미국")
    if not updated:
        raise RuntimeError("해외 종목 표가 없습니다. --full로 먼저 수집하세요.")
    return f"미국 {updated:,}개 종목 시세 갱신"


def update_overseas_full() -> str:
    """해외 재무까지 새로 받는다. 종목마다 1회씩이라 6,775회, 55분쯤 걸린다."""
    from src.collectors.overseas_collector import collect, save

    result = collect("미국")
    save(result, "미국")
    filled = int(result["매출액"].notna().sum())
    return f"미국 {len(result):,}개 종목 (재무 확보 {filled:,}개)"


def update_disclosures() -> str:
    from src.collectors.disclosure_batch import collect, save

    result = collect()
    save(result)
    major = int((result["공시성격"] == "중대 공시").sum())
    return f"{len(result):,}개 종목 (중대 공시 {major}개)"


# (이름, 함수, --quick에도 도는가)
# 재무는 분기마다만 바뀌므로 매일 돌리지 않는다. 국내 재무는 DART 2,655회,
# 해외 재무는 6,775회라 둘 다 무겁다.
STEPS = [
    ("시세", update_prices, True),
    ("해외시세", update_overseas_prices, True),
    ("재무", update_financials, False),
    ("해외재무", update_overseas_full, False),
    ("업종", update_sectors, False),
    ("공시", update_disclosures, True),
]


def main() -> int:
    quick = "--quick" in sys.argv
    steps = [(name, fn) for name, fn, in_quick in STEPS if in_quick or not quick]

    print(f"데이터 갱신 시작 — {datetime.now():%Y-%m-%d %H:%M}")
    if quick:
        print("(--quick: 시세와 공시만 갱신)")

    results = [(name, *_run(name, fn)) for name, fn in steps]

    print(f"\n{'=' * 56}\n요약\n{'=' * 56}")
    for name, ok, note in results:
        print(f"  {'성공' if ok else '실패'}  {name:5} {note[:60]}")
    print(f"\n{dataset_meta.summary_line()}")

    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print(f"\n실패한 단계: {', '.join(failed)}")
        return 1
    print("\n전체 완료. 배포에 반영하려면 커밋 후 푸시하세요.")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
