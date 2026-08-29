"""리포트를 증권사 리포트 레이아웃으로 렌더링한다.

실제 리포트의 시각 문법을 따른다.
  - 상단 헤더 밴드와 액센트 라인
  - 종목명(코드) 큰 제목 + 한 줄 헤드라인
  - 좌측 지표 박스(주가·등락률·투자지표), 우측 본문 2단 구성
  - 요약 실적 3개년 추이표 (증권사 리포트의 표준 요소)
  - 소제목은 좌측 컬러 바로 구분하고 본문은 촘촘하게

투자의견·목표주가 자리에는 넣을 수 없으므로, 그 자리를 핵심 지표가 차지한다.
"""
import pandas as pd

ACCENT = "#12386b"
ACCENT_LINE = "#1a4d8f"
ACCENT_SOFT = "#eef2f8"
INK = "#111"
BODY = "#2b2b2b"
MUTED = "#6e7480"
RULE = "#d5d8dd"
HAIR = "#edeff2"
UP = "#c0392b"
DOWN = "#1f5fa8"

CSS = f"""
<style>
.rpt {{
  font-family: "Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", sans-serif;
  color: {BODY}; font-size: 12.5px; line-height: 1.62;
  background: #fff; border: 1px solid {RULE}; padding: 0;
}}
.rpt-inner {{ padding: 16px 20px 18px; }}
.rpt-top {{ height: 3px; background: {ACCENT}; }}
.rpt-band {{
  display: flex; justify-content: space-between; align-items: baseline;
  border-bottom: 1px solid {RULE}; padding: 10px 20px 7px;
  font-size: 10.5px; color: {MUTED}; letter-spacing: .06em; text-transform: uppercase;
}}
.rpt-brand {{ font-weight: 800; color: {ACCENT}; letter-spacing: .12em; }}

.rpt-title {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; }}
.rpt-name {{ font-size: 25px; font-weight: 800; color: {ACCENT}; margin: 0; letter-spacing: -.02em; }}
.rpt-name small {{ font-size: 15px; font-weight: 600; color: {MUTED}; letter-spacing: 0; }}
.rpt-meta {{ font-size: 10.5px; color: {MUTED}; text-align: right; line-height: 1.7; white-space: nowrap; }}
.rpt-headline {{
  font-size: 15.5px; font-weight: 700; color: {INK}; margin: 7px 0 0;
  padding-bottom: 11px; border-bottom: 2px solid {ACCENT}; letter-spacing: -.01em;
}}

.rpt-box {{ border: 1px solid {RULE}; margin-bottom: 10px; }}
.rpt-box h4 {{
  margin: 0; padding: 5px 10px; font-size: 10.5px; font-weight: 700;
  background: {ACCENT_SOFT}; color: {ACCENT}; border-bottom: 1px solid {RULE};
  letter-spacing: .06em;
}}
table.rpt-t {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
table.rpt-t td {{ padding: 4px 10px; border-bottom: 1px solid {HAIR}; }}
table.rpt-t td:first-child {{ color: {MUTED}; }}
table.rpt-t td:last-child {{ text-align: right; font-weight: 700; color: {INK};
  font-variant-numeric: tabular-nums; }}
table.rpt-t tr:last-child td {{ border-bottom: none; }}

table.rpt-yr {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
table.rpt-yr th {{
  background: {ACCENT_SOFT}; color: {ACCENT}; font-size: 10.5px; font-weight: 700;
  padding: 5px 8px; border-bottom: 1px solid {RULE}; text-align: right;
}}
table.rpt-yr th:first-child {{ text-align: left; }}
table.rpt-yr td {{ padding: 4px 8px; border-bottom: 1px solid {HAIR}; text-align: right;
  font-variant-numeric: tabular-nums; color: {INK}; font-weight: 600; }}
table.rpt-yr td:first-child {{ text-align: left; color: {MUTED}; font-weight: 400; }}
table.rpt-yr tr:last-child td {{ border-bottom: none; }}

.up {{ color: {UP}; }} .down {{ color: {DOWN}; }}

.rpt-points {{
  margin: 0 0 15px; padding: 12px 16px 12px 18px; background: #fafbfc;
  border-left: 3px solid {ACCENT}; list-style: none;
}}
.rpt-points li {{ margin: 0 0 6px; font-size: 12.5px; padding-left: 11px; position: relative; }}
.rpt-points li:before {{ content: "·"; position: absolute; left: 0; color: {ACCENT}; font-weight: 700; }}
.rpt-points li:last-child {{ margin-bottom: 0; }}

.rpt-sec {{ margin-bottom: 15px; }}
.rpt-sec h3 {{
  font-size: 13.5px; font-weight: 700; color: {ACCENT}; margin: 0 0 6px;
  padding-left: 9px; border-left: 3px solid {ACCENT_LINE}; letter-spacing: -.01em;
}}
.rpt-sec p {{ margin: 0; font-size: 12.5px; text-align: justify; word-break: keep-all; }}

.rpt-half {{ border: 1px solid {RULE}; border-top: 2px solid {ACCENT}; padding: 11px 14px; }}
.rpt-half h4 {{ margin: 0 0 8px; font-size: 11.5px; font-weight: 700; color: {ACCENT};
  letter-spacing: .02em; }}
.rpt-half ul {{ margin: 0; padding-left: 16px; }}
.rpt-half li {{ font-size: 11.8px; margin-bottom: 5px; word-break: keep-all; }}

.rpt-foot {{
  margin-top: 12px; padding-top: 9px; border-top: 1px solid {RULE};
  font-size: 10px; color: {MUTED}; line-height: 1.55;
}}
</style>
"""


def _num(value, unit: str = "", scale: float = 1.0, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value / scale:,.{digits}f}{unit}"


def _signed(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    cls = "up" if value > 0 else "down" if value < 0 else ""
    return f'<span class="{cls}">{value:+.1f}%</span>'


def _growth(current, previous) -> str:
    if current is None or previous is None or pd.isna(current) or pd.isna(previous) or previous == 0:
        return "—"
    return _signed((current / previous - 1) * 100)


def _rows(pairs: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in pairs)
    return f'<table class="rpt-t">{body}</table>'


def header_html(row: pd.Series, result: dict) -> str:
    report = result["리포트"]
    date = result["생성시각"][:10].replace("-", ".")
    return f"""{CSS}
<div class="rpt">
  <div class="rpt-top"></div>
  <div class="rpt-band">
    <span class="rpt-brand">AI Company Report</span>
    <span>{date} &nbsp;·&nbsp; {row['시장구분']} &nbsp;·&nbsp; 기업분석</span>
  </div>
  <div class="rpt-inner" style="padding-bottom:0">
    <div class="rpt-title">
      <p class="rpt-name">{row['종목명']} <small>({row['종목코드']})</small></p>
      <div class="rpt-meta">
        분석관점 <b>{result['관점']}</b> · {result['분량']}<br>
        {result['모델']}<br>
        투자의견·목표주가 미제공
      </div>
    </div>
    <p class="rpt-headline">{report['헤드라인']}</p>
  </div>
</div>"""


def yearly_table_html(row: pd.Series) -> str:
    """요약 실적 3개년 추이. 증권사 리포트의 표준 구성 요소."""
    base = row.get("기준연도")
    if pd.isna(base):
        return ""
    base = int(base)
    years = [base - 2, base - 1, base]
    suffixes = ["_전전기", "_전기", ""]
    accounts = ["매출액", "영업이익", "당기순이익"]

    if all(pd.isna(row.get(f"{a}{s}")) for a in accounts for s in suffixes):
        return ""

    head = "".join(f"<th>{y}</th>" for y in years) + "<th>전년비</th>"
    body = ""
    for account in accounts:
        values = [row.get(f"{account}{s}") for s in suffixes]
        cells = "".join(f"<td>{_num(v, '', 1e8)}</td>" for v in values)
        body += f"<tr><td>{account}</td>{cells}<td>{_growth(values[2], values[1])}</td></tr>"

    margins = ""
    for label, numerator in [("영업이익률", "영업이익"), ("순이익률", "당기순이익")]:
        cells = ""
        for suffix in suffixes:
            top, bottom = row.get(f"{numerator}{suffix}"), row.get(f"매출액{suffix}")
            ok = not (pd.isna(top) or pd.isna(bottom) or bottom == 0)
            cells += f"<td>{f'{top / bottom * 100:.1f}%' if ok else '—'}</td>"
        margins += f"<tr><td>{label}</td>{cells}<td>—</td></tr>"

    return f"""{CSS}
<div class="rpt-box">
  <h4>요약 실적 (억원)</h4>
  <table class="rpt-yr">
    <tr><th>구분</th>{head}</tr>
    {body}{margins}
  </table>
</div>"""


def metrics_html(row: pd.Series, perf: dict | None, tech: dict | None) -> str:
    price = [
        ("현재주가", _num(row.get("현재가"), "원")),
        ("시가총액", _num(row.get("시가총액"), "억원", 1e8)),
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

    blocks = [CSS, '<div class="rpt-box"><h4>주가 정보</h4>' + _rows(price) + "</div>"]
    if perf:
        blocks.append(
            '<div class="rpt-box"><h4>주가 등락률</h4>'
            + _rows([(k, _signed(v)) for k, v in perf.items()])
            + "</div>"
        )
    blocks.append('<div class="rpt-box"><h4>투자지표</h4>' + _rows(valuation) + "</div>")
    return "".join(blocks)


def body_html(result: dict) -> str:
    report = result["리포트"]
    points = "".join(f"<li>{p}</li>" for p in report["핵심포인트"])
    sections = "".join(
        f'<div class="rpt-sec"><h3>{s["소제목"]}</h3><p>{s["본문"]}</p></div>'
        for s in report["섹션"]
    )
    return f"""{CSS}
<div class="rpt"><div class="rpt-inner">
  <ul class="rpt-points">{points}</ul>
  {sections}
</div></div>"""


def footer_html(result: dict) -> str:
    report = result["리포트"]
    checks = "".join(f"<li>{c}</li>" for c in report["체크포인트"])
    risks = "".join(f"<li>{r}</li>" for r in report["리스크요인"])
    return f"""{CSS}
<div style="display:flex; gap:12px; margin-bottom:12px">
  <div class="rpt-half" style="flex:1"><h4>투자자가 확인해야 할 점</h4><ul>{checks}</ul></div>
  <div class="rpt-half" style="flex:1"><h4>리스크 요인</h4><ul>{risks}</ul></div>
</div>
<div class="rpt"><div class="rpt-inner" style="padding:12px 16px">
  <div style="font-size:11.5px"><b>이 리포트가 보지 못한 것</b><br>{report['데이터한계']}</div>
  <div class="rpt-foot">{result['면책']}</div>
</div></div>"""
