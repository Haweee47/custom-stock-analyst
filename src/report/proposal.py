"""대회 제출용 기획서를 PDF로 만든다.

본선 심사가 제출물 100%라, 만든 것이 서류에 안 적히면 없는 것과 같다.
숫자는 전부 실제 데이터에서 뽑아 쓴다. 기획서에 적은 수치가 틀리면
이 서비스가 내세우는 것과 정면으로 어긋난다.

xhtml2pdf는 flexbox를 지원하지 않으므로 레이아웃을 표로 짠다.
한글은 저장소에 담은 나눔고딕을 reportlab에 직접 등록해 쓴다.
"""
import sys
from pathlib import Path

from xhtml2pdf import pisa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.report.report_pdf import _register_font  # noqa: E402

INK = "#14171c"
ACCENT = "#12386b"
ACCENT_SOFT = "#eef2f8"
RULE = "#d5d8dd"
HAIR = "#e9ebef"
MUTED = "#5f6672"
WARN = "#9d3b36"
WARN_SOFT = "#fbf4f3"

CSS = f"""
@page {{ size: A4; margin: 15mm 14mm 14mm 14mm; }}
body {{ font-family: "Nanum"; font-size: 9.3pt; color: {INK}; line-height: 1.6; }}

.tag {{ font-size: 7.6pt; color: {ACCENT}; letter-spacing: 1pt; margin-bottom: 2pt; }}
h1 {{ font-size: 21pt; color: {ACCENT}; margin: 0 0 3pt; letter-spacing: -.5pt; }}
.sub {{ font-size: 10.5pt; color: {INK}; margin: 0 0 8pt; }}
.meta {{ font-size: 7.8pt; color: {MUTED}; border-top: 2.2pt solid {ACCENT};
         padding-top: 5pt; margin-bottom: 11pt; }}

table.kpi {{ border-collapse: collapse; width: 100%; margin-bottom: 12pt; }}
table.kpi td {{ width: 25%; background: {ACCENT_SOFT}; border: 1.5pt solid #ffffff;
                padding: 7pt 6pt; text-align: center; }}
.num {{ font-size: 14pt; color: {ACCENT}; font-weight: bold; }}
.cap {{ font-size: 7.4pt; color: {MUTED}; }}

h2 {{ font-size: 11.5pt; color: {ACCENT}; margin: 14pt 0 5pt;
      border-bottom: 1pt solid {ACCENT}; padding-bottom: 3pt; }}
h3 {{ font-size: 9.6pt; color: {INK}; margin: 9pt 0 3pt; }}
p {{ margin: 0 0 6pt; }}
ul {{ margin: 0 0 7pt 0; padding-left: 13pt; }}
li {{ margin-bottom: 3.5pt; }}

.pull {{ background: {ACCENT_SOFT}; border-left: 3pt solid {ACCENT};
         padding: 8pt 10pt; margin: 7pt 0 9pt; font-size: 9.6pt; }}
.flag {{ background: {WARN_SOFT}; border-left: 3pt solid {WARN};
         padding: 7pt 10pt; margin: 6pt 0 8pt; }}
.note {{ font-size: 7.8pt; color: {MUTED}; margin: -2pt 0 8pt; }}

table {{ border-collapse: collapse; width: 100%; margin: 5pt 0 9pt; }}
th {{ background: {ACCENT}; color: #ffffff; font-size: 8.2pt; padding: 4pt 6pt;
      text-align: left; }}
td {{ font-size: 8.6pt; padding: 4pt 6pt; border-bottom: .5pt solid {HAIR};
      vertical-align: top; }}
td.n {{ text-align: right; }}
tr.hi td {{ background: {WARN_SOFT}; }}

pre {{ font-family: "Nanum"; background: #f6f7f9; border: .5pt solid {RULE};
       padding: 7pt 9pt; font-size: 7.9pt; line-height: 1.45; margin: 4pt 0 8pt; }}
"""


def _rows(items: list[tuple], highlight: int | None = None) -> str:
    """표 본문. 첫 칸은 왼쪽, 나머지는 오른쪽 정렬한다."""
    body = ""
    for index, row in enumerate(items):
        cells = "".join(
            f'<td class="n">{cell}</td>' if position else f"<td>{cell}</td>"
            for position, cell in enumerate(row)
        )
        klass = ' class="hi"' if highlight is not None and index == highlight else ""
        body += f"<tr{klass}>{cells}</tr>"
    return body


def kpi(items: list[tuple[str, str]]) -> str:
    """맨 위 네 칸 요약. 심사자가 첫 화면에서 규모를 파악하게 한다."""
    cells = "".join(
        f'<td><div class="num">{value}</div><div class="cap">{label}</div></td>'
        for value, label in items
    )
    return f'<table class="kpi"><tr>{cells}</tr></table>'


def build_html(facts: dict) -> str:
    return f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>

<div class="tag">2026 금융 AI CHALLENGE</div>
<h1>리포트 셀프바</h1>
<p class="sub">애널리스트가 다루지 않는 종목까지, 오늘 데이터로 만드는 AI 기업 리포트</p>
<div class="meta">
{facts['team']} &nbsp;·&nbsp; {facts['date']} &nbsp;·&nbsp;
서비스 {facts['url']} &nbsp;·&nbsp; 소스 {facts['repo']}
</div>

{facts['kpi']}

<div class="pull">
증권사 리포트는 대형주에 쏠려 있습니다. 시가총액 1천억 원 미만 종목은
<b>{facts['gap_headline']}가 최근 3개월 안에 나온 리포트가 없습니다.</b>
정보가 가장 부족한 종목에서 투자자는 근거 없이 판단하게 됩니다.<br/><br/>
리포트 셀프바는 <b>{facts['markets']}개 시장 {facts['stocks']}종목</b> 어디든
오늘 데이터로 리포트를 즉시 만듭니다.
</div>

<h2>1. 문제 — 정보가 필요한 종목일수록 리포트가 없다</h2>
<p>
국내 상장사를 시가총액 구간별로 표본 조사해, 증권사 리포트가 있는지와
그것이 최근 3개월 안에 나온 것인지를 셌습니다.
</p>
<table>
<tr><th>시가총액 구간</th><th style="width:13%">표본</th>
    <th style="width:19%">리포트 있음</th><th style="width:22%">최근 3개월 내</th></tr>
{facts['coverage_rows']}
</table>
<p class="note">
{facts['coverage_date']} 측정 · 출처 네이버 금융 종목별 증권사 리포트 ·
각 구간의 시가총액 상위 종목을 표본으로 삼았으므로 구간 전체의 실제 커버리지는 이보다 낮습니다.
</p>

<div class="flag">
<b>오래된 리포트는 없는 것과 같습니다.</b> 소형주는 60%가 리포트를 갖고 있지만
최근 3개월 내 것은 38%뿐입니다. 실적이 두 번 발표된 뒤의 분석은 지금의 회사를
설명하지 못합니다.
</div>

<p>
해외 투자도 같습니다. 국내 투자자의 해외 주식 거래는 늘었지만 <b>한국어로 된 개별 종목
분석은 소수 대형주에만</b> 있습니다. 그래서 미국·일본·중국을 함께 담았습니다.
</p>

<h2>2. 해결 — 전 종목, 오늘 데이터, 즉시 생성</h2>
<p>
공개 데이터를 매일 자동으로 모아 두고, 이용자가 종목을 열면 그 자리에서 리포트를
만듭니다. 사람이 쓰지 않으므로 종목 수가 늘어도 같은 품질로 제공됩니다.
</p>
<table>
<tr><th>기능</th><th style="width:54%">내용</th></tr>
{facts['features']}
</table>
<p>
관점과 분량을 골라 볼 수 있습니다. 재무 중심(펀더멘탈), 주가 흐름(기술적),
뉴스·공시(이슈·트렌드), 셋을 묶은 종합 중에서 고르고, 압축형과 상세형 중에서 고릅니다.
같은 종목이라도 무엇이 궁금한지에 따라 다른 리포트가 나옵니다.
</p>

<h2>3. 넘어야 했던 것 — AI가 쓴 숫자는 조용히 틀린다</h2>
<p>
사람이 검수하지 않는 금융 문서를 내보내는 일입니다. 개발 과정에서 생성된 리포트의
수치 오류를 <b>{facts['bug_count']}종</b> 발견했고, 모두 <b>문장이 완벽하고 화면에
오류가 나지 않는</b> 종류였습니다.
</p>
<table>
<tr><th>오류 유형</th><th style="width:44%">실제로 발견한 사례</th></tr>
{facts['bug_rows']}
</table>

<h3>대책 1 — 계산은 AI에게 맡기지 않습니다</h3>
<p>
증감률, 영업레버리지, 이익 변화의 요인 분해, 원가율·판관비율, 업종 중앙값 대비 위치를
코드가 계산해 넘깁니다. 모델은 계산하지 않고 서술만 합니다.
</p>
<pre>{facts['trend_sample']}</pre>

<h3>대책 2 — 없는 데이터는 감춥니다</h3>
<p>
시장마다 제공 항목이 다릅니다. 해외는 자산·부채·자본총계가 없어 부채비율과 ROE를
구할 수 없고 공시·뉴스도 없습니다. 빈칸으로 넘기면 모델이 그것을 근거처럼 다루므로
해당 블록을 아예 넣지 않고, 화면에서도 그 지표와 관점을 감춥니다.
회사 소개 역시 모델에게 맡기지 않고 외부 출처에서 받아 인용합니다.
</p>

<h3>대책 3 — 생성된 숫자를 원본과 대조합니다</h3>
<p>
리포트 본문의 금액과 비율을 모두 뽑아 원본에서 나올 수 있는 값과 맞춰 봅니다.
출처를 찾지 못하면 무엇이 어긋났는지 알려 주고 다시 생성하며, 그래도 남으면
숨기지 않고 화면에 표시합니다.
</p>
<pre>{facts['verify_sample']}</pre>

<h2>4. 구현 결과</h2>
<table>
<tr><th>항목</th><th style="width:20%">수치</th><th style="width:36%">비고</th></tr>
{facts['result_rows']}
</table>

<h2>5. 차별점</h2>
<ul>
<li><b>커버리지가 넓습니다.</b> 애널리스트가 다루지 않는 종목이 주 대상입니다.
    기존 리포트가 없는 종목일수록 이 서비스의 값어치가 큽니다.</li>
<li><b>항상 최신입니다.</b> 시세와 공시는 평일 자동 갱신되고 리포트는 열람 시점에
    생성됩니다. '언제 나온 리포트인가'를 따질 필요가 없습니다.</li>
<li><b>해외도 한국어로 봅니다.</b> 미국·일본·중국 종목을 같은 형식으로, 현지 통화
    표기와 함께 제공하며 원화 환산으로 시장을 가로질러 비교합니다.</li>
<li><b>숫자를 검산합니다.</b> 생성된 수치를 원본과 대조하고, 실패하면 재생성하거나
    화면에 표시합니다.</li>
<li><b>규제를 전제로 설계했습니다.</b> 불특정 다수 대상 종목 분석은 유사투자자문업
    이슈가 있어 투자의견·목표주가를 구조적으로 생성하지 않습니다. 응답 스키마에 해당
    항목 자체가 없고, 그 자리에는 '투자자가 확인해야 할 점'과 '리스크 요인'이 들어갑니다.</li>
</ul>

<h2>6. 운영 비용</h2>
<table>
<tr><th>구분</th><th style="width:18%">비용</th><th style="width:40%">근거</th></tr>
{facts['cost_rows']}
</table>
<p>
데이터 수집은 전액 무료입니다. 비용이 드는 구간은 리포트 생성뿐이며, 그중 76%가
출력 토큰에서 발생합니다. 캐시·일일 상한·분량별 상한 세 가지로 최악의 비용을 고정했습니다.
</p>

<h2>7. 확장 계획</h2>
<ul>
<li><b>공백부터 채우기</b> — 리포트가 없는 종목을 우선 생성 대상으로 삼으면 같은 비용으로
    더 큰 공백을 메웁니다. 현재는 시가총액 순으로 채우고 있습니다.</li>
<li><b>공시 원문 연결</b> — 지금은 공시 제목만 봅니다. 원문을 근거로 삼으면 '왜 그렇게
    됐는지'를 추측이 아니라 인용으로 답할 수 있습니다.</li>
<li><b>검증 엔진 분리</b> — 생성기와 떼어내면 금융 텍스트의 수치를 검산하는 모듈이 됩니다.
    사내 리서치 검수나 공시 요약 검증에 적용할 수 있습니다.</li>
<li><b>시장 확대</b> — 홍콩은 한 거래소에 통화가 섞이고 같은 회사가 중복 상장돼 있어
    보류했습니다. 중복 제거와 2차 상장 분리가 선행 과제입니다.</li>
</ul>

</body></html>"""


def render(facts: dict, out_path: Path) -> Path:
    _register_font()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        result = pisa.CreatePDF(build_html(facts), dest=handle, encoding="utf-8")
    if result.err:
        raise RuntimeError("기획서 PDF 생성 실패")
    return out_path
