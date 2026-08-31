"""자주 열릴 종목의 리포트를 미리 만들어 캐시에 채워 둔다.

배포 환경에서는 커밋된 캐시만이 진짜 캐시다. Streamlit Cloud는 앱이 잠들거나
재시작하면 실행 중 만든 파일을 지우기 때문에, 방문자가 만든 리포트는 얼마 못 가
사라진다. 그래서 시가총액 상위 종목만 미리 만들어 저장소에 넣어 둔다.

첫 화면이 비어 보이지 않게 하는 것이 목적이고, 부수 효과로 비용도 준다.
캐시에 있으면 방문자가 열어도 API를 호출하지 않기 때문이다.

    python warmup.py                    상위 30개, 앱 기본값(펀더멘탈·압축형)
    python warmup.py --top 50           상위 50개
    python warmup.py --view 종합        관점 지정
    python warmup.py --dry-run          쓸 돈만 계산하고 끝낸다

만든 뒤에는 커밋해야 배포에 반영된다.
"""
import argparse
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.analysis.gemini_analyzer import (  # noqa: E402
    ApiKeyMissing,
    analyze,
    gather_context,
    load_cached,
    load_universe,
)
from src.analysis.report_spec import LENGTHS, PERSPECTIVES  # noqa: E402
from src.analysis.usage_limit import DailyLimitReached, remaining_today  # noqa: E402

# 실측 단가(gemini-3.1-flash-lite). 백만 토큰당 달러, 환율 1,400원 가정.
INPUT_COST = 0.25
OUTPUT_COST = 1.50
EXCHANGE = 1400

# 프롬프트가 길어진 뒤의 실측 평균이다. 안내용 추정치로만 쓴다.
ESTIMATED_COST = 3.3


def cost_of(tokens: dict) -> float:
    return (
        tokens["입력"] / 1e6 * INPUT_COST + tokens["출력"] / 1e6 * OUTPUT_COST
    ) * EXCHANGE


def targets(top: int, view: str, size: str):
    """시가총액 상위 종목 중 아직 캐시가 없는 것만 고른다."""
    universe = load_universe()
    ranked = (
        universe.dropna(subset=["시가총액"])
        .sort_values("시가총액", ascending=False)
        .head(top)
    )

    todo, cached = [], 0
    for _, row in ranked.iterrows():
        if load_cached(row["종목코드"], view, size):
            cached += 1
        else:
            todo.append(row)
    return universe, todo, cached


def main() -> int:
    parser = argparse.ArgumentParser(description="리포트 캐시를 미리 채운다")
    parser.add_argument("--top", type=int, default=30, help="시총 상위 몇 개까지 (기본 30)")
    parser.add_argument(
        "--view", default=next(iter(PERSPECTIVES)), choices=list(PERSPECTIVES),
        help="분석 관점 (기본값은 앱에서 처음 선택되는 관점)",
    )
    parser.add_argument(
        "--size", default=next(iter(LENGTHS)), choices=list(LENGTHS), help="분량"
    )
    parser.add_argument("--dry-run", action="store_true", help="비용만 계산하고 끝낸다")
    args = parser.parse_args()

    print(f"캐시 워밍 — 시총 상위 {args.top}개 · {args.view} · {args.size}")

    universe, todo, cached = targets(args.top, args.view, args.size)
    print(f"이미 있음 {cached}건 / 만들 것 {len(todo)}건")

    if not todo:
        print("\n모두 채워져 있습니다. 할 일이 없습니다.")
        return 0

    left = remaining_today()
    if len(todo) > left:
        print(f"오늘 남은 생성 가능 건수가 {left}건이라 그만큼만 만듭니다.")
        todo = todo[:left]

    print(f"예상 비용 약 {len(todo) * ESTIMATED_COST:,.0f}원 ({len(todo)}건)")
    if args.dry_run:
        print("\n--dry-run이므로 실제로 만들지 않았습니다.")
        return 0

    made, spent, failed = 0, 0.0, []
    started = time.time()

    for index, row in enumerate(todo, start=1):
        label = f"{row['종목명']} ({row['종목코드']})"
        print(f"[{index}/{len(todo)}] {label} ... ", end="", flush=True)
        try:
            context = gather_context(row["종목코드"], args.view)
            # universe는 gather_context가 이미 넣어 주지만, 관점에 따라 빠질 수 있다
            context.setdefault("universe", universe)
            result = analyze(row, args.view, args.size, batch=True, **context)

            price = cost_of(result["토큰"]) if "토큰" in result else 0.0
            spent += price
            made += 1
            print(f"완료 ({price:.2f}원)")
        except DailyLimitReached as exc:
            print("중단")
            print(f"\n{exc}")
            break
        except ApiKeyMissing as exc:
            print("실패")
            print(f"\n{exc}")
            return 1
        except Exception as exc:
            print(f"실패 — {type(exc).__name__}: {exc}")
            failed.append(label)
            traceback.print_exc(limit=1)

    elapsed = time.time() - started
    print(f"\n{'=' * 56}")
    print(f"만든 리포트 {made}건 · 사용 금액 {spent:,.1f}원 · {elapsed:.0f}초")
    if failed:
        print(f"실패 {len(failed)}건: {', '.join(failed[:5])}")
    print(f"오늘 남은 생성 가능 건수 {remaining_today()}건")

    if made:
        print("\n배포에 반영하려면 커밋하세요:")
        print('  git add data/processed/analysis && git commit -m "chore: 리포트 캐시 워밍"')
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
