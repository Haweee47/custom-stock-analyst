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
)
from src.analysis.report_spec import LENGTHS, PERSPECTIVES
from src.analysis.screens import apply_screens, available_screens, screen_counts
from src.analysis.money import money, price
from src.analysis.money import unit_of as money_unit
from src.analysis.usage_limit import (
    LENGTH_LIMITS,
    SESSION_LIMIT,
    SessionLimitReached,
    remaining_today,
)
from src.collectors import dataset_meta, markets
from src.collectors.disclosure_batch import TIER_HELP, TIER_LABELS
from src.collectors.disclosure_batch import load as load_disclosure_flags
from src.collectors.news_collector import price_performance, technical_summary
from src.report.report_pdf import filename as pdf_filename
from src.report.report_pdf import render_pdf
from src.report.chart import plotly_chart
from src.report.report_view import (
    body_html,
    footer_html,
    header_html,
    issues_html,
    metrics_html,
    styles_html,
    yearly_table_html,
)

# 검증된 참조 팔레트 - 강조 1색 + 맥락용 중립 회색만 쓴다
ACCENT = "#2a78d6"
NEUTRAL = "#d0cfc9"
GRID = "#ebeae5"
TEXT_MUTED = "#52514e"

st.set_page_config(page_title="리포트 셀프바", page_icon="📈", layout="wide")

# 사이드바에 보여줄 순서. 국내를 먼저 둔다.
COUNTRY_ORDER = ["국내주식", "미국주식", "일본주식", "중국주식"]

# 시가총액 구간 (억원, 원화 환산). (하한, 상한) - None은 끝이 없다는 뜻.
#
# 예전에는 0부터 최대값까지 슬라이더 하나로 받았는데, 엔비디아(7,438조원) 때문에
# 눈금이 74만 칸이 됐다. 종목 중앙값이 슬라이더 폭의 0.01% 지점에 몰려서 손으로는
# 맞출 수가 없었다. 사람이 실제로 생각하는 단위인 '대형주/소형주'로 나눈다.
CAP_BUCKETS = {
    "전체": (None, None),
    "초대형 (10조 이상)": (100_000, None),
    "대형 (1조~10조)": (10_000, 100_000),
    "중형 (3천억~1조)": (3_000, 10_000),
    "소형 (1천억~3천억)": (1_000, 3_000),
    "초소형 (1천억 미만)": (None, 1_000),
    "직접 입력": (None, None),
}


@st.cache_data
def get_data() -> pd.DataFrame:
    """국내와 해외를 한 표로 합치고 국내에만 공시를 붙인다."""
    df = markets.load_all()
    if df.empty:
        return df

    flags = load_disclosure_flags()
    if not flags.empty:
        df = df.merge(flags, on="종목코드", how="left", suffixes=("", "_공시"))
    for column in ["공시성격", "해당공시", "공시일자"]:
        if column not in df.columns:
            df[column] = None

    # 공시가 없는 것과 애초에 공시 제도를 안 보는 것은 다르다
    domestic = df["국가"] == markets.KOREA
    df.loc[domestic, "공시성격"] = df.loc[domestic, "공시성격"].fillna("공시 없음")
    df.loc[~domestic, "공시성격"] = "해당 없음"
    return df


# 지표 이름과 표시 형식. 국가마다 쓸 수 있는 것이 달라 markets가 골라 준다.
METRIC_LABELS = {
    "PER": ("PER", "{:,.2f}배"),
    "PBR": ("PBR", "{:,.2f}배"),
    "부채비율": ("부채비율", "{:,.2f}%"),
    "영업이익률": ("영업이익률", "{:,.2f}%"),
    "ROE_계산": ("ROE", "{:,.2f}%"),
    "ROA": ("ROA", "{:,.2f}%"),
}


def stat_row(row: pd.Series) -> None:
    """단일 수치는 차트가 아니라 스탯 타일로 보여준다."""
    currency = row.get("통화") or "KRW"
    metrics = markets.available_metrics(row.get("국가"))

    cols = st.columns(2 + len(metrics))
    cols[0].metric("현재가", price(row.get("현재가"), currency, empty="—"))
    cols[1].metric("시가총액", money(row.get("시가총액"), currency, empty="—"))

    for col, key in zip(cols[2:], metrics):
        label, fmt = METRIC_LABELS.get(key, (key, "{:,.2f}"))
        value = row.get(key)
        col.metric(label, "—" if pd.isna(value) else fmt.format(value))


def profit_chart(row: pd.Series) -> go.Figure | None:
    labels = ["매출액", "영업이익", "당기순이익"]
    values = [row.get(k) for k in labels]
    if all(pd.isna(v) for v in values):
        return None

    # 억 단위로 끊는 규칙은 통화가 달라도 같고, 단위 이름만 바뀐다
    unit = money_unit(row.get("통화"))
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
            hovertemplate="%{y}: %{x:,.0f}억" + unit + "<extra></extra>",
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
def get_price_history(country: str, stock_code: str, lookup: str | None = None) -> pd.DataFrame:
    """차트와 등락률에 쓰는 약 1년치 시세. 조회가 잦으므로 1시간 캐시한다.

    국내와 해외는 받아오는 경로가 다르지만 열 이름은 같게 맞춰져 있다.
    """
    try:
        return markets.price_history(country, stock_code, lookup)
    except Exception as exc:  # 시세를 못 받아도 재무 화면은 살아 있어야 한다
        print(f"[시세 조회 실패] {stock_code}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return pd.DataFrame()


def price_chart(prices: pd.DataFrame, currency: str = "KRW") -> go.Figure | None:
    if prices.empty:
        return None
    unit = money_unit(currency)
    fig = go.Figure(
        go.Scatter(
            x=prices["일자"],
            y=prices["종가"],
            mode="lines",
            line=dict(color=ACCENT, width=1.5),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f}" + unit + "<extra></extra>",
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

    # 스타일은 조각마다 넣지 않고 렌더 시작에서 한 번만 심는다
    st.html(styles_html())
    st.html(header_html(row, result))

    left, right = st.columns([1, 2.1], gap="medium")
    with left:
        st.html(metrics_html(row, perf, tech))
        if result["관점"] != "기술적":
            fig = price_chart(prices, row.get("통화") or "KRW")
            if fig:
                st.caption("주가 추이 (1년)")
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with right:
        st.html(body_html(result))

    if result["관점"] == "기술적" and not prices.empty:
        st.markdown("##### 지표 차트")
        chart, events = plotly_chart(prices, row.get("통화") or "KRW")
        st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})
        if events:
            st.caption(
                "표시된 시점 — "
                + " · ".join(
                    f"{e['일자']:%y.%m.%d} {e['종류']}" for e in sorted(events, key=lambda x: x["일자"])
                )
            )

    # 이어지는 세 블록은 한 번에 심는다. st.html을 나눠 부르면 그 사이마다
    # Streamlit이 여백을 넣어 한 장의 리포트가 아니라 카드 더미처럼 보인다.
    issues = result["리포트"].get("주요이슈") or []
    st.html(
        issues_html(issues) + yearly_table_html(row) + footer_html(result)
    )
    stamp = dataset_meta.oldest_date()
    if stamp:
        st.caption(f"재무·시세 데이터 기준일 {stamp} · 뉴스와 공시는 조회 시점 기준")

    try:
        st.download_button(
            "PDF로 저장",
            data=render_pdf(row, result, perf, tech, prices),
            file_name=pdf_filename(row, result),
            mime="application/pdf",
        )
        st.caption("PDF에는 지표 차트가 포함되지 않습니다. 본문과 표만 담깁니다.")
    except Exception as exc:
        st.caption("PDF 저장을 준비하지 못했습니다.")
        print(f"[PDF 실패] {type(exc).__name__}: {exc}", file=sys.stderr)


def main() -> None:
    df = get_data()

    st.title("리포트 셀프바")
    stamp = dataset_meta.oldest_date()
    counts = df["국가"].value_counts()
    scope = " · ".join(f"{name} {int(counts.get(name, 0)):,}개" for name in COUNTRY_ORDER if name in counts)
    st.caption(
        f"종목도, 관점도 골라 담으세요 · {scope}"
        + (f" · {stamp} 종가 기준" if stamp else "")
    )
    st.caption(DISCLAIMER)

    with st.sidebar:
        st.header("종목 찾기")

        # 국가를 먼저 고른다. 아래 필터는 나라마다 쓸 수 있는 항목이 다르므로
        # 여기서 정해진 범위 안에서만 만들어진다.
        countries = [c for c in COUNTRY_ORDER if (df["국가"] == c).any()]
        country = st.radio(
            "시장",
            countries,
            horizontal=True,
            format_func=lambda c: f"{c} ({int((df['국가'] == c).sum()):,})",
        )
        pool = df[df["국가"] == country]
        domestic = country == markets.KOREA

        exchanges = sorted(pool["시장구분"].dropna().unique())
        picked_exchanges = st.multiselect("거래소", exchanges, default=exchanges)

        # 국내는 업종이 대·소분류 2단이고, 해외는 네이버 업종 하나뿐이다
        if domestic:
            groups = sorted(pool["업종_대분류"].dropna().unique())
            group = st.selectbox("업종 대분류", ["전체"] + groups)
            sub_options = (
                ["전체"]
                if group == "전체"
                else ["전체"] + sorted(pool.loc[pool["업종_대분류"] == group, "업종_소분류"].dropna().unique())
            )
            sub = st.selectbox("업종 소분류", sub_options, disabled=(group == "전체"))
        else:
            group = "전체"
            sub = st.selectbox("업종", ["전체"] + sorted(pool["업종_소분류"].dropna().unique()))

        if domestic:
            kinds = [k for k in TIER_LABELS.values() if (pool["공시성격"] == k).any()]
            kind_counts = pool["공시성격"].value_counts()
            disclosure_kinds = st.multiselect(
                "최근 공시 (3개월)",
                kinds,
                format_func=lambda k: f"{k} ({kind_counts.get(k, 0):,})",
                help=" / ".join(f"{k}: {v}" for k, v in TIER_HELP.items()),
            )
            hide_risky = st.checkbox(
                "중대 공시 종목 제외",
                help="상장폐지·관리종목 지정우려·자본잠식 등의 공시가 있는 종목을 목록에서 뺍니다.",
            )
        else:
            disclosure_kinds, hide_risky = [], False

        # 해외는 자본총계가 없어 ROE·부채비율 조건을 판정할 수 없다.
        # 고를 수는 있는데 늘 0건이면 이유를 알 수 없으므로 아예 빼고 보여준다.
        usable = available_screens(pool)
        counts = screen_counts(pool)
        screens = st.multiselect(
            "재무 특성",
            usable,
            format_func=lambda name: f"{name} ({counts[name]:,})",
            help="여러 개를 고르면 모두 만족하는 종목만 남습니다.",
        )
        if not domestic:
            st.caption("해외 종목은 자본·부채총계가 제공되지 않아 ROE·부채비율 조건은 뺐습니다.")

        # 통화가 섞이므로 시총 범위는 원화 환산 기준으로 건다
        caps = pool["시가총액_원화"].dropna() / 1e8
        cap_ceiling = int(caps.max()) if not caps.empty else 0

        bucket_counts = {
            name: int(((caps >= (low or 0)) & (caps < (high or float("inf")))).sum())
            for name, (low, high) in CAP_BUCKETS.items()
            if name not in ("전체", "직접 입력")
        }
        bucket = st.selectbox(
            "시가총액",
            list(CAP_BUCKETS),
            format_func=lambda name: (
                name if name not in bucket_counts else f"{name} · {bucket_counts[name]:,}개"
            ),
            help="원화로 환산한 금액 기준입니다.",
        )

        if bucket == "직접 입력":
            low_col, high_col = st.columns(2)
            cap_min = low_col.number_input(
                "최소(억원)", min_value=0, max_value=cap_ceiling, value=0, step=1_000,
                key=f"cap_low_{country}",
            )
            cap_max = high_col.number_input(
                "최대(억원)", min_value=0, max_value=cap_ceiling, value=cap_ceiling, step=1_000,
                key=f"cap_high_{country}",
            )
            if cap_min > cap_max:
                cap_min, cap_max = cap_max, cap_min
        else:
            low, high = CAP_BUCKETS[bucket]
            cap_min = low or 0
            cap_max = high if high is not None else cap_ceiling

        if not domestic:
            rate, fresh = markets.fx_rate("USD")
            st.caption(
                f"환율 {rate:,.1f}원/달러 적용"
                + ("" if fresh else " (환율 갱신 실패, 최근 값 사용)")
            )
        keyword = st.text_input(
            "종목명 검색", placeholder="예: 삼성" if domestic else "예: 애플, NVDA"
        )

        st.divider()
        age = dataset_meta.days_old()
        line = dataset_meta.summary_line()
        if age is not None and age >= 3:
            st.warning(line)
        else:
            st.caption(line)
        meta = dataset_meta.read()
        if meta:
            with st.expander("데이터별 갱신 시각"):
                for name, info in meta.items():
                    st.caption(f"{dataset_meta.LABELS.get(name, name)} · {info.get('갱신', '')}")

    view = pool[pool["시장구분"].isin(picked_exchanges)]
    if group != "전체":
        view = view[view["업종_대분류"] == group]
    if sub != "전체":
        view = view[view["업종_소분류"] == sub]
    if disclosure_kinds:
        view = view[view["공시성격"].isin(disclosure_kinds)]
    if hide_risky:
        view = view[view["공시성격"] != "중대 공시"]
    if screens:
        view = apply_screens(view, screens)
    # 시총을 모르는 종목(상장폐지 등 251개)은 '전체'일 때만 남긴다.
    # 규모를 골랐는데 규모를 모르는 종목이 섞여 나오면 필터가 거짓말이 된다.
    billions = view["시가총액_원화"] / 1e8
    if bucket == "전체":
        view = view[billions.isna() | ((billions >= cap_min) & (billions <= cap_max))]
    else:
        view = view[(billions >= cap_min) & (billions <= cap_max)]
    if keyword:
        # 해외는 영문 티커나 영문명으로 찾는 사람이 많다
        haystack = view["종목명"].fillna("")
        for column in ("영문명", "종목코드"):
            if column in view.columns:
                haystack = haystack + " " + view[column].fillna("")
        view = view[haystack.str.contains(keyword, case=False, na=False)]

    st.sidebar.caption(f"조건에 맞는 종목 {len(view):,}개 / {country} {len(pool):,}개")
    st.sidebar.caption(
        "ETF·ETN·우선주는 재무제표가 없어 분석 대상에서 제외했습니다. 보통주만 다룹니다."
        if domestic
        else "나스닥·뉴욕 상장 종목입니다. 공시와 뉴스는 제공되지 않습니다."
    )
    if view.empty:
        st.warning("조건에 맞는 종목이 없습니다. 필터를 넓혀보세요.")
        return

    # 종목이 6,775개까지 늘어 iterrows로 라벨을 만들면 화면을 건드릴 때마다
    # 0.3초씩 먹는다. 벡터 연산으로 바꿔 10배 이상 줄였다.
    options = view.sort_values("시가총액_원화", ascending=False)
    mark = (options["공시성격"] == "중대 공시").map({True: "⚠ ", False: ""})
    labels = dict(
        zip(mark + options["종목명"].fillna("") + " (" + options["종목코드"] + ")", options["종목코드"])
    )
    picked = st.sidebar.selectbox("종목 선택", list(labels))
    row = pool[pool["종목코드"] == labels[picked]].iloc[0]

    st.subheader(f"{row['종목명']} · {row['시장구분']} · {row['종목코드']}")
    if row.get("공시성격") == "중대 공시":
        st.warning(
            f"**최근 중대 공시가 있습니다** — {row.get('해당공시', '')} "
            f"({row.get('공시일자', '')}). 내용을 직접 확인해보세요."
        )
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
        st.markdown(f"##### {country} 전체 대비 위치")
        metric = st.selectbox(
            "지표",
            markets.available_metrics(country),
            format_func=lambda k: METRIC_LABELS.get(k, (k, ""))[0],
            label_visibility="collapsed",
        )
        # 비교는 같은 시장 안에서만 한다. 나라를 섞으면 회계 기준이 달라 뜻이 없다.
        fig = distribution_chart(pool, row, metric)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("이 지표는 데이터가 없습니다.")

    with st.expander("숫자로 보기"):
        # 해외는 자산·부채·자본총계가 제공되지 않아 항목이 다르다
        cols = [
            c
            for c in ["매출액", "영업이익", "당기순이익", "EBITDA", "자산총계", "부채총계", "자본총계"]
            if pd.notna(row.get(c))
        ]
        unit = money_unit(row.get("통화"))
        table = pd.DataFrame(
            {
                "항목": cols,
                f"금액(억{unit})": [f"{row.get(c) / 1e8:,.0f}" for c in cols],
            }
        )
        st.dataframe(table, hide_index=True, width="stretch")
        if not domestic:
            st.caption("해외 종목은 자산·부채·자본총계가 제공되지 않습니다. 영업이익은 EBIT 기준입니다.")

    st.divider()
    st.markdown("##### AI 리포트")

    # 관점도 나라마다 다르다. 해외는 뉴스·공시가 없어 '이슈·트렌드'를 열지 않는다.
    views = markets.available_perspectives(country)
    opt_left, opt_right = st.columns(2)
    perspective = opt_left.radio(
        "분석 관점",
        views,
        horizontal=True,
        captions=[PERSPECTIVES[k]["설명"] for k in views],
    )
    length = opt_right.radio(
        "분량",
        list(LENGTHS),
        horizontal=True,
        captions=[LENGTHS[k]["설명"] for k in LENGTHS],
    )
    if not domestic:
        st.caption("해외 종목은 뉴스·공시를 제공하지 않아 '이슈·트렌드' 관점은 열지 않았습니다.")

    prices = get_price_history(country, row["종목코드"], row.get("조회코드"))

    cached = load_cached(row["종목코드"], perspective, length, country)
    if cached:
        render_report(cached, row, prices)
    else:
        # 상세형은 출력이 길어 비용이 높으므로 하루 상한을 따로 둔다
        note = f"오늘 신규 생성 {_usage_today()}/{DAILY_LIMIT}건 사용"
        cap = LENGTH_LIMITS.get(length)
        if cap:
            note += f" · {length} {_usage_today(length)}/{cap}건"
        note += f" (남은 {remaining_today(length)}건, 이번 접속에서 최대 {SESSION_LIMIT}건)"
        st.caption(note)
        if st.button(f"{perspective} 관점으로 리포트 생성", type="primary"):
            try:
                with st.spinner("데이터를 모으고 리포트를 작성하는 중..."):
                    context = gather_context(row, perspective)
                    result = analyze(row, perspective, length, **context)
                render_report(result, row, prices)
            except (DailyLimitReached, SessionLimitReached) as exc:
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
