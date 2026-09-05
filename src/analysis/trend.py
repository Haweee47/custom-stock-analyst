"""매출과 이익이 같이 움직이는지 계산한다.

'매출은 10% 늘었는데 영업이익은 33% 늘었다'는 문장은 단순한 숫자 나열이 아니라
회사를 읽는 핵심이다. 이익이 매출보다 빠르게 늘면 마진이 좋아진 것이고, 매출은
느는데 이익이 줄면 비용이 더 빨리 늘어난 것이다.

모델에게 세 숫자를 주고 '알아서 보라'고 하면 자주 틀린다(실제로 '3년 연속 감소'
같은 오독을 겪었다). 그래서 여기서 계산해 결론까지 만들어 주고, 모델은 그것을
문장으로 풀기만 하게 한다.

영업이익 변화를 두 갈래로 나누는 방법:
    영업이익 = 매출 × 마진
    ΔOP = 마진(전) × Δ매출  +  매출(당) × Δ마진
         └ 매출이 늘어서 생긴 몫    └ 마진이 좋아져서 생긴 몫
DART 주요계정에는 매출원가·판관비가 없어 비용 항목까지는 못 쪼갠다.
'왜' 마진이 변했는지가 아니라 '얼마나' 기여했는지까지가 이 데이터의 한계다.
"""
import pandas as pd

# 영업레버리지를 말할 수 있는 최소 매출 변화율(%). 매출이 거의 안 움직였는데
# 배수를 계산하면 0으로 나누는 것과 다름없는 숫자가 나온다.
MIN_SALES_CHANGE = 0.5

# 마진 변화가 이 정도(%p) 미만이면 '제자리'로 본다
FLAT_MARGIN = 0.3


def _value(row: pd.Series, name: str):
    value = row.get(name)
    return None if value is None or pd.isna(value) else float(value)


def _rate(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def _margin(profit, sales):
    if profit is None or sales is None or sales <= 0:
        return None
    return profit / sales * 100


def _direction(rate) -> str:
    if rate is None:
        return "알 수 없음"
    if rate > 1:
        return "증가"
    if rate < -1:
        return "감소"
    return "제자리"


def compare(row: pd.Series, current_suffix: str = "", previous_suffix: str = "_전기") -> dict | None:
    """두 해를 놓고 매출과 영업이익이 어떻게 함께 움직였는지 계산한다."""
    sales_now = _value(row, f"매출액{current_suffix}")
    sales_before = _value(row, f"매출액{previous_suffix}")
    profit_now = _value(row, f"영업이익{current_suffix}")
    profit_before = _value(row, f"영업이익{previous_suffix}")

    if None in (sales_now, sales_before, profit_now, profit_before):
        return None
    if sales_now <= 0 or sales_before <= 0:
        return None

    sales_rate = _rate(sales_now, sales_before)
    profit_rate = _rate(profit_now, profit_before)
    margin_now = _margin(profit_now, sales_now)
    margin_before = _margin(profit_before, sales_before)
    margin_change = margin_now - margin_before

    # 이익 변화를 매출 몫과 마진 몫으로 나눈다. 둘을 더하면 실제 변화와 같다.
    sales_effect = (margin_before / 100) * (sales_now - sales_before)
    margin_effect = sales_now * (margin_change / 100)

    # 배수는 두 증감률이 같은 방향일 때만 뜻이 있다. 매출은 늘고 이익은 줄었는데
    # '-3.9배'라고 적으면 읽는 사람이 해석할 수 없다. 적자가 끼어도 마찬가지다.
    both_positive = profit_now > 0 and profit_before > 0
    same_way = sales_rate is not None and profit_rate is not None and (
        (sales_rate >= 0) == (profit_rate >= 0)
    )
    leverage = None
    if both_positive and same_way and abs(sales_rate) >= MIN_SALES_CHANGE:
        leverage = profit_rate / sales_rate

    return {
        "매출_증감률": sales_rate,
        "영업이익_증감률": profit_rate,
        "매출_방향": _direction(sales_rate),
        "영업이익_방향": _direction(profit_rate),
        "영업이익률_전": margin_before,
        "영업이익률_당": margin_now,
        "영업이익률_변화": margin_change,
        "매출효과": sales_effect,
        "마진효과": margin_effect,
        "실제변화": profit_now - profit_before,
        "레버리지": leverage,
        "적자포함": not both_positive,
        "판정": verdict(sales_rate, profit_rate, margin_change, leverage),
    }


def verdict(sales_rate, profit_rate, margin_change, leverage) -> str:
    """한 줄 결론. 모델이 방향을 잘못 읽지 않도록 여기서 못 박는다."""
    if sales_rate is None or profit_rate is None:
        return "판단할 데이터가 부족하다"

    same_way = (sales_rate >= 0) == (profit_rate >= 0)
    margin_word = (
        "마진 개선"
        if margin_change > FLAT_MARGIN
        else "마진 악화"
        if margin_change < -FLAT_MARGIN
        else "마진 제자리"
    )

    if not same_way:
        if sales_rate > 0:
            return f"매출은 늘었는데 영업이익은 줄었다 ({margin_word}). 비용이 매출보다 빨리 늘었다"
        return f"매출은 줄었는데 영업이익은 늘었다 ({margin_word}). 비용을 줄여 방어했다"

    # 둘 다 줄어든 경우와 둘 다 늘어난 경우는 같은 배수라도 읽는 맛이 다르다
    growing = sales_rate >= 0
    if leverage is not None and leverage > 1.2:
        if growing:
            return f"영업이익이 매출보다 빠르게 늘었다 (증감률 {leverage:.1f}배, {margin_word})"
        return f"매출보다 영업이익이 훨씬 크게 줄었다 (감소폭 {leverage:.1f}배, {margin_word})"
    if leverage is not None and leverage < 0.8:
        if growing:
            return f"매출은 늘었지만 영업이익 증가폭이 그에 못 미쳤다 ({margin_word})"
        return f"매출은 줄었지만 영업이익은 덜 줄었다 ({margin_word})"
    return f"매출과 영업이익이 비슷한 폭으로 움직였다 ({margin_word})"


def cost_split(row: pd.Series, current_suffix: str = "", previous_suffix: str = "_전기") -> dict | None:
    """마진 변화를 원가율과 판관비율로 쪼갠다.

        영업이익률 = 100% - 원가율 - 판관비율

    이걸로 '마진이 좋아졌다'가 아니라 '원가율이 내려가서 좋아졌다'까지 말할 수 있다.
    다만 원가율이 왜 내려갔는지(단가·물량·환율)는 사업보고서 본문을 읽어야 알 수 있고,
    이 데이터로는 알 수 없다. 여기서 멈추는 것이 정직하다.

    국내만 가능하다. 해외(네이버)는 원가 항목을 주지 않는다.
    """
    sales_now = _value(row, f"매출액{current_suffix}")
    sales_before = _value(row, f"매출액{previous_suffix}")
    if sales_now is None or sales_before is None or sales_now <= 0 or sales_before <= 0:
        return None

    parts = {}
    for name, label in [("매출원가", "원가율"), ("판매비와관리비", "판관비율")]:
        now = _value(row, f"{name}{current_suffix}")
        before = _value(row, f"{name}{previous_suffix}")
        if now is None or before is None:
            continue
        ratio_now = now / sales_now * 100
        ratio_before = before / sales_before * 100
        parts[label] = {
            "전": ratio_before,
            "당": ratio_now,
            "변화": ratio_now - ratio_before,
        }

    return parts or None


def cost_verdict(parts: dict) -> str:
    """마진이 왜 움직였는지 한 줄로. 비율이 내려가면 이익에 보탬이다."""
    contributions = []
    for label, data in parts.items():
        change = data["변화"]
        if abs(change) < 0.1:
            continue
        # 원가율·판관비율이 내려가면 마진은 올라간다(부호가 뒤집힌다)
        effect = "개선" if change < 0 else "악화"
        contributions.append(f"{label} {change:+.2f}%p({effect} 요인)")

    if not contributions:
        return "원가율과 판관비율 모두 큰 변화가 없다"
    return " · ".join(contributions)


def margin_position(row: pd.Series, peers: dict | None) -> str | None:
    """영업이익률이 업종에서 어디쯤인지. '왜 낮은가'의 출발점이다."""
    if not peers:
        return None
    data = (peers.get("지표") or {}).get("영업이익률")
    if not data:
        return None

    mine, median = data.get("값"), data.get("중앙값")
    if mine is None or median is None:
        return None

    if median == 0:
        return f"업종 중앙값이 0%라 배수로 비교할 수 없다 (이 회사 {mine:.2f}%)"
    if median < 0 < mine:
        return f"업종 중앙값은 적자({median:.2f}%)인데 이 회사는 {mine:.2f}%로 흑자다"

    gap = mine - median
    word = "높다" if gap > 0 else "낮다"
    return (
        f"영업이익률 {mine:.2f}%는 업종 중앙값 {median:.2f}%보다 "
        f"{abs(gap):.2f}%p {word} (중앙값의 {mine / median:.1f}배)"
    )


def block(row: pd.Series, peers: dict | None = None) -> str:
    """프롬프트에 넣을 텍스트. 계산은 여기서 끝내고 모델은 풀어 쓰기만 한다."""
    from src.analysis.money import money

    currency = row.get("통화")
    currency = "KRW" if currency is None or pd.isna(currency) else str(currency)

    recent = compare(row)
    if recent is None:
        return ""

    base = row.get("기준연도")
    base = int(base) if base is not None and not pd.isna(base) else None
    span = f"{base - 1}년 → {base}년" if base else "전년 → 당해"

    lines = [
        f"- 매출액 {recent['매출_증감률']:+.1f}%, 영업이익 {recent['영업이익_증감률']:+.1f}%",
        f"- 영업이익률 {recent['영업이익률_전']:.2f}% → {recent['영업이익률_당']:.2f}% "
        f"({recent['영업이익률_변화']:+.2f}%p)",
    ]

    if recent["레버리지"] is not None:
        lines.append(
            f"- 영업이익 증감률은 매출 증감률의 {recent['레버리지']:.1f}배"
        )

    if not recent["적자포함"]:
        lines.append(
            f"- 영업이익 변화 {money(recent['실제변화'], currency)}의 내역: "
            f"매출이 늘어서 {money(recent['매출효과'], currency)}, "
            f"마진이 바뀌어서 {money(recent['마진효과'], currency)}"
        )

    # 마진이 왜 움직였는지. 국내만 원가 항목이 있다.
    parts = cost_split(row)
    if parts:
        detail = " / ".join(
            f"{label} {data['전']:.2f}% → {data['당']:.2f}% ({data['변화']:+.2f}%p)"
            for label, data in parts.items()
        )
        lines.append(f"- 마진 내역: {detail}")
        lines.append(f"- 마진이 움직인 이유: {cost_verdict(parts)}")

    lines.append(f"- 결론: {recent['판정']}")

    # 2년 전과도 비교해 한 해만의 변동인지 흐름인지 구분한다
    older = compare(row, current_suffix="_전기", previous_suffix="_전전기")
    if older:
        lines.append(
            f"- 그 전 해({base - 2}년 → {base - 1}년)는: {older['판정']}"
            if base
            else f"- 그 전 해는: {older['판정']}"
        )

    position = margin_position(row, peers)
    if position:
        lines.append(f"- 업종 대비: {position}")

    return (
        f"[매출과 이익의 연동 ({span})]\n"
        + "\n".join(lines)
        + "\n(이 수치와 결론은 계산된 값이다. 다시 계산하지 말고 그대로 인용해 서술하라. "
        "매출과 이익이 같은 방향으로 움직였는지, 폭이 달랐다면 왜 그런지를 반드시 다뤄라.)"
    )
