"""동종업계(업종 소분류) 비교 통계.

절대 수치만으로는 좋은지 나쁜지 알 수 없다. 영업이익률 13%가 훌륭한 숫자인지는
같은 업종이 몇 %를 버는지를 알아야 판단이 선다. 그래서 리포트에 업종 중앙값을
나란히 놓는다.

이미 수집해 둔 2,655종목 재무로 계산하므로 추가 수집도, API 비용도 들지 않는다.
"""
import pandas as pd

# (지표, 표시 단위, 높을수록 좋은가)
# PER은 None이다. 낮으면 저평가일 수도, 시장이 성장을 기대하지 않는 것일 수도 있어
# 우열을 매길 수 없다. 중앙값만 나란히 보여주고 해석은 하지 않는다.
METRICS = [
    ("영업이익률", "%", True),
    ("ROE_계산", "%", True),
    ("ROA", "%", True),
    ("부채비율", "%", False),
    ("PER", "배", None),
    ("PBR", "배", None),
]

LABELS = {"ROE_계산": "ROE"}

# 낮다고 좋은 것도 높다고 나쁜 것도 아닌 지표
MEDIAN_ONLY = {"PER", "PBR"}

# 표본이 너무 적으면 중앙값이 대표성을 잃는다
MIN_PEERS = 5


def _label(metric: str) -> str:
    return LABELS.get(metric, metric)


def _clean(series: pd.Series, metric: str) -> pd.Series:
    """비교를 왜곡하는 값을 뺀다."""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if metric in ("PER", "PBR"):
        # 적자 기업의 음수 배수와 극단적 고배수는 중앙값을 흔든다
        values = values[(values > 0) & (values < 200)]
    elif metric == "부채비율":
        # 완전자본잠식이면 음수가 나온다
        values = values[values >= 0]
    return values


def percentile(values: pd.Series, value: float, higher_is_better: bool) -> float:
    """전체에서 몇 % 지점에 있는지. 항상 '클수록 우수'가 되도록 방향을 맞춘다."""
    rank = (values < value).mean() * 100
    return rank if higher_is_better else 100 - rank


def _median_only(metric: str) -> bool:
    """우열을 매길 수 없는 지표는 중앙값만 보여준다."""
    return any(name == metric and direction is None for name, _, direction in METRICS)


def same_market(universe: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    """비교 모집단을 같은 나라로 좁힌다.

    회계 기준도 업종 분류 체계도 다르므로 국내와 해외를 한 줄에 세우면
    중앙값이 뜻을 잃는다. '반도체'라는 이름이 같아도 같은 모집단이 아니다.
    """
    country = row.get("국가")
    if not country or "국가" not in universe.columns:
        return universe
    return universe[universe["국가"] == country]


def sector_stats(universe: pd.DataFrame, sector: str, row: pd.Series) -> dict | None:
    """한 종목을 같은 시장·같은 업종 소분류와 비교한다. 표본이 모자라면 None."""
    if not sector or sector == "미분류" or "업종_소분류" not in universe.columns:
        return None

    universe = same_market(universe, row)
    peers = universe[universe["업종_소분류"] == sector]
    if len(peers) < MIN_PEERS:
        return None

    stats: dict[str, dict] = {}
    for metric, unit, higher_is_better in METRICS:
        if metric not in peers.columns:
            continue
        values = _clean(peers[metric], metric)
        mine = pd.to_numeric(pd.Series([row.get(metric)]), errors="coerce").iloc[0]
        if len(values) < MIN_PEERS or pd.isna(mine):
            continue
        stats[_label(metric)] = {
            "값": float(mine),
            "중앙값": float(values.median()),
            "백분위": (
                None
                if higher_is_better is None
                else round(percentile(values, float(mine), higher_is_better))
            ),
            "단위": unit,
            "표본": int(len(values)),
        }

    if not stats:
        return None
    return {"업종": sector, "종목수": int(len(peers)), "지표": stats}


def cap_rank(universe: pd.DataFrame, sector: str, stock_code: str) -> tuple[int, int] | None:
    """업종 내 시가총액 순위. 대장주인지 소형주인지가 리포트의 톤을 좌우한다."""
    if "시가총액" not in universe.columns:
        return None
    peers = universe[universe["업종_소분류"] == sector].dropna(subset=["시가총액"])
    if len(peers) < MIN_PEERS or stock_code not in set(peers["종목코드"]):
        return None
    ordered = peers.sort_values("시가총액", ascending=False).reset_index(drop=True)
    rank = int(ordered.index[ordered["종목코드"] == stock_code][0]) + 1
    return rank, len(ordered)


def peer_block(row: pd.Series, universe: pd.DataFrame) -> str:
    """프롬프트에 넣을 동종업계 비교 텍스트."""
    sector = row.get("업종_소분류")
    stats = sector_stats(universe, sector, row)
    if stats is None:
        return "[동종업계 비교]\n- 같은 업종의 비교 표본이 충분하지 않아 제공하지 않음"

    lines = []
    rank = cap_rank(same_market(universe, row), sector, row.get("종목코드"))
    if rank:
        lines.append(f"- 업종 내 시가총액 순위: {stats['종목수']}개 중 {rank[0]}위")

    for name, data in stats["지표"].items():
        unit = data["단위"]
        line = (
            f"- {name}: 이 회사 {data['값']:,.2f}{unit} / "
            f"업종 중앙값 {data['중앙값']:,.2f}{unit}"
        )
        if data["백분위"] is not None:
            line += f" (업종 내 상위 {100 - data['백분위']:.0f}%)"
        lines.append(line)

    return (
        f"[동종업계 비교 — {sector} ({stats['종목수']}개 종목)]\n"
        + "\n".join(lines)
        + "\n(중앙값은 같은 업종 상장사의 가운데 값이다. '상위 N%'는 작을수록 우수하다. "
        "PER은 낮다고 좋은 것도 높다고 나쁜 것도 아니므로 순위를 매기지 않는다.)"
    )
