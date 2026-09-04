"""재무 특성으로 종목을 걸러내는 조건들.

이미 수집해 둔 3개년 재무만으로 계산하므로 추가 수집이 필요 없다.
각 조건은 (설명, 판정함수) 형태이며, 판정함수는 불리언 Series를 돌려준다.
"""
import pandas as pd


def _has(df: pd.DataFrame, *columns: str) -> bool:
    return all(column in df.columns for column in columns)


def _profitable(df: pd.DataFrame) -> pd.Series:
    return df["영업이익"] > 0


def _low_per(df: pd.DataFrame) -> pd.Series:
    # PER은 적자면 음수로 나오므로 0 초과 조건을 함께 건다
    return (df["PER"] > 0) & (df["PER"] < 10)


def _high_roe(df: pd.DataFrame) -> pd.Series:
    if not _has(df, "ROE_계산"):
        return pd.Series(False, index=df.index)
    return df["ROE_계산"] >= 15


def _low_debt(df: pd.DataFrame) -> pd.Series:
    if not _has(df, "부채비율"):
        return pd.Series(False, index=df.index)
    return (df["부채비율"] > 0) & (df["부채비율"] < 100)


def _high_growth(df: pd.DataFrame) -> pd.Series:
    if not _has(df, "매출액_전기"):
        return pd.Series(False, index=df.index)
    previous = df["매출액_전기"]
    return (previous > 0) & (df["매출액"] / previous - 1 >= 0.20)


def _turnaround(df: pd.DataFrame) -> pd.Series:
    """전기 영업적자에서 당기 흑자로 돌아선 기업."""
    if not _has(df, "영업이익_전기"):
        return pd.Series(False, index=df.index)
    return (df["영업이익_전기"] < 0) & (df["영업이익"] > 0)


def _margin_improving(df: pd.DataFrame) -> pd.Series:
    """영업이익률이 전년보다 개선된 기업."""
    if not _has(df, "영업이익_전기", "매출액_전기"):
        return pd.Series(False, index=df.index)
    now = df["영업이익"] / df["매출액"]
    before = df["영업이익_전기"] / df["매출액_전기"]
    return (df["매출액"] > 0) & (df["매출액_전기"] > 0) & (now > before)


SCREENS = {
    "흑자 기업": ("영업이익이 0보다 큰 기업", _profitable),
    "저PER (10배 미만)": ("이익 대비 주가가 낮은 기업", _low_per),
    "고ROE (15% 이상)": ("자기자본으로 이익을 잘 내는 기업", _high_roe),
    "저부채 (100% 미만)": ("부채비율이 낮아 재무가 탄탄한 기업", _low_debt),
    "고성장 (매출 +20%)": ("매출이 전년 대비 20% 이상 늘어난 기업", _high_growth),
    "턴어라운드": ("전년 영업적자에서 흑자로 돌아선 기업", _turnaround),
    "수익성 개선": ("영업이익률이 전년보다 좋아진 기업", _margin_improving),
}


# 조건마다 필요한 열. 해외 종목은 자본총계·부채총계가 없어 ROE와 부채비율을
# 구할 수 없다. 고를 수는 있는데 결과가 늘 0건이면 이유를 알 수 없으므로,
# 판정할 수 있는 조건만 화면에 올린다.
REQUIRES = {
    "흑자 기업": ["영업이익"],
    "저PER (10배 미만)": ["PER"],
    "고ROE (15% 이상)": ["ROE_계산"],
    "저부채 (100% 미만)": ["부채비율"],
    "고성장 (매출 +20%)": ["매출액", "매출액_전기"],
    "턴어라운드": ["영업이익", "영업이익_전기"],
    "수익성 개선": ["영업이익", "매출액", "영업이익_전기", "매출액_전기"],
}


def available_screens(df: pd.DataFrame) -> list[str]:
    """이 표에서 실제로 판정할 수 있는 조건만 돌려준다.

    열이 아예 없거나 전부 결측이면 뺀다. 값이 하나도 없는 조건을 보여주면
    이용자는 '0건'만 보고 왜 그런지 알 수 없다.
    """
    usable = []
    for name, columns in REQUIRES.items():
        if all(column in df.columns and df[column].notna().any() for column in columns):
            usable.append(name)
    return usable


def apply_screens(df: pd.DataFrame, selected: list[str]) -> pd.DataFrame:
    """선택한 조건을 모두 만족하는 종목만 남긴다."""
    result = df
    for name in selected:
        _, test = SCREENS[name]
        result = result[test(result).fillna(False)]
    return result


def screen_counts(df: pd.DataFrame) -> dict[str, int]:
    """각 조건에 해당하는 종목 수. 필터를 고르기 전에 규모를 보여준다."""
    return {name: int(test(df).fillna(False).sum()) for name, (_, test) in SCREENS.items()}
