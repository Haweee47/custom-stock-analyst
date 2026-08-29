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
    ApiKeyMissing,
    DailyLimitReached,
    _usage_today,
    analyze,
    gather_context,
    load_cached,
    load_financials,
)
from src.analysis.report_spec import LENGTHS, PERSPECTIVES

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


def render_report(result: dict) -> None:
    report = result["리포트"]
    st.markdown(f"### {report['헤드라인']}")
    st.caption(f"{result['관점']} 관점 · {result['분량']} · {result['모델']} · {result['생성시각']}")

    st.markdown("**핵심 포인트**")
    for point in report["핵심포인트"]:
        st.markdown(f"- {point}")

    for section in report["섹션"]:
        st.markdown(f"**{section['소제목']}**")
        st.write(section["본문"])

    left, right = st.columns(2)
    with left:
        st.markdown("**확인할 점**")
        for item in report["체크포인트"]:
            st.markdown(f"- {item}")
    with right:
        st.markdown("**리스크 요인**")
        for item in report["리스크요인"]:
            st.markdown(f"- {item}")

    with st.expander("이 리포트가 보지 못한 것"):
        st.write(report["데이터한계"])


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
    st.markdown("##### AI 리포트")

    opt_left, opt_right = st.columns(2)
    perspective = opt_left.radio(
        "분석 관점",
        list(PERSPECTIVES),
        horizontal=True,
        captions=[PERSPECTIVES[k]["설명"] for k in PERSPECTIVES],
    )
    length = opt_right.radio(
        "분량",
        list(LENGTHS),
        horizontal=True,
        captions=[LENGTHS[k]["설명"] for k in LENGTHS],
    )

    cached = load_cached(row["종목코드"], perspective, length)
    if cached:
        render_report(cached)
    else:
        st.caption(f"오늘 신규 생성 {_usage_today()}/{DAILY_LIMIT}건 사용")
        if st.button(f"{perspective} 관점으로 리포트 생성", type="primary"):
            try:
                with st.spinner("데이터를 모으고 리포트를 작성하는 중..."):
                    context = gather_context(row["종목코드"], perspective)
                    result = analyze(row, perspective, length, **context)
                render_report(result)
            except DailyLimitReached as exc:
                st.warning(str(exc))
            except ApiKeyMissing as exc:
                st.error("현재 AI 리포트 기능을 이용할 수 없습니다. 잠시 후 다시 시도해주세요.")
                st.caption("운영자: API 키 설정이 필요합니다.")
                print(f"[설정 오류] {exc}", file=sys.stderr)
            except Exception as exc:
                st.error("리포트 생성 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.")
                print(f"[분석 실패] {type(exc).__name__}: {exc}", file=sys.stderr)

    st.divider()
    st.caption(DISCLAIMER)


if __name__ == "__main__":
    main()
