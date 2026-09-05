"""리포트를 증권사 리포트 레이아웃으로 렌더링한다.

실제 리포트의 시각 문법을 따른다.
  - 상단 헤더 밴드와 액센트 라인
  - 종목명(코드) 큰 제목 + 한 줄 헤드라인
  - 좌측 지표 박스(주가·등락률·투자지표), 우측 본문 2단 구성
  - 요약 실적 3개년 추이표 (증권사 리포트의 표준 요소)
  - 소제목은 좌측 컬러 바로 구분하고 본문은 촘촘하게

투자의견·목표주가 자리에는 넣을 수 없으므로, 그 자리를 핵심 지표가 차지한다.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.analysis.money import money, price as money_price, unit_of as money_unit  # noqa: E402

ACCENT = "#12386b"
ACCENT_LINE = "#1a4d8f"
ACCENT_SOFT = "#f2f5fa"
PAPER = "#ffffff"
INK = "#14161a"
BODY = "#33383f"
MUTED = "#6e7480"
RULE = "#d7dae0"
HAIR = "#ecedf1"
UP = "#c0392b"
DOWN = "#1f5fa8"
OK = "#2f6b52"
OK_SOFT = "#eef5f1"
WARN = "#9d6b1f"
WARN_SOFT = "#faf3e6"

CSS = f"""
<style>
/* 한 장의 지면처럼 보이는 것이 이 스타일의 목표다.

   Streamlit은 st.html을 부를 때마다 별도 블록을 만든다. 조각마다 테두리를 두르면
   리포트가 아니라 카드 대시보드처럼 보이므로, 조각에는 테두리를 두지 않고 흰 지면
   위에 얇은 괘선으로만 구획을 나눈다. 배경색은 모든 면에 명시한다. 이용자가 다크
   테마로 바꾸면 배경을 지정하지 않은 상자가 어두워지면서 검은 글자가 사라진다. */

.rpt {{
  font-family: "Pretendard", "Malgun Gothic", "맑은 고딕",
               "Apple SD Gothic Neo", system-ui, sans-serif;
  color: {BODY}; font-size: 13px; line-height: 1.72;
  background: {PAPER}; -webkit-font-smoothing: antialiased;
}}
.rpt-inner {{ padding: 0 2px; }}
.rpt-top {{ height: 3px; background: {ACCENT}; }}
.rpt-band {{
  display: flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: 4px 12px;
  border-bottom: 1px solid {HAIR}; padding: 9px 2px 7px;
  font-size: 10.5px; color: {MUTED}; letter-spacing: .08em; text-transform: uppercase;
}}
.rpt-brand {{ font-weight: 800; color: {ACCENT}; letter-spacing: .14em; }}

.rpt-title {{
  display: flex; justify-content: space-between; align-items: flex-end;
  gap: 8px 20px; flex-wrap: wrap; padding-top: 14px;
}}
.rpt-name {{
  font-size: 28px; font-weight: 800; color: {ACCENT}; margin: 0;
  letter-spacing: -.03em; line-height: 1.15;
}}
.rpt-name small {{ font-size: 15px; font-weight: 600; color: {MUTED}; letter-spacing: 0; }}
.rpt-meta {{
  font-size: 10.5px; color: {MUTED}; text-align: right; line-height: 1.75;
  white-space: nowrap;
}}
.rpt-headline {{
  font-size: 17px; font-weight: 700; color: {INK}; margin: 10px 0 0;
  padding-bottom: 13px; border-bottom: 2px solid {ACCENT};
  letter-spacing: -.02em; line-height: 1.5; word-break: keep-all;
}}

/* 수치 상자 - 표는 담아 두는 편이 읽기 쉬우므로 여기만 테두리를 남긴다 */
.rpt-box {{
  border: 1px solid {RULE}; background: {PAPER};
  margin-bottom: 10px; overflow: hidden;
}}
.rpt-box h4 {{
  margin: 0; padding: 6px 11px; font-size: 10.5px; font-weight: 700;
  background: {ACCENT_SOFT}; color: {ACCENT}; border-bottom: 1px solid {RULE};
  letter-spacing: .08em;
}}
.rpt-scroll {{ overflow-x: auto; }}

table.rpt-t {{ width: 100%; border-collapse: collapse; font-size: 12px; background: {PAPER}; }}
table.rpt-t td {{ padding: 5px 11px; border-bottom: 1px solid {HAIR}; }}
table.rpt-t td:first-child {{ color: {MUTED}; white-space: nowrap; }}
table.rpt-t td:last-child {{
  text-align: right; font-weight: 700; color: {INK};
  font-variant-numeric: tabular-nums; white-space: nowrap;
}}
table.rpt-t tr:last-child td {{ border-bottom: none; }}

table.rpt-yr {{ width: 100%; border-collapse: collapse; font-size: 12px; background: {PAPER}; }}
table.rpt-yr th {{
  background: {ACCENT_SOFT}; color: {ACCENT}; font-size: 10.5px; font-weight: 700;
  padding: 6px 9px; border-bottom: 1px solid {RULE}; text-align: right; white-space: nowrap;
}}
table.rpt-yr th:first-child {{ text-align: left; }}
table.rpt-yr td {{
  padding: 5px 9px; border-bottom: 1px solid {HAIR}; text-align: right;
  font-variant-numeric: tabular-nums; color: {INK}; font-weight: 600; white-space: nowrap;
}}
table.rpt-yr td:first-child {{ text-align: left; color: {MUTED}; font-weight: 400; }}
table.rpt-yr tr:last-child td {{ border-bottom: none; }}

.up {{ color: {UP}; }} .down {{ color: {DOWN}; }}

/* 핵심포인트 - 리포트에서 가장 먼저 읽히는 자리라 지면과 톤을 다르게 준다 */
.rpt-points {{
  margin: 2px 0 20px; padding: 14px 18px 14px 20px; background: {ACCENT_SOFT};
  border-left: 3px solid {ACCENT}; list-style: none;
}}
.rpt-points li {{
  margin: 0 0 8px; font-size: 13px; line-height: 1.65; padding-left: 13px;
  position: relative; word-break: keep-all; color: {INK};
}}
.rpt-points li:before {{
  content: ""; position: absolute; left: 0; top: .62em;
  width: 4px; height: 4px; border-radius: 50%; background: {ACCENT};
}}
.rpt-points li:last-child {{ margin-bottom: 0; }}

.rpt-sec {{ margin-bottom: 19px; }}
.rpt-sec h3 {{
  font-size: 14.5px; font-weight: 700; color: {ACCENT}; margin: 0 0 7px;
  padding-left: 10px; border-left: 3px solid {ACCENT_LINE};
  letter-spacing: -.02em; line-height: 1.45; word-break: keep-all;
}}
.rpt-sec p {{ margin: 0; font-size: 13px; line-height: 1.78; word-break: keep-all; }}

/* 체크포인트와 리스크 - 좁은 화면에서는 두 칸이 눌리므로 접어서 쌓는다 */
.rpt-cols {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }}
.rpt-half {{
  flex: 1 1 260px; min-width: 0; background: {PAPER};
  border: 1px solid {RULE}; border-top: 2px solid {ACCENT}; padding: 12px 15px;
}}
.rpt-half h4 {{
  margin: 0 0 9px; font-size: 11px; font-weight: 700; color: {ACCENT};
  letter-spacing: .06em;
}}
.rpt-half ul {{ margin: 0; padding-left: 17px; }}
.rpt-half li {{ font-size: 12.3px; line-height: 1.65; margin-bottom: 6px; word-break: keep-all; }}
.rpt-half li:last-child {{ margin-bottom: 0; }}

/* 숫자 대조 결과 - 이 리포트가 다른 AI 리포트와 다른 점이라 눈에 띄게 둔다 */
.rpt-verify {{
  font-size: 12px; line-height: 1.6; padding: 10px 14px; margin-bottom: 12px;
  border: 1px solid {RULE}; border-left: 3px solid {OK}; background: {OK_SOFT};
  color: {INK}; word-break: keep-all;
}}
.rpt-verify.warn {{ border-left-color: {WARN}; background: {WARN_SOFT}; }}
.rpt-verify .hint {{ margin-top: 5px; font-size: 11px; color: {MUTED}; }}

.rpt-note {{
  background: {PAPER}; border: 1px solid {RULE}; padding: 13px 16px;
}}
.rpt-note b {{ color: {ACCENT}; font-size: 11px; letter-spacing: .06em; }}
.rpt-note div.body {{ font-size: 12.3px; line-height: 1.7; margin-top: 5px; word-break: keep-all; }}
.rpt-foot {{
  margin-top: 11px; padding-top: 10px; border-top: 1px solid {HAIR};
  font-size: 10.5px; color: {MUTED}; line-height: 1.6;
}}

@media (max-width: 640px) {{
  .rpt-name {{ font-size: 23px; }}
  .rpt-headline {{ font-size: 15px; }}
  .rpt-meta {{ text-align: left; }}
}}
</style>
"""


def _num(value, unit: str = "", scale: float = 1.0, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value / scale:,.{digits}f}{unit}"


def shares(value) -> str:
    """상장주식수. 수집기가 이미 천주 단위로 저장하므로 다시 나누면 안 된다.

    표시할 때 한 번 더 1,000으로 나누는 바람에 삼성전자 발행주식수가
    5,846천주(실제 58억 주)로 나오고 있었다.
    """
    if value is None or pd.isna(value):
        return "—"

    count = int(round(float(value) * 1_000))
    if count >= 10**8:
        eok, rest = divmod(count, 10**8)
        man = rest // 10**4
        return f"{eok:,}억 {man:,}만주" if man else f"{eok:,}억주"
    if count >= 10**4:
        return f"{count // 10**4:,}만주"
    return f"{count:,}주"


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


def styles_html() -> str:
    """리포트 스타일. 한 번만 심으면 되므로 렌더 시작에서 한 번 호출한다."""
    return CSS


def header_html(row: pd.Series, result: dict) -> str:
    report = result["리포트"]
    date = result["생성시각"][:10].replace("-", ".")
    # 이 리포트가 언제까지 유효한지 알려 준다. 관점마다 다르다.
    from src.analysis.gemini_analyzer import cache_ttl

    ttl = cache_ttl(result.get("관점"))
    return f"""<div class="rpt">
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
        {date} 작성 · {ttl}일간 유효<br>
        투자의견·목표주가 미제공
      </div>
    </div>
    <p class="rpt-headline">{report['헤드라인']}</p>
  </div>
</div>"""


def yearly_table_html(row: pd.Series) -> str:
    """요약 실적 3개년 추이. 증권사 리포트의 표준 구성 요소."""
    currency = row.get("통화")
    if currency is None or pd.isna(currency):
        currency = "KRW"
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

    return f"""<div class="rpt-box">
  <h4>요약 실적 (억{money_unit(currency)})</h4>
  <div class="rpt-scroll"><table class="rpt-yr">
    <tr><th>구분</th>{head}</tr>
    {body}{margins}
  </table></div>
</div>"""


# 시장마다 제공되는 지표가 다르다. 값이 없는 줄은 표에 올리지 않는다.
VALUATION_FIELDS = [
    ("PER", "PER", "배"),
    ("PBR", "PBR", "배"),
    ("ROE_계산", "ROE", "%"),
    ("ROA", "ROA", "%"),
    ("부채비율", "부채비율", "%"),
    ("영업이익률", "영업이익률", "%"),
    ("배당수익률", "배당수익률", "%"),
]


def metrics_html(row: pd.Series, perf: dict | None, tech: dict | None) -> str:
    currency = row.get("통화")
    if currency is None or pd.isna(currency):
        currency = "KRW"
    unit = money_unit(currency)

    price = [
        ("현재주가", money_price(row.get("현재가"), currency, empty="—")),
        ("시가총액", money(row.get("시가총액"), currency, empty="—")),
    ]
    if pd.notna(row.get("상장주식수")):
        price.append(("발행주식수", shares(row.get("상장주식수"))))
    if pd.notna(row.get("외국인비율")):
        price.append(("외국인비율", _num(row.get("외국인비율"), "%", digits=2)))
    if tech:
        price += [
            ("1년 최고", _num(tech.get("기간고가"), unit)),
            ("1년 최저", _num(tech.get("기간저가"), unit)),
        ]

    valuation = [
        (label, _num(row.get(key), fmt_unit, digits=2))
        for key, label, fmt_unit in VALUATION_FIELDS
        if pd.notna(row.get(key))
    ]

    blocks = ['<div class="rpt-box"><h4>주가 정보</h4>' + _rows(price) + "</div>"]
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
    return f"""<div class="rpt"><div class="rpt-inner">
  <ul class="rpt-points">{points}</ul>
  {sections}
</div></div>"""


def verification_html(result: dict) -> str:
    """숫자 대조 결과. AI가 쓴 수치를 원본과 맞춰 봤다는 것을 독자에게 알린다.

    금융 리포트에서 가장 위험한 건 문장이 아니라 숫자다. 그래서 이 표시를
    본문 바로 아래, 면책 문구보다 위에 둔다.
    """
    checked = result.get("검증")
    if not checked:
        return ""

    total, matched = checked.get("전체", 0), checked.get("확인", 0)
    if not total:
        return ""

    unmatched = checked.get("미확인") or []
    if not unmatched:
        return (
            f'<div class="rpt-verify ok">✓ 숫자 대조 완료 — 본문의 수치 {matched}개가 '
            f"모두 원본 데이터와 일치합니다</div>"
        )

    items = ", ".join(f"<b>{u['표기']}</b>" for u in unmatched[:5])
    return (
        f'<div class="rpt-verify warn">⚠ 숫자 대조 — {total}개 중 {matched}개 확인. '
        f"원본에서 출처를 찾지 못한 수치: {items}"
        f'<div class="hint">직접 확인해보세요. 이 표시는 AI가 지어냈을 수 있는 숫자를 '
        f"기계로 걸러낸 결과입니다.</div></div>"
    )


def footer_html(result: dict) -> str:
    report = result["리포트"]
    checks = "".join(f"<li>{c}</li>" for c in report["체크포인트"])
    risks = "".join(f"<li>{r}</li>" for r in report["리스크요인"])
    return f"""<div class="rpt">
  <div class="rpt-cols">
    <div class="rpt-half"><h4>투자자가 확인해야 할 점</h4><ul>{checks}</ul></div>
    <div class="rpt-half"><h4>리스크 요인</h4><ul>{risks}</ul></div>
  </div>
  {verification_html(result)}
  <div class="rpt-note">
    <b>이 리포트가 보지 못한 것</b>
    <div class="body">{report['데이터한계']}</div>
    <div class="rpt-foot">{result['면책']}</div>
  </div>
</div>"""


def issues_html(issues: list[dict]) -> str:
    """주요 이슈를 일자·구분과 함께 시간순으로 보여준다."""
    if not issues:
        return ""
    rows = ""
    for item in sorted(issues, key=lambda x: str(x.get("일자", "")), reverse=True):
        kind = item.get("구분", "")
        tone = ACCENT if kind == "공시" else MUTED
        rows += f"""
        <tr>
          <td class="d">{item.get('일자', '')}</td>
          <td><span class="k" style="border-color:{tone}; color:{tone}">{kind}</span></td>
          <td>
            <div class="t">{item.get('제목', '')}</div>
            <div class="i">{item.get('인사이트', '')}</div>
          </td>
        </tr>"""
    return f"""<div class="rpt-box">
  <h4>최근 주요 이슈</h4>
  <style>
    table.rpt-iss {{ width:100%; border-collapse:collapse; font-size:12px; background:{PAPER}; }}
    table.rpt-iss td {{ padding:8px 10px; border-bottom:1px solid {HAIR}; vertical-align:top; }}
    table.rpt-iss tr:last-child td {{ border-bottom:none; }}
    table.rpt-iss td.d {{ color:{MUTED}; white-space:nowrap; font-variant-numeric:tabular-nums; width:88px; }}
    table.rpt-iss .k {{ display:inline-block; font-size:10px; padding:1px 6px;
      border:1px solid; border-radius:2px; white-space:nowrap; }}
    table.rpt-iss .t {{ font-weight:700; color:{INK}; margin-bottom:2px; }}
    table.rpt-iss .i {{ color:{BODY}; font-size:11.5px; word-break:keep-all; }}
  </style>
  <div class="rpt-scroll"><table class="rpt-iss">{rows}</table></div>
</div>"""
