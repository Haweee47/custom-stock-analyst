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

<h1>숫자를 검산하는 AI 금융 리포트</h1>
<p class="sub">AI가 쓴 금융 텍스트의 수치 오류를 기계로 잡아내는 생성·검증 시스템</p>
<div class="meta">
  2026 금융 AI Challenge 기획서 &nbsp;|&nbsp; 서비스명 <b>리포트 셀프바</b>
  &nbsp;|&nbsp; 배포 {facts['url']} &nbsp;|&nbsp; 작성일 {facts['date']}
</div>

<div class="lead">
<b>한 줄 요약</b><br>
LLM이 금융 리포트를 쓸 때 가장 위험한 것은 문장이 어색한 것이 아니라 숫자가 틀리는 것입니다.
이 서비스는 리포트를 생성한 뒤 <b>본문의 모든 금액과 비율을 원본 데이터와 기계로 대조</b>하고,
출처를 찾지 못한 수치가 있으면 다시 생성하거나 이용자에게 표시합니다.
{facts['markets']}개 시장 <b>{facts['stocks']}종목</b>에 대해 실제로 작동합니다.
</div>

<h2>1. 문제 — 금융 AI의 숫자는 조용히 틀린다</h2>
<p>
개발 과정에서 LLM이 생성한 리포트의 수치 오류를 <b>{facts['bug_count']}종</b> 실제로 발견했습니다.
공통점은 <b>문장이 완벽하고 화면에 오류가 나지 않는다</b>는 것입니다.
사람이 원본 데이터와 한 줄씩 대조해야만 드러났습니다.
</p>
<table>
<tr><th>발견한 오류</th><th style="width:38%">실제 사례</th></tr>
{_rows(facts['bugs'])}
</table>
<div class="callout">
금융 리포트에서 매출이 10배로 적히면 그 리포트는 쓸 수 없습니다. 그런데 이런 오류는
사용자가 원본을 갖고 있지 않으면 <b>발견할 방법이 없습니다</b>.
프롬프트 규칙으로 빈도를 줄일 수는 있어도 없앨 수는 없습니다.
</div>

<h2>2. 해결 — 계산 · 생성 · 검증의 3단 구조</h2>
<p>
LLM에게 판단을 맡기는 범위를 좁히고, 판단한 결과를 다시 기계로 검산합니다.
</p>

<h3>1단계 · 계산 레이어 — LLM에게 계산을 맡기지 않는다</h3>
<p>
증감률, 영업레버리지, 이익 변화의 요인 분해, 업종 중앙값 대비 위치를
<b>결정론적으로 계산</b>해 프롬프트에 넣습니다. 모델은 계산하지 않고 서술만 합니다.
</p>
<pre>{facts['trend_sample']}</pre>

<h3>2단계 · 생성 레이어 — 시장별로 없는 데이터를 감춘다</h3>
<p>
시장마다 제공되는 항목이 다릅니다. 해외는 자산·부채·자본총계가 없어 부채비율과 ROE를
구할 수 없고, 공시·뉴스도 없습니다. 없는 값을 빈칸으로 넘기면 모델이 그 빈칸을
근거처럼 다루므로, <b>블록 자체를 넣지 않고</b> 무엇을 알 수 없는지 명시합니다.
화면에서도 해당 지표와 관점을 감춥니다.
</p>

<h3>3단계 · 검증 레이어 — 생성된 숫자를 원본과 대조한다</h3>
<p>
리포트 본문의 금액과 비율을 모두 추출해 원본에서 나올 수 있는 값의 목록과 대조합니다.
출처를 찾지 못하면 <b>무엇이 틀렸는지 알려 주고 다시 생성</b>하며, 그래도 남으면
이용자 화면에 경고로 표시합니다.
</p>
<table>
<tr><th>출처로 인정하는 값</th><th style="width:30%">비고</th></tr>
{_rows(facts['sources'])}
</table>
<p class="note">
한국어 리포트는 '21.5% 감소'처럼 방향을 말로 쓰고 숫자에 부호를 붙이지 않습니다.
계산값 -21.46과 그대로 비교하면 맞는 문장이 대량으로 오탐됩니다. 부호를 양쪽 다
인정하도록 고쳐 오탐을 {facts['fp_before']}건에서 {facts['fp_after']}건으로 줄였습니다.
</p>

<h2>3. 구현 결과</h2>
<table>
<tr><th>항목</th><th style="width:22%">수치</th><th style="width:34%">비고</th></tr>
{_rows(facts['results'])}
</table>

<h3>검증 레이어의 실제 동작</h3>
<p>
오류가 있던 과거 리포트와 현재 리포트를 같은 검증기에 넣은 결과입니다.
</p>
<pre>{facts['verify_sample']}</pre>

<h2>4. 차별점</h2>
<ul>
<li><b>생성이 아니라 검증이 핵심입니다.</b> AI 리포트 생성은 흔하지만, 생성된 수치를
    원본과 기계로 대조하고 실패 시 재생성하는 구조는 드뭅니다.</li>
<li><b>모르는 것을 모른다고 말합니다.</b> 시장별로 없는 데이터는 감추고, 검증에 실패한
    수치는 숨기지 않고 표시합니다. 원가 항목이 없으므로 마진이 왜 변했는지는
    '얼마나 기여했는지'까지만 말하고 원인은 추측하지 않습니다.</li>
<li><b>규제를 전제로 설계했습니다.</b> 불특정 다수 대상 종목 분석은 유사투자자문업
    이슈가 있어, 투자의견·목표주가를 구조적으로 생성하지 않습니다
    (응답 스키마에 해당 항목이 없습니다). 그 자리에는 '투자자가 확인해야 할 점'과
    '리스크 요인'이 들어갑니다.</li>
<li><b>비용을 측정하고 상한을 걸었습니다.</b> 1건 {facts['cost_per']}원(실측),
    일일 상한과 분량별 상한으로 최악의 비용이 고정됩니다.</li>
</ul>

<h2>5. 실현 가능성</h2>
<table>
<tr><th>구분</th><th style="width:20%">비용</th><th style="width:38%">근거</th></tr>
{_rows(facts['costs'])}
</table>
<p>
데이터 수집은 전액 무료이며 평일 자동 실행으로 갱신됩니다. 유료 구간은 LLM 호출뿐이고,
비용의 76%가 출력 토큰에서 발생하므로 분량 상한이 가장 효과적인 통제 수단입니다.
</p>

<h2>6. 앞으로</h2>
<ul>
<li><b>검증 대상 확대</b> — 현재는 금액과 비율을 검증합니다. 인과 주장("수요 증가로 단가 인상")은
    아직 검증할 수 없어 생성하지 않습니다. 공시 원문을 근거로 연결하는 것이 다음 과제입니다.</li>
<li><b>검증 엔진의 분리</b> — 리포트 생성기와 무관하게, 금융 텍스트를 입력받아 수치를
    검산하는 모듈로 떼어낼 수 있습니다. 사내 리서치 자동화나 공시 요약 검수에 적용 가능합니다.</li>
<li><b>시장 확대</b> — 홍콩은 한 거래소에 통화가 섞이고 중복 상장이 있어 보류했습니다.
    중복 제거와 2차 상장 분리가 선행 과제입니다.</li>
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
