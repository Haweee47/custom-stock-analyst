"""MVP 산출물로 제출할 기능명세서를 PDF로 만든다.

기획서가 '왜 만드는가'라면 이 문서는 '무엇이 어떻게 동작하는가'다.
화면에 있는 기능, 데이터가 어디서 와서 어디로 가는지, 시장마다 무엇이 다른지를
빠짐없이 적는다. 숫자는 기획서와 마찬가지로 실제 데이터에서 뽑는다.
"""
import sys
from pathlib import Path

from xhtml2pdf import pisa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.report.proposal import _rows  # noqa: E402
from src.report.report_pdf import _register_font  # noqa: E402

INK = "#14171c"
ACCENT = "#12386b"
ACCENT_SOFT = "#eef2f8"
RULE = "#d5d8dd"
HAIR = "#e9ebef"
MUTED = "#5f6672"

CSS = f"""
@page {{ size: A4; margin: 15mm 14mm 14mm 14mm; }}
body {{ font-family: "Nanum"; font-size: 9.2pt; color: {INK}; line-height: 1.58; }}

.tag {{ font-size: 7.6pt; color: {ACCENT}; letter-spacing: 1pt; margin-bottom: 2pt; }}
h1 {{ font-size: 19pt; color: {ACCENT}; margin: 0 0 3pt; letter-spacing: -.4pt; }}
.sub {{ font-size: 10pt; color: {INK}; margin: 0 0 8pt; }}
.meta {{ font-size: 7.8pt; color: {MUTED}; border-top: 2.2pt solid {ACCENT};
         padding-top: 5pt; margin-bottom: 12pt; }}

h2 {{ font-size: 11pt; color: {ACCENT}; margin: 13pt 0 5pt;
      border-bottom: 1pt solid {ACCENT}; padding-bottom: 3pt; }}
h3 {{ font-size: 9.4pt; color: {INK}; margin: 9pt 0 3pt; }}
p {{ margin: 0 0 5pt; }}
ul {{ margin: 0 0 6pt 0; padding-left: 13pt; }}
li {{ margin-bottom: 3pt; }}

.note {{ font-size: 7.8pt; color: {MUTED}; margin: -1pt 0 7pt; }}
.box {{ background: {ACCENT_SOFT}; border-left: 3pt solid {ACCENT};
        padding: 7pt 10pt; margin: 6pt 0 8pt; }}

table {{ border-collapse: collapse; width: 100%; margin: 5pt 0 8pt; }}
th {{ background: {ACCENT}; color: #ffffff; font-size: 8pt; padding: 4pt 6pt;
      text-align: left; }}
td {{ font-size: 8.4pt; padding: 3.6pt 6pt; border-bottom: .5pt solid {HAIR};
      vertical-align: top; }}
td.n {{ text-align: right; }}

pre {{ font-family: "Nanum"; background: #f6f7f9; border: .5pt solid {RULE};
       padding: 8pt 10pt; font-size: 7.8pt; line-height: 1.4; margin: 4pt 0 8pt; }}
"""

FLOW = """  [수집 — 평일 자동, 무료]
    네이버 금융 시세·업종      →  data/raw, data/processed
    네이버 해외주식 시세·재무   →  overseas_{미국,일본,중국}.csv
    DART 재무·공시·원가        →  financials.csv, disclosure_flags.csv, costs.csv
    wisereport / 네이버 기업개요 →  overviews.json
                    │
                    ▼
  [열람 — 이용자가 종목을 열 때]
    캐시 확인 ──있음──▶ 저장된 리포트 표시            (LLM 호출 0회)
        │
       없음
        ▼
    계산 레이어  증감률·영업레버리지·원가율·업종 중앙값을 코드가 계산
        ▼
    생성 레이어  Gemini 호출 (계산값 + 회사개요 + 뉴스·공시를 프롬프트로)
        ▼
    검증 레이어  본문 숫자를 원본과 대조 ──실패──▶ 재생성(1회)
        ▼
    캐시 저장 후 표시 (검증 결과를 화면에 함께 표시)"""


def build_html(facts: dict) -> str:
    return f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>

<div class="tag">2026 금융 AI CHALLENGE · MVP 산출물</div>
<h1>리포트 셀프바 기능명세서</h1>
<p class="sub">애널리스트가 다루지 않는 종목까지, 오늘 데이터로 만드는 AI 기업 리포트</p>
<div class="meta">
{facts['team']} &nbsp;·&nbsp; {facts['date']} &nbsp;·&nbsp;
서비스 {facts['url']} &nbsp;·&nbsp; 소스 {facts['repo']}
</div>

<h2>1. 서비스 개요</h2>
<p>
국내·미국·일본·중국 상장사 <b>{facts['stocks']}종목</b>에 대해, 이용자가 종목을 여는
시점의 데이터로 기업 분석 리포트를 생성합니다. 사전에 만들어 둔 리포트가 있으면 즉시
표시하고, 없으면 그 자리에서 생성합니다.
</p>
<table>
<tr><th>구분</th><th style="width:64%">내용</th></tr>
{facts['overview_rows']}
</table>

<h2>2. 시스템 구성</h2>
<pre>{FLOW}</pre>
<p class="note">
수집은 GitHub Actions로 평일 18:30(KST)에 자동 실행되며 갱신분은 저장소에 자동 커밋됩니다.
비용이 발생하는 구간은 생성 레이어(Gemini 호출)뿐입니다.
</p>

<h2>3. 데이터 소스</h2>
<table>
<tr><th>소스</th><th style="width:22%">대상</th><th style="width:16%">갱신</th>
    <th style="width:30%">수집 항목</th></tr>
{facts['source_rows']}
</table>

<h2>4. 화면 기능</h2>

<h3>4.1 종목 탐색 (사이드바)</h3>
<table>
<tr><th>기능</th><th style="width:20%">형태</th><th style="width:42%">동작</th></tr>
{facts['filter_rows']}
</table>
<p class="note">
필터는 선택한 시장에 맞춰 구성이 바뀝니다. 해외에는 공시 필터가 없고, 자본총계가
제공되지 않아 판정할 수 없는 재무 조건(고ROE·저부채)은 목록에서 제외됩니다.
</p>

<h3>4.2 종목 상세</h3>
<table>
<tr><th>구성 요소</th><th style="width:56%">내용</th></tr>
{facts['detail_rows']}
</table>

<h3>4.3 리포트 생성</h3>
<p>
분석 관점 4종과 분량 2종을 조합해 8가지 리포트를 만들 수 있습니다.
해외 종목은 뉴스·공시가 없어 '이슈·트렌드'를 제외한 3종을 제공합니다.
</p>
<table>
<tr><th>분석 관점</th><th style="width:22%">사용 데이터</th><th style="width:38%">서술 범위</th></tr>
{facts['perspective_rows']}
</table>

<h3>4.4 리포트 구성</h3>
<table>
<tr><th>항목</th><th style="width:58%">내용</th></tr>
{facts['report_rows']}
</table>

<h2>5. 시장별 제공 범위</h2>
<p>
시장마다 확보 가능한 데이터가 다릅니다. 없는 항목은 화면과 프롬프트 양쪽에서
제외하며, 임의로 추정하지 않습니다.
</p>
<table>
<tr><th>시장</th><th style="width:12%">종목</th><th style="width:11%">재무</th>
    <th style="width:11%">공시</th><th style="width:11%">뉴스</th>
    <th style="width:28%">제공 지표</th></tr>
{facts['market_rows']}
</table>

<h2>6. 숫자 검증</h2>
<p>
생성된 리포트 본문에서 금액과 비율을 모두 추출해, 원본에서 나올 수 있는 값의 목록과
대조합니다. 허용 오차는 금액 1.5%(조·억 반올림), 비율 0.15%p입니다.
</p>
<table>
<tr><th>출처로 인정하는 값</th><th style="width:30%">비고</th></tr>
{facts['source_kind_rows']}
</table>
<p>
출처를 찾지 못한 수치가 있으면 <b>무엇이 어긋났는지 프롬프트에 적어 1회 재생성</b>합니다.
재생성 후에도 남으면 대조율이 높은 쪽을 저장하고, 화면 하단에 어떤 수치가 확인되지
않았는지 표시합니다. 숨기지 않습니다.
</p>

<h2>7. 비용 통제</h2>
<table>
<tr><th>장치</th><th style="width:18%">값</th><th style="width:44%">동작</th></tr>
{facts['limit_rows']}
</table>

<h2>8. 기술 스택</h2>
<table>
<tr><th>구분</th><th style="width:26%">사용</th><th style="width:40%">비고</th></tr>
{facts['stack_rows']}
</table>

<h2>9. 설계 원칙 — 확인되지 않은 것은 쓰지 않는다</h2>
<p>
사람이 검수하지 않는 금융 문서이므로, 근거를 댈 수 없는 서술은 만들지 않는 것을
기준으로 삼았습니다. 아래 두 가지는 기능 부족이 아니라 의도한 설계입니다.
</p>
<ul>
<li><b>투자의견과 목표주가를 생성하지 않습니다.</b> 불특정 다수 대상 종목 분석의
    유사투자자문업 이슈를 피하기 위해 응답 스키마에서 해당 항목을 아예 제외했습니다.
    그 자리에는 '투자자가 확인해야 할 점'과 '리스크 요인'이 들어갑니다.</li>
<li><b>데이터로 확인되지 않는 인과는 서술하지 않습니다.</b> 원가율이 내려갔다는
    사실까지는 계산으로 말하지만, 왜 내려갔는지는 근거가 없으면 쓰지 않습니다.
    숫자 검증기가 금액과 비율은 잡아내지만 인과 주장의 참·거짓은 가려내지 못하기
    때문입니다.</li>
</ul>

<h2>10. 앞으로 해결할 과제</h2>
<p>
아래는 현재 데이터로는 아직 답하지 못하는 것들입니다. 각각 해결 경로를 확인해
두었고, 순서대로 개발을 이어갈 계획입니다.
</p>
<table>
<tr><th>과제</th><th style="width:31%">현재</th><th style="width:37%">해결 방향</th></tr>
{facts['roadmap_rows']}
</table>

</body></html>"""


def render(facts: dict, out_path: Path) -> Path:
    _register_font()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        result = pisa.CreatePDF(build_html(facts), dest=handle, encoding="utf-8")
    if result.err:
        raise RuntimeError("기능명세서 PDF 생성 실패")
    return out_path
