"""리포트 셀프바 - Streamlit 웹앱."""
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
from src.analysis.screens import SCREENS, apply_screens, screen_counts
from src.collectors.sector_collector import load as load_sectors
from src.collectors.news_collector import (
    fetch_price_history,
    price_performance,
    technical_summary,
)
from src.report.report_pdf import filename as pdf_filename
from src.report.report_pdf import render_pdf
from src.report.report_view import (
    body_html,
    footer_html,
    header_html,
    metrics_html,
    won,
    yearly_table_html,
)

# 검증된 참조 팔레트 - 강조 1색 + 맥락용 중립 회색만 쓴다
ACCENT = "#2a78d6"
NEUTRAL = "#d0cfc9"
GRID = "#ebeae5"
TEXT_MUTED = "#52514e"

st.set_page_config(page_title="리포트 셀프바", page_icon="📈", layout="wide")


@st.cache_data
def get_data() -> pd.DataFrame:
    """재무에 업종을 붙여 하나의 표로 다룬다."""
    df = load_financials()
    sectors = load_sectors()
    if sectors.empty:
        df["업종_대분류"] = "미분류"
        df["업종_소분류"] = "미분류"
        return df
    merged = df.merge(sectors, on="종목코드", how="left")
    merged[["업종_대분류", "업종_소분류"]] = merged[["업종_대분류", "업종_소분류"]].fillna("미분류")
    return merged


def stat_row(row: pd.Series) -> None:
    """단일 수치는 차트가 아니라 스탯 타일로 보여준다."""
    cols = st.columns(6)
    items = [
        ("현재가", row.get("현재가"), "{:,.0f}원"),
        ("시가총액", row.get("시가총액"), None),
        ("PER", row.get("PER"), "{:,.2f}배"),
        ("부채비율", row.get("부채비율"), "{:,.2f}%"),
        ("영업이익률", row.get("영업이익률"), "{:,.2f}%"),
        ("ROE", row.get("ROE_계산"), "{:,.2f}%"),
    ]
    for col, (label, value, fmt) in zip(cols, items):
        if pd.isna(value):
            col.metric(label, "—")
        elif fmt is None:
            col.metric(label, won(value))
        else:
            col.metric(label, fmt.format(value))


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


@st.cache_data(ttl=3600, show_spinner=False)
def get_price_history(stock_code: str) -> pd.DataFrame:
    """차트와 등락률에 쓰는 약 1년치 시세. 조회가 잦으므로 1시간 캐시한다."""
    return fetch_price_history(stock_code, pages=25)


def price_chart(prices: pd.DataFrame) -> go.Figure | None:
    if prices.empty:
        return None
    fig = go.Figure(
        go.Scatter(
            x=prices["일자"],
            y=prices["종가"],
            mode="lines",
            line=dict(color=ACCENT, width=1.5),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f}원<extra></extra>",
        )
    )
    fig.update_layout(
        height=190,
        margin=dict(l=8, r=8, t=8, b=8),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_MUTED, size=10),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False, side="right"),
        showlegend=False,
    )
    return fig


def render_report(result: dict, row: pd.Series, prices: pd.DataFrame) -> None:
    perf = price_performance(prices) if not prices.empty else None
    tech = technical_summary(prices) if not prices.empty else None

    st.html(header_html(row, result))

    left, right = st.columns([1, 2.1], gap="medium")
    with left:
        st.html(metrics_html(row, perf, tech))
        fig = price_chart(prices)
        if fig:
            st.caption("주가 추이 (1년)")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with right:
        st.html(body_html(result))

    st.html(yearly_table_html(row))
    st.html(footer_html(result))

    try:
        st.download_button(
            "PDF로 저장",
            data=render_pdf(row, result, perf, tech, prices),
            file_name=pdf_filename(row, result),
            mime="application/pdf",
        )
    except Exception as exc:
        st.caption("PDF 저장을 준비하지 못했습니다.")
        print(f"[PDF 실패] {type(exc).__name__}: {exc}", file=sys.stderr)


def main() -> None:
    df = get_data()

    st.title("리포트 셀프바")
    st.caption("종목도, 관점도 골라 담으세요 · 코스피·코스닥 전 종목")
    st.caption(DISCLAIMER)

    with st.sidebar:
        st.header("종목 찾기")
        markets = st.multiselect("시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])

        groups = sorted(df["업종_대분류"].dropna().unique())
        group = st.selectbox("업종 대분류", ["전체"] + groups)

        if group == "전체":
            sub_options = ["전체"]
        else:
            sub_options = ["전체"] + sorted(
                df.loc[df["업종_대분류"] == group, "업종_소분류"].dropna().unique()
            )
        sub = st.selectbox("업종 소분류", sub_options, disabled=(group == "전체"))

        counts = screen_counts(df)
        screens = st.multiselect(
            "재무 특성",
            list(SCREENS),
            format_func=lambda name: f"{name} ({counts[name]:,})",
            help="여러 개를 고르면 모두 만족하는 종목만 남습니다.",
        )

        caps = df["시가총액"].dropna() / 1e8
        cap_ceiling = int(caps.max())

        # 슬라이더와 숫자 입력이 서로를 갱신하도록 세션 상태를 공유한다
        if "cap_range" not in st.session_state:
            st.session_state.cap_range = (0, cap_ceiling)

        st.markdown("**시가총액 (억원)**")
        st.slider(
            "시가총액 범위",
            min_value=0,
            max_value=cap_ceiling,
            step=100,
            key="cap_range",
            label_visibility="collapsed",
        )

        def _sync_from_inputs() -> None:
            low = st.session_state.cap_low
            high = st.session_state.cap_high
            st.session_state.cap_range = (min(low, high), max(low, high))

        low_col, high_col = st.columns(2)
        low_col.number_input(
            "최소",
            min_value=0,
            max_value=cap_ceiling,
            value=st.session_state.cap_range[0],
            step=100,
            key="cap_low",
            on_change=_sync_from_inputs,
        )
        high_col.number_input(
            "최대",
            min_value=0,
            max_value=cap_ceiling,
            value=st.session_state.cap_range[1],
            step=100,
            key="cap_high",
            on_change=_sync_from_inputs,
        )

        cap_min, cap_max = st.session_state.cap_range
        st.caption(f"{cap_min:,}억원 ~ {cap_max:,}억원")
        keyword = st.text_input("종목명 검색", placeholder="예: 삼성")

    view = df[df["시장구분"].isin(markets)]
    if group != "전체":
        view = view[view["업종_대분류"] == group]
        if sub != "전체":
            view = view[view["업종_소분류"] == sub]
    if screens:
        view = apply_screens(view, screens)
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
        # 소수점은 억원 단위에서 의미가 없으므로 반올림하고 쉼표만 남긴다
        table = pd.DataFrame(
            {
                "항목": cols,
                "금액(억원)": [
                    f"{row.get(c) / 1e8:,.0f}" if pd.notna(row.get(c)) else "—"
                    for c in cols
                ],
            }
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
        render_report(cached, row, get_price_history(row["종목코드"]))
    else:
        st.caption(f"오늘 신규 생성 {_usage_today()}/{DAILY_LIMIT}건 사용")
        if st.button(f"{perspective} 관점으로 리포트 생성", type="primary"):
            try:
                with st.spinner("데이터를 모으고 리포트를 작성하는 중..."):
                    context = gather_context(row["종목코드"], perspective)
                    result = analyze(row, perspective, length, **context)
                render_report(result, row, get_price_history(row["종목코드"]))
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
