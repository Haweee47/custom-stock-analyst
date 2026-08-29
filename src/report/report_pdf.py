"""리포트를 PDF로 내보낸다.

xhtml2pdf는 flexbox를 지원하지 않으므로, 화면용 HTML을 그대로 쓰지 않고
표 기반 레이아웃으로 다시 구성한다. 한글 폰트는 배포 환경(리눅스)에
맑은 고딕이 없으므로 저장소에 담은 나눔고딕을 등록해 쓴다.
"""
import base64
from io import BytesIO
from pathlib import Path

import matplotlib

# 서버에는 화면이 없으므로 GUI를 쓰지 않는 백엔드를 강제한다
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xhtml2pdf import pisa
from xhtml2pdf.default import DEFAULT_FONT

from src.report.report_view import _growth, _num, _signed, won

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = ROOT / "assets" / "fonts"
FONT_NAME = "Nanum"
_FONT_READY = False


def _register_font() -> None:
    """@font-face는 쓰지 않는다. xhtml2pdf가 폰트를 임시파일로 복사하는데
    Windows에서 그 파일을 다시 열지 못해 실패한다. 대신 reportlab에 직접 등록하고
    xhtml2pdf 폰트 매핑에 이름을 넣어준다. 한 번만 수행한다."""
    global _FONT_READY
    if _FONT_READY:
        return
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_DIR / "NanumGothic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(f"{FONT_NAME}-Bold", str(FONT_DIR / "NanumGothic-Bold.ttf")))
    pdfmetrics.registerFontFamily(
        FONT_NAME, normal=FONT_NAME, bold=f"{FONT_NAME}-Bold",
        italic=FONT_NAME, boldItalic=f"{FONT_NAME}-Bold",
    )
    # xhtml2pdf는 CSS의 font-family를 소문자로 조회하므로 매핑을 넣어준다
    DEFAULT_FONT["nanum"] = FONT_NAME
    _FONT_READY = True

ACCENT = "#12386b"
SOFT = "#eef2f8"
RULE = "#d5d8dd"
MUTED = "#6e7480"

PDF_CSS = f"""
@page {{ size: A4; margin: 14mm 13mm 16mm 13mm; }}
body {{ font-family: "Nanum"; font-size: 8.4pt; color: #2b2b2b; line-height: 1.5; }}
h1 {{ font-size: 17pt; color: {ACCENT}; margin: 0; }}
h1 small {{ font-size: 11pt; color: {MUTED}; }}
.headline {{ font-size: 11pt; font-weight: bold; color: #111;
             border-bottom: 1.6pt solid {ACCENT}; padding-bottom: 5pt; margin: 5pt 0 9pt; }}
.band {{ border-bottom: .5pt solid {RULE}; padding-bottom: 4pt; margin-bottom: 7pt;
         font-size: 7pt; color: {MUTED}; letter-spacing: .5pt; }}
.brand {{ color: {ACCENT}; font-weight: bold; }}
.boxhead {{ background: {SOFT}; color: {ACCENT}; font-size: 7.2pt; font-weight: bold;
            padding: 3pt 5pt; border: .5pt solid {RULE}; }}
table {{ border-collapse: collapse; width: 100%; }}
table.kv td {{ font-size: 7.8pt; padding: 2.4pt 5pt; border-bottom: .4pt solid #edeff2; }}
table.kv td.k {{ color: {MUTED}; }}
table.kv td.v {{ text-align: right; font-weight: bold; color: #111; }}
table.yr th {{ background: {SOFT}; color: {ACCENT}; font-size: 7.2pt; padding: 3pt 4pt;
               border-bottom: .5pt solid {RULE}; text-align: right; }}
table.yr th.l {{ text-align: left; }}
table.yr td {{ font-size: 7.8pt; padding: 2.6pt 4pt; border-bottom: .4pt solid #edeff2;
               text-align: right; font-weight: bold; color: #111; }}
table.yr td.l {{ text-align: left; color: {MUTED}; font-weight: normal; }}
.points {{ background: #fafbfc; border-left: 2.4pt solid {ACCENT}; padding: 6pt 8pt; margin-bottom: 7pt; }}
.points p {{ margin: 0 0 3pt; font-size: 8.2pt; }}
.sec {{ margin-bottom: 7pt; }}
.sec h3 {{ font-size: 9.4pt; color: {ACCENT}; margin: 0 0 3.5pt; padding-left: 5pt;
           border-left: 2.4pt solid {ACCENT}; }}
.sec p {{ margin: 0; font-size: 8.2pt; text-align: justify; }}
.half {{ border: .5pt solid {RULE}; border-top: 1.6pt solid {ACCENT}; padding: 5pt 7pt; }}
.half h4 {{ margin: 0 0 4pt; font-size: 8pt; color: {ACCENT}; }}
.half p {{ margin: 0 0 3pt; font-size: 7.8pt; }}
.foot {{ margin-top: 8pt; padding-top: 5pt; border-top: .5pt solid {RULE};
         font-size: 6.8pt; color: {MUTED}; }}
.up {{ color: #c0392b; }} .down {{ color: #1f5fa8; }}
"""


def _chart_img(prices: pd.DataFrame) -> str:
    """주가 추이를 PNG로 그려 data URI로 돌려준다.

    plotly 이미지 변환(kaleido)은 내부적으로 브라우저를 띄워 메모리를 많이 쓴다.
    선 하나짜리 차트에는 matplotlib이면 충분하다.
    """
    if prices.empty:
        return ""

    fig, ax = plt.subplots(figsize=(2.3, 1.0), dpi=220)
    ax.plot(prices["일자"], prices["종가"], color=ACCENT, linewidth=1.0)
    ax.fill_between(prices["일자"], prices["종가"], prices["종가"].min(),
                    color=ACCENT, alpha=0.06)

    ax.yaxis.tick_right()
    ax.grid(axis="y", color="#e9ebef", linewidth=0.5)
    ax.set_axisbelow(True)
    for side in ["top", "left", "right"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#d5d8dd")
    ax.spines["bottom"].set_linewidth(0.5)
    ax.tick_params(labelsize=4.2, colors="#6e7480", length=0, pad=1.5)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}")
    )
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4))
    ax.set_xticks([prices["일자"].iloc[0], prices["일자"].iloc[-1]])
    ax.set_xticklabels(
        [d.strftime("%y.%m") for d in [prices["일자"].iloc[0], prices["일자"].iloc[-1]]]
    )
    fig.tight_layout(pad=0.15)

    buffer = BytesIO()
    fig.savefig(buffer, format="png", transparent=True)
    plt.close(fig)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    # xhtml2pdf는 퍼센트 폭을 읽지 못하므로 좌측 단 폭에 맞춘 고정값을 준다
    return f'<img src="data:image/png;base64,{encoded}" style="width:150pt; height:64pt">'


def _kv(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f'<tr><td class="k">{k}</td><td class="v">{v}</td></tr>' for k, v in pairs)
    return f'<table class="kv">{rows}</table>'


def _yearly(row: pd.Series) -> str:
    base = row.get("기준연도")
    if pd.isna(base):
        return ""
    base = int(base)
    suffixes = ["_전전기", "_전기", ""]
    head = "".join(f"<th>{base - 2 + i}</th>" for i in range(3))

    body = ""
    for account in ["매출액", "영업이익", "당기순이익"]:
        values = [row.get(f"{account}{s}") for s in suffixes]
        cells = "".join(f"<td>{_num(v, '', 1e8)}</td>" for v in values)
        body += f'<tr><td class="l">{account}</td>{cells}<td>{_growth(values[2], values[1])}</td></tr>'

    return f"""<div class="boxhead">요약 실적 (억원)</div>
<table class="yr"><tr><th class="l">구분</th>{head}<th>전년비</th></tr>{body}</table>"""


def build_html(
    row: pd.Series,
    result: dict,
    perf: dict | None,
    tech: dict | None,
    prices: pd.DataFrame | None = None,
) -> str:
    report = result["리포트"]
    date = result["생성시각"][:10].replace("-", ".")

    price = [
        ("현재주가", _num(row.get("현재가"), "원")),
        ("시가총액", won(row.get("시가총액"))),
        ("발행주식수", _num(row.get("상장주식수"), "천주", 1e3)),
        ("외국인비율", _num(row.get("외국인비율"), "%", digits=2)),
    ]
    if tech:
        price += [
            ("1년 최고", _num(tech.get("기간고가"), "원")),
            ("1년 최저", _num(tech.get("기간저가"), "원")),
        ]
    valuation = [
        ("PER", _num(row.get("PER"), "배", digits=2)),
        ("ROE", _num(row.get("ROE_계산"), "%", digits=2)),
        ("부채비율", _num(row.get("부채비율"), "%", digits=2)),
        ("영업이익률", _num(row.get("영업이익률"), "%", digits=2)),
    ]

    side = f'<div class="boxhead">주가 정보</div>{_kv(price)}'
    if perf:
        side += '<div class="boxhead" style="margin-top:6pt">주가 등락률</div>'
        side += _kv([(k, _signed(v)) for k, v in perf.items()])
    side += '<div class="boxhead" style="margin-top:6pt">투자지표</div>' + _kv(valuation)
    if prices is not None and not prices.empty:
        side += '<div class="boxhead" style="margin-top:6pt">주가 추이 (1년)</div>'
        side += f'<div style="border:.5pt solid {RULE}; border-top:0; padding:3pt">{_chart_img(prices)}</div>' 

    points = "".join(f"<p>· {p}</p>" for p in report["핵심포인트"])
    sections = "".join(
        f'<div class="sec"><h3>{s["소제목"]}</h3><p>{s["본문"]}</p></div>'
        for s in report["섹션"]
    )
    checks = "".join(f"<p>· {c}</p>" for c in report["체크포인트"])
    risks = "".join(f"<p>· {r}</p>" for r in report["리스크요인"])

    return f"""<html><head><meta charset="utf-8"><style>{PDF_CSS}</style></head><body>
<div class="band">
  <table><tr>
    <td class="brand" style="font-size:7pt">AI COMPANY REPORT</td>
    <td style="text-align:right; font-size:7pt; color:{MUTED}">
      {date} · {row['시장구분']} · 기업분석 · 분석관점 {result['관점']}</td>
  </tr></table>
</div>

<table><tr>
  <td><h1>{row['종목명']} <small>({row['종목코드']})</small></h1></td>
  <td style="text-align:right; font-size:7pt; color:{MUTED}">
    {result['분량']} · {result['모델']}<br>투자의견·목표주가 미제공</td>
</tr></table>
<div class="headline">{report['헤드라인']}</div>

<table><tr>
  <td width="32%" valign="top">{side}</td>
  <td width="3%"></td>
  <td width="65%" valign="top">
    <div class="points">{points}</div>
    {sections}
    <div class="half" style="margin-top:2pt"><h4>투자자가 확인해야 할 점</h4>{checks}</div>
    <div class="half" style="margin-top:6pt"><h4>리스크 요인</h4>{risks}</div>
  </td>
</tr></table>

<div style="margin-top:6pt">{_yearly(row)}</div>

<div class="foot">
  <b>이 리포트가 보지 못한 것</b><br>{report['데이터한계']}<br><br>{result['면책']}
</div>
</body></html>"""


def render_pdf(
    row: pd.Series,
    result: dict,
    perf: dict | None,
    tech: dict | None,
    prices: pd.DataFrame | None = None,
) -> bytes:
    _register_font()
    buffer = BytesIO()
    status = pisa.CreatePDF(
        build_html(row, result, perf, tech, prices), dest=buffer, encoding="utf-8"
    )
    if status.err:
        raise RuntimeError("PDF 생성에 실패했습니다.")
    return buffer.getvalue()


def filename(row: pd.Series, result: dict) -> str:
    date = result["생성시각"][:10].replace("-", "")
    return f"{row['종목명']}_{row['종목코드']}_{result['관점']}_{date}.pdf"
