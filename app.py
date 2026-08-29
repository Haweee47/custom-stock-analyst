"""초소형주 맞춤형 AI 리포트 생성기 - Streamlit 웹앱."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.analysis.gemini_analyzer import (
    DAILY_LIMIT,
    DISCLAIMER,
    DailyLimitReached,
    _usage_today,
    analyze,
    load_cached,
    load_financials,
)

# 검증된 참조 팔레트 - 강조 1색 + 맥락용 중립 회색만 쓴다
ACCENT = "#2a78d6"
NEUTRAL = "#d0cfc9"
GRID = "#ebeae5"
TEXT_MUTED = "#52514e"

st.set_page_config(page_title="AI 종목 리포트", page_icon="📊", layout="wide")


@st.cache_data
def get_data() -> pd.DataFrame:
    return load_financials()


def stat_row(row: pd.Series) -> None:
    """단일 수치는 차트가 아니라 스탯 타일로 보여준다."""
    cols = st.columns(6)
    items = [
        ("현재가", row.get("현재가"), "{:,.0f}원"),
        ("시가총액", row.get("시가총액"), "{:,.0f}억"),
        ("PER", row.get("PER"), "{:,.2f}배"),
        ("부채비율", row.get("부채비율"), "{:,.2f}%"),
        ("영업이익률", row.get("영업이익률"), "{:,.2f}%"),
        ("ROE", row.get("ROE_계산"), "{:,.2f}%"),
    ]
    for col, (label, value, fmt) in zip(cols, items):
        if pd.isna(value):
            col.metric(label, "—")
        else:
            shown = value / 1e8 if label == "시가총액" else value
            col.metric(label, fmt.format(shown))


def profit_chart(row: pd.Series) -> go.Figure | None:
    labels = ["매출액", "영업이익", "당기순이익"]
    values = [row.get(k) for k in labels]
    if all(pd.isna(v) for v in values):
        return None

    billions = [None if pd.isna(v) else v / 1e8 for v in values]
    fig = go.Figure(
        go.Bar(
            x=billions,
            y=labels,
            orientation="h",
            marker_color=ACCENT,
            width=0.5,
            text=["" if v is None else f"{v:,.0f}억" for v in billions],
            textposition="outside",
            hovertemplate="%{y}: %{x:,.0f}억원<extra></extra>",
        )
    )
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=60, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_MUTED),
        xaxis=dict(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False, title=None),
        yaxis=dict(showgrid=False, autorange="reversed"),
        showlegend=False,
    )
    return fig


def distribution_chart(df: pd.DataFrame, row: pd.Series, metric: str) -> go.Figure | None:
    """전체 분포는 회색으로 깔고 해당 종목만 강조한다."""
    series = df[metric].dropna()
    value = row.get(metric)
    if series.empty or pd.isna(value):
        return None

    # 극단값이 있으면 분포가 한쪽으로 뭉치므로 1~99 백분위로 자른다
    low, high = series.quantile(0.01), series.quantile(0.99)
    trimmed = series[(series >= low) & (series <= high)]
    percentile = (series < value).mean() * 100

    fig = go.Figure(
        go.Histogram(x=trimmed, nbinsx=50, marker_color=NEUTRAL, hoverinfo="skip")
    )
    fig.add_vline(
        x=value,
        line_color=ACCENT,
        line_width=2,
        annotation_text=f"  {row['종목명']} {value:,.1f} (상위 {100 - percentile:.0f}%)",
        annotation_position="top",
        annotation_font_color=ACCENT,
    )
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=40, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_MUTED),
        xaxis=dict(title=metric, showgrid=False, zeroline=False),
        yaxis=dict(title="종목 수", showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False),
        bargap=0.02,
        showlegend=False,
    )
    return fig


def render_analysis(result: dict) -> None:
    a = result["분석"]
    st.markdown(f"**요약** — {a['요약']}")

    left, right = st.columns(2)
    with left:
        st.markdown("**재무 강점**")
        for item in a["재무_강점"]:
            st.markdown(f"- {item}")
    with right:
        st.markdown("**재무 우려**")
        for item in a["재무_우려"]:
            st.markdown(f"- {item}")

    st.markdown(f"**밸류에이션** — {a['밸류에이션']}")
    with st.expander("유의사항"):
        for item in a["유의사항"]:
            st.markdown(f"- {item}")
    st.caption(f"{result['모델']} · {result['생성시각']} 생성")


def main() -> None:
    df = get_data()

    st.title("초소형주 맞춤형 AI 리포트")
    st.caption(DISCLAIMER)

    with st.sidebar:
        st.header("종목 찾기")
        markets = st.multiselect("시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])

        caps = df["시가총액"].dropna() / 1e8
        cap_min, cap_max = st.slider(
            "시가총액 (억원)",
            min_value=0,
            max_value=int(caps.max()),
            value=(0, int(caps.max())),
            step=100,
        )
        keyword = st.text_input("종목명 검색", placeholder="예: 삼성")

    view = df[df["시장구분"].isin(markets)]
    view = view[
        view["시가총액"].isna()
        | ((view["시가총액"] / 1e8 >= cap_min) & (view["시가총액"] / 1e8 <= cap_max))
    ]
    if keyword:
        view = view[view["종목명"].str.contains(keyword, case=False, na=False)]

    st.sidebar.caption(f"조건에 맞는 종목 {len(view):,}개 / 전체 {len(df):,}개")
    st.sidebar.caption(
        "ETF·ETN·우선주는 재무제표가 없어 분석 대상에서 제외했습니다. "
        "보통주만 다룹니다."
    )
    if view.empty:
        st.warning("조건에 맞는 종목이 없습니다. 필터를 넓혀보세요.")
        return

    options = view.sort_values("시가총액", ascending=False)
    labels = {
        f"{r['종목명']} ({r['종목코드']})": r["종목코드"] for _, r in options.iterrows()
    }
    picked = st.sidebar.selectbox("종목 선택", list(labels))
    row = df[df["종목코드"] == labels[picked]].iloc[0]

    st.subheader(f"{row['종목명']} · {row['시장구분']} · {row['종목코드']}")
    stat_row(row)

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("##### 손익 구성")
        fig = profit_chart(row)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("재무 데이터가 없습니다.")
    with right:
        st.markdown("##### 전체 종목 대비 위치")
        metric = st.selectbox(
            "지표", ["부채비율", "영업이익률", "ROE_계산", "PER"], label_visibility="collapsed"
        )
        fig = distribution_chart(df, row, metric)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("이 지표는 데이터가 없습니다.")

    with st.expander("숫자로 보기"):
        cols = ["매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계"]
        table = pd.DataFrame(
            {"항목": cols, "금액(억원)": [row.get(c) / 1e8 if pd.notna(row.get(c)) else None for c in cols]}
        )
        st.dataframe(table, hide_index=True, width="stretch")

    st.divider()
    st.markdown("##### AI 분석")
    used = _usage_today()
    cached = load_cached(row["종목코드"])

    if cached:
        render_analysis(cached)
    else:
        st.caption(f"오늘 신규 분석 {used}/{DAILY_LIMIT}건 사용")
        if st.button("AI 분석 생성하기", type="primary"):
            try:
                with st.spinner("분석 중... 약 5초 걸립니다"):
                    result = analyze(row)
                render_analysis(result)
            except DailyLimitReached as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"분석에 실패했습니다: {exc}")

    st.divider()
    st.caption(DISCLAIMER)


if __name__ == "__main__":
    main()
