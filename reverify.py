"""저장된 리포트를 지금의 검증기로 다시 대조한다.

검증기를 고쳐도 캐시에 박힌 '검증' 결과는 그대로다. 화면은 그 값을 읽으므로,
검증기만 고치면 이미 만들어진 리포트는 옛 판정을 계속 보여 준다. Gemini를 다시
부를 필요는 없다 — 리포트 본문은 그대로 두고 대조만 다시 하면 된다.

    python reverify.py            무엇이 달라지는지만 보여 준다
    python reverify.py --write    달라진 것을 캐시에 반영한다

기술적·이슈 관점은 보조지표와 뉴스가 있어야 대조가 되는데 그것은 네트워크를
다시 타야 한다. 그래서 재무만으로 대조가 끝나는 관점만 다시 본다.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.analysis import peer, verify  # noqa: E402
from src.analysis.gemini_analyzer import CACHE_DIR, MARKET_CODES, load_universe  # noqa: E402
from src.collectors.overview_collector import CACHE_PATH as OVERVIEW_CACHE  # noqa: E402

# 재무와 동종업계만 보는 관점. 나머지는 외부 자료가 있어야 대조가 성립한다.
OFFLINE_PERSPECTIVES = {"펀더멘탈"}


def _key(item: dict) -> tuple[str, float]:
    # 표기가 아니라 값으로 맞춘다. 규칙이 바뀌면 같은 숫자의 표기가 달라진다
    # ('70%' → '70%대', '544억원' → '-544억원'). 부호도 규칙에 따라 붙었다 떨어진다.
    return item["종류"], round(abs(float(item["값"])), 6)


def keep_confirmed(old: dict, new: dict) -> dict:
    """새 검증 결과에서, 생성 당시에 확인됐던 숫자는 확인된 것으로 둔다.

    재대조는 오늘 데이터로 한다. 그런데 시가총액·PER처럼 매일 바뀌는 값은 리포트를
    쓴 날과 다르다. 9/12에 재대조했더니 맞게 쓴 시가총액 13건이 미확인으로 떨어졌다.
    생성 때의 판정은 그날 데이터로 한 것이라 그쪽이 맞다. 재대조는 새 규칙으로
    풀리는 것만 반영하고, 확인된 숫자를 뒤집지는 않는다.
    """
    remaining = [_key(item) for item in old.get("미확인", [])]
    unmatched = []
    for item in new["미확인"]:
        key = _key(item)
        if key in remaining:
            remaining.remove(key)
            unmatched.append(item)

    total = new["전체"]
    checked = total - len(unmatched)
    return {
        **new,
        "확인": checked,
        "미확인": unmatched,
        "통과": not unmatched,
        "대조율": round(checked / total * 100, 1) if total else 100.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="저장된 리포트를 다시 대조한다")
    parser.add_argument("--write", action="store_true", help="달라진 결과를 캐시에 쓴다")
    args = parser.parse_args()

    universe = load_universe()
    by_market = {code: name for name, code in MARKET_CODES.items()}

    overviews = {}
    if OVERVIEW_CACHE.exists():
        overviews = json.loads(OVERVIEW_CACHE.read_text(encoding="utf-8"))

    changed, improved, worsened, skipped = [], 0, 0, 0
    before_pass = after_pass = total = 0

    for path in sorted(CACHE_DIR.glob("*.json")):
        market_code, code, perspective, _ = path.stem.split("_", 3)
        if perspective not in OFFLINE_PERSPECTIVES:
            skipped += 1
            continue

        country = by_market.get(market_code)
        match = universe[(universe["국가"] == country) & (universe["종목코드"] == code)]
        if match.empty:
            skipped += 1
            continue
        row = match.iloc[0]

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 워밍이 도는 중에 같이 돌리면 막 쓰이는 중인 파일을 읽을 수 있다
            skipped += 1
            continue
        old = data.get("검증")
        if not old:
            skipped += 1
            continue

        peers = peer.sector_stats(universe, row.get("업종_소분류"), row)
        # 개요는 받아 둔 것을 캐시에서 꺼낸다. 네트워크를 다시 타지 않는다.
        overview = overviews.get(f"{country}:{code}")
        new = keep_confirmed(old, verify.verify(data["리포트"], row, peers, overview=overview))

        total += 1
        before_pass += bool(old["통과"])
        after_pass += bool(new["통과"])

        if new["대조율"] == old["대조율"] and new["통과"] == old["통과"]:
            continue
        if new["대조율"] > old["대조율"]:
            improved += 1
        else:
            worsened += 1
        changed.append((path.name, old, new))

        if args.write:
            data["검증"] = new
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"대상 {total}건 (건너뜀 {skipped}건)")
    print(f"통과 {before_pass}건 → {after_pass}건")
    print(f"달라진 것 {len(changed)}건 (좋아짐 {improved} · 나빠짐 {worsened})")

    for name, old, new in changed[:15]:
        gone = [u["표기"] for u in old["미확인"] if u not in new["미확인"]]
        print(f"  {name}: {old['대조율']}% → {new['대조율']}%  해소: {', '.join(gone) or '-'}")
    if len(changed) > 15:
        print(f"  ... 외 {len(changed) - 15}건")

    if worsened:
        print("\n나빠진 것이 있습니다. 검증기가 출처를 잃은 것은 아닌지 확인하세요.")
    if changed and not args.write:
        print("\n반영하려면: python reverify.py --write")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
