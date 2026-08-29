"""리포트를 증권사 리포트 레이아웃으로 렌더링한다.

실제 리포트의 시각 문법을 따른다.
  - 상단 헤더 밴드와 액센트 라인
  - 종목명(코드) 큰 제목 + 한 줄 헤드라인
  - 좌측 지표 박스(현재가·시총·등락률·재무요약), 우측 본문 2단 구성
  - 소제목은 좌측 컬러 바로 구분하고 본문은 촘촘하게

투자의견·목표주가 자리에는 넣을 수 없으므로, 그 자리를 핵심 지표가 차지한다.
"""
import pandas as pd

ACCENT = "#1a4d8f"
ACCENT_SOFT = "#e8eef7"
INK = "#1a1a1a"
MUTED = "#6b6b6b"
RULE = "#d8d8d8"
UP = "#c0392b"
DOWN = "#1f5fa8"

CSS = f"""
<style>
.rpt {{
  font-family: "Malgun Gothic", "맑은 고딕", -apple-system, sans-serif;
  color: {INK}; font-size: 13px; line-height: 1.65;
  background: #fff; border: 1px solid {RULE}; border-top: 3px solid {ACCENT};
  padding: 18px 22px 20px;
}}
.rpt-band {{
  display: flex; justify-content: space-between; align-items: baseline;
  border-bottom: 1px solid {RULE}; padding-bottom: 8px; margin-bottom: 14px;
  font-size: 11px; color: {MUTED}; letter-spacing: .02em;
}}
.rpt-brand {{ font-weight: 700; color: {ACCENT}; font-size: 12px; }}
.rpt-name {{ font-size: 24px; font-weight: 700; color: {ACCENT}; margin: 0 0 2px; }}
.rpt-name small {{ font-size: 16px; font-weight: 600; color: {MUTED}; }}
.rpt-headline {{
  font-size: 15px; font-weight: 600; color: {INK};
  margin: 0 0 6px; padding-bottom: 12px; border-bottom: 1px solid {RULE};
}}
.rpt-byline {{ font-size: 11px; color: {MUTED}; text-align: right; margin: -22px 0 14px; }}

.rpt-box {{ border: 1px solid {RULE}; margin-bottom: 12px; }}
.rpt-box h4 {{
  margin: 0; padding: 5px 9px; font-size: 11px; font-weight: 700;
  background: {ACCENT_SOFT}; color: {ACCENT}; border-bottom: 1px solid {RULE};
  letter-spacing: .03em;
}}
table.rpt-t {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
table.rpt-t td {{ padding: 3.5px 9px; border-bottom: 1px solid #f0f0f0; }}
table.rpt-t td:first-child {{ color: {MUTED}; }}
table.rpt-t td:last-child {{ text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }}
table.rpt-t tr:last-child td {{ border-bottom: none; }}
.up {{ color: {UP}; }} .down {{ color: {DOWN}; }}

.rpt-points {{ margin: 0 0 16px; padding: 11px 14px; background: #fafafa; border-left: 3px solid {ACCENT}; }}
.rpt-points li {{ margin: 0 0 5px 0; font-size: 12.5px; }}
.rpt-points li:last-child {{ margin-bottom: 0; }}

.rpt-sec {{ margin-bottom: 15px; }}
.rpt-sec h3 {{
  font-size: 14px; font-weight: 700; color: {ACCENT}; margin: 0 0 5px;
  padding-left: 8px; border-left: 3px solid {ACCENT};
}}
.rpt-sec p {{ margin: 0; font-size: 12.5px; text-align: justify; }}

.rpt-half {{ border: 1px solid {RULE}; padding: 10px 13px; height: 100%; }}
.rpt-half h4 {{ margin: 0 0 7px; font-size: 12px; font-weight: 700; color: {ACCENT}; }}
.rpt-half li {{ font-size: 12px; margin-bottom: 5px; }}
.rpt-half ul {{ margin: 0; padding-left: 17px; }}

.rpt-foot {{
  margin-top: 14px; padding-top: 9px; border-top: 1px solid {RULE};
  font-size: 10.5px; color: {MUTED}; line-height: 1.5;
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


def _rows(pairs: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in pairs)
    return f'<table class="rpt-t">{body}</table>'


def header_html(row: pd.Series, result: dict) -> str:
    report = result["리포트"]
    return f"""{CSS}
<div class="rpt">
  <div class="rpt-band">
    <span class="rpt-brand">AI COMPANY REPORT</span>
    <span>{result['생성시각'][:10].replace('-', '.')} &nbsp;|&nbsp; {row['시장구분']} &nbsp;|&nbsp; 기업분석</span>
  </div>
  <p class="rpt-name">{row['종목명']} <small>({row['종목코드']})</small></p>
  <p class="rpt-headline">{report['헤드라인']}</p>
  <div class="rpt-byline">
    {result['관점']} 관점 · {result['분량']} · {result['모델']}
  </div>
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
            ("기간 최고", _num(tech.get("기간고가"), "원")),
            ("기간 최저", _num(tech.get("기간저가"), "원")),
        ]

    valuation = [
        ("PER", _num(row.get("PER"), "배", digits=2)),
        ("ROE", _num(row.get("ROE_계산"), "%", digits=2)),
        ("부채비율", _num(row.get("부채비율"), "%", digits=2)),
        ("영업이익률", _num(row.get("영업이익률"), "%", digits=2)),
    ]
    financials = [
        ("매출액", _num(row.get("매출액"), "", 1e8)),
        ("영업이익", _num(row.get("영업이익"), "", 1e8)),
        ("당기순이익", _num(row.get("당기순이익"), "", 1e8)),
        ("자산총계", _num(row.get("자산총계"), "", 1e8)),
        ("자본총계", _num(row.get("자본총계"), "", 1e8)),
    ]

    blocks = [
        CSS,
        '<div class="rpt-box"><h4>주가 정보</h4>' + _rows(price) + "</div>",
    ]
    if perf:
        rows = [(k, _signed(v)) for k, v in perf.items()]
        blocks.append('<div class="rpt-box"><h4>주가 등락률</h4>' + _rows(rows) + "</div>")
    blocks.append('<div class="rpt-box"><h4>투자지표</h4>' + _rows(valuation) + "</div>")
    blocks.append(
        f'<div class="rpt-box"><h4>재무요약 ({row.get("기준연도", "")}, 억원)</h4>'
        + _rows(financials)
        + "</div>"
    )
    return "".join(blocks)


def body_html(result: dict) -> str:
    report = result["리포트"]
    points = "".join(f"<li>{p}</li>" for p in report["핵심포인트"])
    sections = "".join(
        f'<div class="rpt-sec"><h3>{s["소제목"]}</h3><p>{s["본문"]}</p></div>'
        for s in report["섹션"]
    )
    return f"""{CSS}
<div class="rpt" style="border-top-width:1px">
  <ul class="rpt-points">{points}</ul>
  {sections}
</div>"""


def footer_html(result: dict) -> str:
    report = result["리포트"]
    checks = "".join(f"<li>{c}</li>" for c in report["체크포인트"])
    risks = "".join(f"<li>{r}</li>" for r in report["리스크요인"])
    return f"""{CSS}
<div style="display:flex; gap:12px; margin-bottom:12px">
  <div class="rpt-half" style="flex:1">
    <h4>투자자가 확인해야 할 점</h4><ul>{checks}</ul>
  </div>
  <div class="rpt-half" style="flex:1">
    <h4>리스크 요인</h4><ul>{risks}</ul>
  </div>
</div>
<div class="rpt" style="border-top-width:1px; padding:12px 16px">
  <div style="font-size:11.5px"><b>이 리포트가 보지 못한 것</b><br>{report['데이터한계']}</div>
  <div class="rpt-foot">{result['면책']}</div>
</div>"""
