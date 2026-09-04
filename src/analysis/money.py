"""통화별 금액 표기.

리포트가 삼성전자 매출을 열 배로 부풀려 쓴 사고가 있었다. '3,336,059.38억원'처럼
자릿수가 긴 표기를 모델이 잘못 읽은 것이 원인이었고, 사람이 읽는 방식대로
'333조 6,059억원'으로 끊어 주니 사라졌다.

해외 종목이 들어오면 같은 함정이 통화만큼 늘어난다. 그래서 끊어 읽는 규칙은
하나로 두고 단위 이름만 바꾼다. 한국어 금융 기사도 달러를 '2,159억 달러'처럼
조·억으로 끊어 쓰므로 읽는 사람에게도 자연스럽다.
"""
import pandas as pd

UNITS = {
    "KRW": "원",
    "USD": "달러",
    "JPY": "엔",
    "CNY": "위안",
    "HKD": "홍콩달러",
}

# 소수점이 의미 있는 통화. 원·엔은 주가에 소수점을 쓰지 않는다.
DECIMAL_PRICES = {"USD", "CNY", "HKD"}


def unit_of(currency: str | None) -> str:
    return UNITS.get((currency or "KRW").upper(), currency or "")


def money(value, currency: str = "KRW", empty: str = "데이터 없음") -> str:
    """금액을 조·억으로 끊어 쓴다.

    1조 이상이면 '5조 5,056억 달러', 1억 이상이면 '2,159억 달러',
    그보다 작으면 끊지 않고 그대로 적는다.
    """
    if value is None or pd.isna(value):
        return empty

    unit = unit_of(currency)
    sign = "-" if value < 0 else ""
    amount = abs(float(value))
    trillion, remainder = divmod(amount, 1e12)
    billion = remainder / 1e8

    if trillion >= 1:
        return f"{sign}{trillion:,.0f}조 {billion:,.0f}억{unit}"
    if amount >= 1e8:
        return f"{sign}{billion:,.0f}억{unit}"
    return f"{sign}{amount:,.0f}{unit}"


def price(value, currency: str = "KRW", empty: str = "데이터 없음") -> str:
    """주가. 달러는 센트가 의미 있으므로 소수 둘째 자리까지 남긴다."""
    if value is None or pd.isna(value):
        return empty
    unit = unit_of(currency)
    if (currency or "KRW").upper() in DECIMAL_PRICES:
        return f"{value:,.2f}{unit}"
    return f"{value:,.0f}{unit}"


def growth(current, previous) -> str:
    """전년 대비 증감률. 적자에서 흑자로 돌아선 경우는 비율이 의미가 없다."""
    if current is None or previous is None or pd.isna(current) or pd.isna(previous):
        return ""
    if previous == 0:
        return ""
    if previous < 0 < current:
        return " (흑자 전환)"
    if current < 0 < previous:
        return " (적자 전환)"
    rate = (current - previous) / abs(previous) * 100
    return f" ({rate:+.1f}%)"
