"""대회 제출용 기획서를 PDF로 만든다.

본선 심사가 제출물 100%라, 만든 것이 서류에 안 적히면 없는 것과 같다.
숫자는 전부 실제 데이터에서 뽑아 쓴다. 기획서에 적은 수치가 틀리면
이 프로젝트가 말하는 것과 정면으로 어긋난다.

리포트 PDF와 같은 방식(xhtml2pdf + 나눔고딕)을 쓴다. xhtml2pdf는 flexbox를
지원하지 않으므로 표 기반으로 짠다.
"""
import sys
from pathlib import Path

from xhtml2pdf import pisa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.report.report_pdf import _register_font  # noqa: E402

ACCENT = "#12386b"
SOFT = "#eef2f8"
RULE = "#d5d8dd"
MUTED = "#6e7480"
OK = "#2f6b52"
WARN = "#9d3b36"

CSS = f"""
@page {{ size: A4; margin: 16mm 15mm 18mm 15mm; }}
body {{ font-family: "Nanum"; font-size: 9.4pt; color: #24272c; line-height: 1.62; }}

h1 {{ font-size: 20pt; color: {ACCENT}; margin: 0 0 2pt; }}
.sub {{ font-size: 10.5pt; color: {MUTED}; margin: 0 0 3pt; }}
.meta {{ font-size: 8pt; color: {MUTED}; border-bottom: 2pt solid {ACCENT};
         padding-bottom: 7pt; margin-bottom: 12pt; }}

h2 {{ font-size: 12pt; color: {ACCENT}; margin: 15pt 0 5pt;
      border-left: 3pt solid {ACCENT}; padding-left: 6pt; }}
h3 {{ font-size: 10pt; color: #1a1c20; margin: 9pt 0 3pt; }}
p {{ margin: 0 0 6pt; }}
ul {{ margin: 0 0 7pt 0; padding-left: 14pt; }}
li {{ margin-bottom: 3pt; }}

.lead {{ background: {SOFT}; border-left: 3pt solid {ACCENT}; padding: 9pt 11pt;
         margin-bottom: 11pt; font-size: 9.8pt; }}
.callout {{ border: .6pt solid {RULE}; border-left: 3pt solid {WARN};
            padding: 8pt 10pt; margin: 7pt 0; background: #fdf9f8; }}
.note {{ font-size: 8.4pt; color: {MUTED}; margin-top: 3pt; }}

table {{ border-collapse: collapse; width: 100%; margin: 6pt 0 9pt; }}
th {{ background: {SOFT}; color: {ACCENT}; font-size: 8.4pt; padding: 4pt 6pt;
      border-bottom: .8pt solid {RULE}; text-align: left; }}
td {{ font-size: 8.8pt; padding: 4pt 6pt; border-bottom: .5pt solid #edeff2;
      vertical-align: top; }}
td.n {{ text-align: right; }}
.ok {{ color: {OK}; font-weight: bold; }}
.bad {{ color: {WARN}; font-weight: bold; }}

/* pre는 기본 monospace로 떨어지는데 그 폰트에 한글 글리프가 없어 네모로 깨진다 */
pre {{ font-family: "Nanum"; background: #f7f8fa; border: .6pt solid {RULE};
       padding: 7pt 9pt; font-size: 8pt; line-height: 1.5; margin: 5pt 0 8pt; }}
.foot {{ margin-top: 14pt; padding-top: 6pt; border-top: .6pt solid {RULE};
         font-size: 7.6pt; color: {MUTED}; }}
"""


def _rows(items: list[tuple]) -> str:
    body = ""
    for row in items:
        cells = "".join(
            f'<td class="n">{c}</td>' if index else f"<td>{c}</td>"
            for index, c in enumerate(row)
        )
        body += f"<tr>{cells}</tr>"
    return body


def build_html(facts: dict) -> str:
    """기획서 본문. facts에는 실제 측정값만 넣는다."""
    return f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>

<h1>커버리지 밖의 종목에도 오늘자 리포트를</h1>
<p class="sub">애널리스트가 다루지 않는 종목까지, 최신 데이터로 즉시 생성하는 AI 기업 리포트</p>
<div class="meta">
  2026 금융 AI Challenge 기획서 &nbsp;|&nbsp; 서비스명 <b>리포트 셀프바</b>
  &nbsp;|&nbsp; 배포 {facts['url']} &nbsp;|&nbsp; 작성일 {facts['date']}
</div>

<div class="lead">
<b>한 줄 요약</b><br>
증권사 리포트는 대형주에 쏠려 있습니다. 초소형주는 <b>{facts['gap_headline']}</b>가
최근 3개월 안에 나온 리포트가 없습니다. 투자자는 판단 근거 없이 종목을 고르게 됩니다.<br>
이 서비스는 <b>{facts['markets']}개 시장 {facts['stocks']}종목</b> 어디든, 오늘 데이터로
리포트를 즉시 만들어 줍니다. AI가 쓴 숫자는 원본과 기계로 대조해 검산합니다.
</div>

<h2>1. 문제 — 리포트가 없는 종목이 대부분이다</h2>
<p>
국내 상장사를 시가총액 구간별로 표본 조사했습니다. 증권사 리포트가 존재하는지,
그리고 그것이 최근 3개월 안에 나온 것인지를 셌습니다.
</p>
<table>
<tr><th>시가총액 구간</th><th style="width:15%">표본</th><th style="width:19%">리포트 있음</th>
    <th style="width:22%">최근 3개월 내</th></tr>
{facts['coverage_rows']}
</table>
<p class="note">
{facts['coverage_date']} 측정 · 출처: 네이버 금융 종목별 증권사 리포트 목록 ·
각 구간의 시가총액 <b>상위</b> 종목을 표본으로 잡았으므로, 구간 전체의 실제 커버리지는
이 수치보다 낮습니다.
</p>
<div class="callout">
<b>리포트가 있어도 오래된 것이면 소용이 없습니다.</b> 실적이 두 번 발표된 뒤의 리포트는
지금의 회사를 설명하지 못합니다. 위 표에서 '리포트 있음'과 '최근 3개월 내'의 차이가
그만큼입니다. 소형주는 60%가 리포트를 갖고 있지만 최신인 것은 38%뿐입니다.
</div>
<p>
해외 투자도 같은 문제입니다. 한국 개인 투자자의 해외 주식 투자는 늘었지만,
<b>한국어로 된 개별 종목 분석은 극소수 대형주에만</b> 있습니다. 그래서 국내뿐 아니라
미국·일본·중국을 함께 담았습니다.
</p>

<h2>2. 해결 — 전 종목, 오늘 데이터, 즉시 생성</h2>
<p>
공개 데이터를 매일 모아 두고, 이용자가 종목을 열면 그 자리에서 리포트를 만듭니다.
사람이 쓰지 않으므로 종목 수와 무관하게 같은 품질로 제공됩니다.
</p>
<table>
<tr><th>제공하는 것</th><th style="width:52%">내용</th></tr>
{_rows(facts['features'])}
</table>
<p>
관점을 골라 볼 수 있습니다. 재무 중심(펀더멘탈), 주가 흐름 중심(기술적),
뉴스·공시 중심(이슈·트렌드), 그리고 셋을 묶은 종합입니다. 분량도 압축형과 상세형 중
고릅니다. 같은 종목이라도 무엇이 궁금한지에 따라 다른 리포트가 나옵니다.
</p>

<h2>3. 이 문제를 풀려면 넘어야 했던 것 — AI가 쓴 숫자는 틀린다</h2>
<p>
전 종목 리포트를 AI로 만들겠다는 것은, 아무도 검수하지 않은 금융 문서를 내보내겠다는
뜻입니다. 개발 과정에서 LLM이 생성한 리포트의 수치 오류를 <b>{facts['bug_count']}종</b>
발견했습니다. 공통점은 <b>문장이 완벽하고 화면에 오류가 나지 않는다</b>는 것입니다.
</p>
<table>
<tr><th>발견한 오류</th><th style="width:38%">실제 사례</th></tr>
{facts['bug_rows']}
</table>
<p>
그래서 세 겹으로 막았습니다.
</p>

<h3>1단계 · 계산은 AI에게 맡기지 않는다</h3>
<p>
증감률, 영업레버리지, 이익 변화의 요인 분해, 원가율·판관비율, 업종 중앙값 대비 위치를
<b>코드가 계산해</b> 프롬프트에 넣습니다. 모델은 계산하지 않고 서술만 합니다.
</p>
<pre>{facts['trend_sample']}</pre>

<h3>2단계 · 없는 데이터는 감춘다</h3>
<p>
시장마다 제공되는 항목이 다릅니다. 해외는 자산·부채·자본총계가 없어 부채비율과 ROE를
구할 수 없고, 공시·뉴스도 없습니다. 없는 값을 빈칸으로 넘기면 모델이 그 빈칸을
근거처럼 다루므로 <b>블록 자체를 넣지 않고</b>, 화면에서도 해당 지표와 관점을 감춥니다.
회사 소개도 모델에게 맡기지 않고 외부 출처에서 받아 인용합니다.
</p>

<h3>3단계 · 생성된 숫자를 원본과 대조한다</h3>
<p>
리포트 본문의 금액과 비율을 모두 뽑아 원본에서 나올 수 있는 값과 대조합니다.
출처를 찾지 못하면 <b>무엇이 틀렸는지 알려 주고 다시 생성</b>하며, 그래도 남으면
숨기지 않고 화면에 경고로 표시합니다.
</p>
<pre>{facts['verify_sample']}</pre>
<p class="note">
한국어는 '21.5% 감소'처럼 방향을 말로 쓰고 숫자에 부호를 붙이지 않습니다. 계산값
-21.46과 그대로 비교하면 맞는 문장이 대량 오탐됩니다. 부호를 양쪽 다 인정하도록 고쳐
오탐을 {facts['fp_before']}건에서 {facts['fp_after']}건으로 줄였습니다.
</p>

<h2>4. 구현 결과</h2>
<table>
<tr><th>항목</th><th style="width:22%">수치</th><th style="width:34%">비고</th></tr>
{facts['result_rows']}
</table>

<h2>5. 차별점</h2>
<ul>
<li><b>커버리지가 넓습니다.</b> 애널리스트가 다루지 않는 종목이 이 서비스의 주 대상입니다.
    시가총액 하위 종목일수록 기존 리포트가 없고, 그런 종목에서 이 서비스의 값어치가 큽니다.</li>
<li><b>항상 오늘 데이터입니다.</b> 시세와 공시는 평일 자동 갱신되고, 리포트는 열람 시점에
    생성됩니다. '언제 나온 리포트인가'를 따질 필요가 없습니다.</li>
<li><b>해외도 한국어로 봅니다.</b> 미국·일본·중국 종목을 같은 형식으로, 현지 통화 표기와
    함께 제공합니다. 원화 환산으로 시장을 가로질러 비교할 수 있습니다.</li>
<li><b>AI가 쓴 숫자를 검산합니다.</b> 사람이 검수하지 않는 문서를 내보내는 이상 필수입니다.
    검증에 실패한 수치는 숨기지 않고 표시합니다.</li>
<li><b>규제를 전제로 설계했습니다.</b> 불특정 다수 대상 종목 분석은 유사투자자문업 이슈가
    있어, 투자의견·목표주가를 구조적으로 생성하지 않습니다(응답 스키마에 항목 자체가
    없습니다). 그 자리에는 '투자자가 확인해야 할 점'과 '리스크 요인'이 들어갑니다.</li>
</ul>

<h2>6. 실현 가능성</h2>
<table>
<tr><th>구분</th><th style="width:20%">비용</th><th style="width:38%">근거</th></tr>
{_rows(facts['costs'])}
</table>
<p>
데이터 수집은 전액 무료이며 평일 자동 실행으로 갱신됩니다. 유료 구간은 LLM 호출뿐이고,
비용의 76%가 출력 토큰에서 발생하므로 분량 상한이 가장 효과적인 통제 수단입니다.
</p>

<h2>7. 앞으로</h2>
<ul>
<li><b>커버리지 공백을 먼저 채웁니다.</b> 리포트가 없는 종목을 우선 생성 대상으로 삼으면
    같은 비용으로 더 큰 공백을 메울 수 있습니다. 현재는 시가총액 순으로 채우고 있습니다.</li>
<li><b>공시 원문 연결.</b> 지금은 공시 제목만 봅니다. 원문을 근거로 삼으면 '왜 이렇게 됐는지'를
    추측이 아니라 인용으로 답할 수 있습니다. 검증 대상도 그만큼 넓어집니다.</li>
<li><b>검증 엔진의 분리.</b> 리포트 생성기와 떼어내면, 금융 텍스트를 입력받아 수치를 검산하는
    모듈로 쓸 수 있습니다. 사내 리서치 검수나 공시 요약 검증에 적용 가능합니다.</li>
<li><b>시장 확대.</b> 홍콩은 한 거래소에 통화가 섞이고 같은 회사가 중복 상장돼 있어
    보류했습니다. 중복 제거와 2차 상장 분리가 선행 과제입니다.</li>
</ul>

<div class="foot">
본 서비스가 제공하는 모든 내용은 정보 제공을 목적으로 하며 특정 종목의 매수·매도를 권유하지
않습니다. AI가 생성한 분석은 부정확할 수 있으며, 투자 판단과 그 결과에 대한 책임은
이용자 본인에게 있습니다.
</div>

</body></html>"""


def render(facts: dict, out_path: Path) -> Path:
    _register_font()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        result = pisa.CreatePDF(build_html(facts), dest=handle, encoding="utf-8")
    if result.err:
        raise RuntimeError("기획서 PDF 생성 실패")
    return out_path
