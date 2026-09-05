"""지표를 얹은 주가 차트.

숫자만 나열하면 "20일선 위, 구름대 아래"가 어떤 그림인지 알 수 없다.
밴드와 구름대를 칠하고, 교차·고저점·거래량 급증일을 표시해 눈으로 읽히게 한다.
"""
import pandas as pd

from src.analysis.money import unit_of as money_unit

ACCENT = "#12386b"
UP = "#c0392b"
DOWN = "#1f5fa8"
MA20 = "#e08a1e"
MA60 = "#7a5bb5"
CLOUD_UP = "rgba(192,57,43,0.10)"
CLOUD_DOWN = "rgba(31,95,168,0.10)"
BAND = "rgba(18,56,107,0.06)"
GRID = "#edeff2"
MUTED = "#6e7480"


def build_overlays(df: pd.DataFrame) -> pd.DataFrame:
    """차트에 그릴 보조지표 계열을 한 표로 계산한다."""
    out = df.copy()
    close = out["종가"]

    out["MA20"] = close.rolling(20).mean()
    out["MA60"] = close.rolling(60).mean()

    deviation = close.rolling(20).std()
    out["BB상단"] = out["MA20"] + 2 * deviation
    out["BB하단"] = out["MA20"] - 2 * deviation

    high, low = out["고가"], out["저가"]

    def mid(window: int) -> pd.Series:
        return (high.rolling(window).max() + low.rolling(window).min()) / 2

    conversion, base = mid(9), mid(26)
    out["전환선"] = conversion
    out["기준선"] = base
    out["선행1"] = ((conversion + base) / 2).shift(26)
    out["선행2"] = mid(52).shift(26)

    exp12 = close.ewm(span=12, adjust=False).mean()
    exp26 = close.ewm(span=26, adjust=False).mean()
    out["MACD"] = exp12 - exp26
    out["시그널"] = out["MACD"].ewm(span=9, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    out["RSI"] = 100 - 100 / (1 + gain / loss)

    out["거래량평균"] = out["거래량"].rolling(20).mean()
    return out


def find_events(df: pd.DataFrame) -> list[dict]:
    """차트에 표시할 중요 시점을 찾는다."""
    events = []

    peak = df.loc[df["종가"].idxmax()]
    trough = df.loc[df["종가"].idxmin()]
    events.append({"일자": peak["일자"], "값": peak["종가"], "종류": "고점", "설명": "기간 최고가"})
    events.append({"일자": trough["일자"], "값": trough["종가"], "종류": "저점", "설명": "기간 최저가"})

    # MACD가 시그널선을 지나는 지점 = 추세 전환 후보
    diff = (df["MACD"] - df["시그널"]).dropna()
    crossings = diff * diff.shift(1) < 0
    for index in diff[crossings].index[-4:]:
        row = df.loc[index]
        golden = diff.loc[index] > 0
        events.append(
            {
                "일자": row["일자"],
                "값": row["종가"],
                "종류": "골든크로스" if golden else "데드크로스",
                "설명": "MACD 상향 돌파" if golden else "MACD 하향 돌파",
            }
        )

    # 거래량이 평소의 3배를 넘은 날은 무언가 있었던 날이다
    spikes = df[df["거래량"] > df["거래량평균"] * 3].dropna(subset=["거래량평균"])
    for _, row in spikes.tail(3).iterrows():
        events.append(
            {
                "일자": row["일자"],
                "값": row["종가"],
                "종류": "거래량 급증",
                "설명": f"20일 평균의 {row['거래량'] / row['거래량평균']:.1f}배",
            }
        )
    return events


def plotly_chart(df: pd.DataFrame, currency: str = "KRW"):
    """웹 화면용 3단 차트: 주가+지표 / 거래량 / RSI."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    data = build_overlays(df)
    events = find_events(data)

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.62, 0.19, 0.19],
    )

    # 일목 구름대 - 선행스팬1이 위면 양운(붉은빛), 아래면 음운(푸른빛)
    fig.add_trace(
        go.Scatter(x=data["일자"], y=data["선행2"], line=dict(width=0),
                   showlegend=False, hoverinfo="skip"), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=data["일자"], y=data["선행1"], line=dict(width=0), fill="tonexty",
                   fillcolor=CLOUD_UP, name="일목 구름대", hoverinfo="skip"), row=1, col=1)

    # 볼린저밴드
    fig.add_trace(
        go.Scatter(x=data["일자"], y=data["BB상단"], line=dict(width=0),
                   showlegend=False, hoverinfo="skip"), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=data["일자"], y=data["BB하단"], line=dict(width=0), fill="tonexty",
                   fillcolor=BAND, name="볼린저밴드", hoverinfo="skip"), row=1, col=1)

    for column, color, name, dash in [
        ("MA60", MA60, "60일선", "dot"),
        ("MA20", MA20, "20일선", None),
    ]:
        fig.add_trace(
            go.Scatter(x=data["일자"], y=data[column], name=name,
                       line=dict(color=color, width=1.2, dash=dash),
                       hovertemplate="%{y:,.0f}<extra>" + name + "</extra>"), row=1, col=1)

    fig.add_trace(
        go.Scatter(x=data["일자"], y=data["종가"], name="종가",
                   line=dict(color=ACCENT, width=1.9),
                   hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f}원<extra></extra>"), row=1, col=1)

    marker_style = {
        "고점": (UP, "triangle-up"),
        "저점": (DOWN, "triangle-down"),
        "골든크로스": (UP, "circle"),
        "데드크로스": (DOWN, "circle"),
        "거래량 급증": (MA20, "diamond"),
    }
    for kind in marker_style:
        picked = [e for e in events if e["종류"] == kind]
        if not picked:
            continue
        color, symbol = marker_style[kind]
        fig.add_trace(
            go.Scatter(
                x=[e["일자"] for e in picked], y=[e["값"] for e in picked],
                mode="markers", name=kind,
                marker=dict(color=color, symbol=symbol, size=10,
                            line=dict(color="#fff", width=1.5)),
                customdata=[e["설명"] for e in picked],
                hovertemplate="%{x|%Y-%m-%d}<br><b>" + kind + "</b><br>%{customdata}<extra></extra>",
            ), row=1, col=1)

    volume_colors = [
        MA20 if (pd.notna(avg) and volume > avg * 3) else "#c8ccd4"
        for volume, avg in zip(data["거래량"], data["거래량평균"])
    ]
    fig.add_trace(
        go.Bar(x=data["일자"], y=data["거래량"], marker_color=volume_colors,
               name="거래량", hovertemplate="%{y:,.0f}주<extra>거래량</extra>"), row=2, col=1)

    fig.add_trace(
        go.Scatter(x=data["일자"], y=data["RSI"], name="RSI(14)",
                   line=dict(color=ACCENT, width=1.3),
                   hovertemplate="RSI %{y:.1f}<extra></extra>"), row=3, col=1)
    for level, label in [(70, "과매수"), (30, "과매도")]:
        fig.add_hline(y=level, line=dict(color=MUTED, width=0.8, dash="dot"),
                      annotation_text=label, annotation_font_size=9,
                      annotation_font_color=MUTED, row=3, col=1)

    fig.update_layout(
        height=620,
        margin=dict(l=10, r=10, t=34, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=MUTED, size=11),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.06, x=0, font=dict(size=10)),
        bargap=0.1,
    )
    for row_index in (1, 2, 3):
        fig.update_xaxes(showgrid=False, zeroline=False, row=row_index, col=1)
        fig.update_yaxes(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False,
                         row=row_index, col=1)
    fig.update_yaxes(title_text=money_unit(currency), title_font_size=10, row=1, col=1)
    fig.update_yaxes(title_text="거래량", title_font_size=10, row=2, col=1)
    fig.update_yaxes(title_text="RSI", title_font_size=10, range=[0, 100], row=3, col=1)
    return fig, events
