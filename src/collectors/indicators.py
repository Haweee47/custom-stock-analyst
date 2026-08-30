"""주가 보조지표 계산.

지표는 코드가 계산하고 AI에게는 해석만 맡긴다. AI에게 숫자를 세게 하면
틀리기 때문이다. 각 지표는 값과 함께 '어떤 상태인지'를 문자열로 함께 돌려주어
AI가 수치를 잘못 읽는 여지를 줄인다.
"""
import pandas as pd


def _last(series: pd.Series):
    value = series.dropna()
    return None if value.empty else value.iloc[-1]


def _round(value, digits: int = 0):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits) if digits else int(round(float(value)))


def moving_averages(close: pd.Series, price: float) -> dict:
    """이동평균과 정배열/역배열 여부."""
    out = {}
    values = {}
    for window in (5, 20, 60, 120):
        if len(close) >= window:
            ma = _last(close.rolling(window).mean())
            values[window] = ma
            out[f"{window}일선"] = _round(ma)
            out[f"{window}일선_대비"] = f"{(price / ma - 1) * 100:+.1f}%"

    if {5, 20, 60} <= values.keys():
        short, mid, long = values[5], values[20], values[60]
        if short > mid > long:
            out["배열"] = "정배열 (5>20>60, 상승 추세 형태)"
        elif short < mid < long:
            out["배열"] = "역배열 (5<20<60, 하락 추세 형태)"
        else:
            out["배열"] = "혼조 (이동평균이 엇갈림)"
    return out


def rsi(close: pd.Series, period: int = 14) -> dict:
    """상승폭과 하락폭의 비율. 통상 70 이상 과매수, 30 이하 과매도로 본다."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    last_gain, last_loss = _last(gain), _last(loss)
    if last_gain is None or last_loss is None:
        return {}
    if last_loss == 0:
        # 기간 내내 하락이 없으면 RSI는 정의상 100이다
        value = 100.0 if last_gain > 0 else 50.0
    else:
        value = 100 - 100 / (1 + last_gain / last_loss)
    state = "과매수 구간" if value >= 70 else "과매도 구간" if value <= 30 else "중립 구간"
    return {"RSI(14)": _round(value, 1), "RSI_상태": state}


def macd(close: pd.Series) -> dict:
    """단기·장기 지수이동평균의 차이. 시그널선과의 교차로 추세 전환을 본다."""
    if len(close) < 35:
        return {}
    line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = line.ewm(span=9, adjust=False).mean()
    histogram = line - signal

    now, before = _last(histogram), histogram.dropna().iloc[-2] if len(histogram.dropna()) > 1 else None
    if now is None:
        return {}
    if before is not None and now > 0 >= before:
        state = "골든크로스 발생 (MACD가 시그널선을 상향 돌파)"
    elif before is not None and now < 0 <= before:
        state = "데드크로스 발생 (MACD가 시그널선을 하향 돌파)"
    else:
        state = "MACD가 시그널선 위" if now > 0 else "MACD가 시그널선 아래"
    return {
        "MACD": _round(_last(line)),
        "MACD_시그널": _round(_last(signal)),
        "MACD_히스토그램": _round(now),
        "MACD_상태": state,
    }


def bollinger(close: pd.Series, price: float, window: int = 20) -> dict:
    """이동평균 ±2표준편차. 밴드 폭은 변동성, %B는 밴드 내 위치를 뜻한다."""
    if len(close) < window:
        return {}
    middle = close.rolling(window).mean()
    deviation = close.rolling(window).std()
    upper, lower = _last(middle + 2 * deviation), _last(middle - 2 * deviation)
    center = _last(middle)
    if upper is None or lower is None or upper == lower:
        return {}

    percent_b = (price - lower) / (upper - lower) * 100
    if price > upper:
        state = "상단 밴드 이탈 (단기 과열 신호)"
    elif price < lower:
        state = "하단 밴드 이탈 (단기 과매도 신호)"
    else:
        state = "밴드 내부"
    return {
        "볼린저_상단": _round(upper),
        "볼린저_중심": _round(center),
        "볼린저_하단": _round(lower),
        "볼린저_%B": _round(percent_b, 1),
        "볼린저_폭": f"{(upper - lower) / center * 100:.1f}%",
        "볼린저_상태": state,
    }


def stochastic(df: pd.DataFrame, period: int = 14) -> dict:
    """최근 고저 범위에서 종가의 위치. 80 이상 과매수, 20 이하 과매도로 본다."""
    if len(df) < period + 3:
        return {}
    low = df["저가"].rolling(period).min()
    high = df["고가"].rolling(period).max()
    k = (df["종가"] - low) / (high - low) * 100
    d = k.rolling(3).mean()
    k_value, d_value = _last(k), _last(d)
    if k_value is None:
        return {}
    state = "과매수 구간" if k_value >= 80 else "과매도 구간" if k_value <= 20 else "중립 구간"
    return {"스토캐스틱_%K": _round(k_value, 1), "스토캐스틱_%D": _round(d_value, 1),
            "스토캐스틱_상태": state}


def ichimoku(df: pd.DataFrame, price: float) -> dict:
    """일목균형표. 구름대(선행스팬1·2 사이)와 주가의 위치가 핵심이다.

    선행스팬은 26일 앞으로 그리는 지표이므로, 오늘 자리의 구름은
    26일 전에 계산된 값이다. shift(26)으로 그 값을 가져온다.
    """
    if len(df) < 78:
        return {}
    high, low = df["고가"], df["저가"]

    def mid(window: int) -> pd.Series:
        return (high.rolling(window).max() + low.rolling(window).min()) / 2

    conversion, base = mid(9), mid(26)
    span1 = ((conversion + base) / 2).shift(26)
    span2 = mid(52).shift(26)

    top, bottom = _last(span1), _last(span2)
    if top is None or bottom is None:
        return {}
    top, bottom = max(top, bottom), min(top, bottom)

    if price > top:
        cloud = "주가가 구름대 위 (강세 구간)"
    elif price < bottom:
        cloud = "주가가 구름대 아래 (약세 구간)"
    else:
        cloud = "주가가 구름대 안 (방향성 불분명)"

    conversion_value, base_value = _last(conversion), _last(base)
    if conversion_value and base_value:
        cross = "전환선이 기준선 위" if conversion_value > base_value else "전환선이 기준선 아래"
    else:
        cross = None

    return {
        "일목_전환선": _round(conversion_value),
        "일목_기준선": _round(base_value),
        "일목_선행스팬1": _round(_last(span1)),
        "일목_선행스팬2": _round(_last(span2)),
        "일목_구름대": f"{_round(bottom):,} ~ {_round(top):,}",
        "일목_위치": cloud,
        "일목_전환기준": cross,
    }


def volume_profile(df: pd.DataFrame) -> dict:
    """거래량이 평소 대비 얼마나 늘었는지. 추세의 힘을 가늠하는 데 쓴다."""
    volume = df["거래량"]
    if len(volume) < 20:
        return {}
    average = _last(volume.rolling(20).mean())
    if not average:
        return {}
    ratio = volume.iloc[-1] / average
    state = "거래량 급증" if ratio >= 2 else "거래량 증가" if ratio >= 1.2 else (
        "거래량 감소" if ratio <= 0.7 else "거래량 평이"
    )
    return {
        "거래량": int(volume.iloc[-1]),
        "거래량_20일평균": _round(average),
        "거래량_배수": _round(ratio, 2),
        "거래량_상태": state,
    }
