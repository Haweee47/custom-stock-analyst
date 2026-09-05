"""기능명세서 PDF를 만든다. 종목 수 같은 수치는 실제 데이터에서 뽑는다.

    python make_spec.py
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.analysis.report_spec import LENGTHS, PERSPECTIVES  # noqa: E402
from src.analysis.screens import SCREENS  # noqa: E402
from src.analysis.usage_limit import DAILY_LIMIT, LENGTH_LIMITS, SESSION_LIMIT  # noqa: E402
from src.collectors import markets  # noqa: E402
from src.report.proposal import _rows  # noqa: E402
from src.report.spec_doc import render  # noqa: E402

OUT = ROOT / "docs" / "기능명세서_리포트셀프바.pdf"
URL = "custom-stock-analyst.streamlit.app"
REPO = "github.com/Haweee47/custom-stock-analyst"
TEAM = "숑이"


def main() -> int:
    universe = markets.load_all()
    if universe.empty:
        sys.exit("종목 데이터가 없습니다. 먼저 수집을 돌리세요.")
    counts = universe.groupby("국가").size().to_dict()

    def market_row(label, exchanges, disclosure, news, metrics):
        return (
            f"{label}<br/><span style='color:#5f6672'>{exchanges}</span>",
            f"{counts.get(label, 0):,}",
            "O",
            "O" if disclosure else "—",
            "O" if news else "—",
            metrics,
        )

    facts = {
        "team": TEAM,
        "date": date.today().strftime("%Y년 %m월 %d일"),
        "url": URL,
        "repo": REPO,
        "stocks": f"{len(universe):,}",
        "overview_rows": _rows([
            ("대상", f"국내·미국·일본·중국 상장사 {len(universe):,}종목"),
            ("입력", "이용자가 시장·업종·규모 등으로 걸러 종목 하나를 선택"),
            ("처리", "저장된 리포트가 있으면 표시, 없으면 그 자리에서 생성(약 8초)"),
            ("출력", "화면 리포트 + PDF 내려받기"),
            ("갱신", "시세·공시 평일 자동, 재무·원가는 분기 단위"),
        ]),
        "source_rows": _rows([
            ("네이버 금융", "국내 시세·업종", "매일", "주가·시가총액·거래량·PER·외국인비율"),
            ("네이버 해외주식", "미국·일본·중국", "매일(시세)", "주가·시총·3개년 재무·업종·기업개요"),
            ("DART 주요계정", "국내 재무", "분기", "매출액·영업이익·당기순이익·자산·부채·자본"),
            ("DART 전체재무제표", "국내 원가", "분기", "매출원가·판매비와관리비 3개년"),
            ("DART 공시목록", "국내 공시", "매일", "최근 3개월 공시 제목·일자"),
            ("wisereport", "국내 기업개요", "필요 시", "사업 내용·주요 제품 설명"),
            ("네이버 환율", "원화 환산", "12시간", "USD·JPY·CNY 고시 환율"),
        ]),
        "filter_rows": _rows([
            ("시장", "라디오", "국내·미국·일본·중국. 아래 필터 구성을 결정"),
            ("거래소", "다중선택", "코스피·코스닥 / 나스닥·뉴욕 / 도쿄 / 상해·심천"),
            ("업종", "선택", "국내는 대분류→소분류 2단, 해외는 단일 분류"),
            ("최근 공시", "다중선택", "중대 공시·공시 위반·실적계약 등 7단계 (국내만)"),
            ("중대 공시 제외", "체크박스", "상장폐지·자본잠식 등이 있는 종목을 목록에서 제외"),
            ("재무 특성", f"다중선택 {len(SCREENS)}종", "흑자·저PER·고ROE·저부채·고성장·턴어라운드·수익성개선"),
            ("시가총액", "구간 선택", "초대형~초소형 5구간 + 직접 입력. 원화 환산 기준"),
            ("종목명 검색", "텍스트", "한글명·영문명·티커로 검색"),
            ("바로 볼 수 있는 종목만", "체크박스", "리포트가 이미 만들어진 종목만 표시"),
            ("종목 선택", "선택", "시총 순 정렬. ⚡는 즉시 열람, ⚠는 중대 공시"),
        ]),
        "detail_rows": _rows([
            ("중대 공시 경고", "해당 공시가 있으면 상단에 내용과 일자를 표시 (국내)"),
            ("핵심 지표", "현재가·시가총액과 시장별 지표 4종을 타일로 표시"),
            ("손익 구성", "매출액·영업이익·당기순이익 가로 막대. 통화 단위 반영"),
            ("시장 내 분포", "선택 지표의 전체 분포에 해당 종목 위치를 표시"),
            ("숫자로 보기", "제공되는 재무 항목만 표로. 없는 항목은 행을 만들지 않음"),
            ("AI 리포트", "관점·분량 선택 후 생성 또는 저장된 리포트 표시"),
            ("PDF 내려받기", "생성된 리포트를 A4 문서로 저장"),
        ]),
        "perspective_rows": _rows([
            (name, " · ".join(spec["데이터"]), spec["설명"])
            for name, spec in PERSPECTIVES.items()
        ]),
        "report_rows": _rows([
            ("회사 개요", "무슨 사업을 하는 곳인지. 외부 출처에서 받아 인용"),
            ("헤드라인", "회사의 현재 상태를 한 줄로. 관점에 맞는 구체적 사실 포함"),
            ("핵심 포인트", f"{LENGTHS['압축형']['포인트수']}~{LENGTHS['상세형']['포인트수']}개"),
            ("본문 섹션", f"압축형 {LENGTHS['압축형']['섹션수']}, 상세형 {LENGTHS['상세형']['섹션수']}"),
            ("주가 정보·투자지표", "현재가·시총·발행주식수와 시장별 지표"),
            ("주요 이슈", "뉴스·공시를 일자·구분과 함께 (국내)"),
            ("요약 실적", "매출·영업이익·순이익 3개년과 전년비, 마진율"),
            ("확인해야 할 점 / 리스크", "투자의견 대신 들어가는 항목"),
            ("숫자 대조 결과", "본문 수치의 원본 대조율. 미확인 항목이 있으면 명시"),
            ("데이터 한계", "이 분석이 보지 못한 것"),
        ]),
        "market_rows": _rows([
            market_row("국내주식", "코스피·코스닥", True, True,
                       "PER·부채비율·영업이익률·ROE"),
            market_row("미국주식", "나스닥·뉴욕", False, False,
                       "PER·PBR·영업이익률·ROA"),
            market_row("일본주식", "도쿄", False, False, "PER·PBR·영업이익률·ROA"),
            market_row("중국주식", "상해·심천", False, False, "PER·PBR·영업이익률·ROA"),
        ]),
        "source_kind_rows": _rows([
            ("재무 계정 3개년", "원본 값"),
            ("증감률 (전년비·2년비, 부호 양방향)", "계산값"),
            ("영업레버리지, 이익 변화의 매출·마진 분해", "계산값"),
            ("원가율·판관비율과 그 변화", "계산값 (국내)"),
            ("업종 중앙값·백분위", "동종 시장·업종 통계"),
            ("주가 보조지표", "이동평균·RSI·볼린저·일목 등"),
            ("뉴스·공시 제목에 실린 숫자", "인용으로 인정"),
        ]),
        "limit_rows": _rows([
            ("캐시", "7일", "같은 종목·관점·분량은 재호출 없이 표시"),
            ("프롬프트 버전", "v6", "프롬프트가 바뀌면 옛 캐시를 자동 만료"),
            ("일일 상한", f"{DAILY_LIMIT}건", "전체 신규 생성 건수. 환경변수로 조절"),
            ("분량별 상한", f"상세형 {LENGTH_LIMITS['상세형']}건", "출력이 길어 건당 비용이 높음"),
            ("세션 상한", f"{SESSION_LIMIT}건", "한 방문자가 한 번에 만들 수 있는 양"),
            ("모델", "gemini-3.1-flash-lite", "건당 약 3.1원 (실측)"),
        ]),
        "roadmap_rows": _rows([
            ("마진이 변한 원인",
             "원가율·판관비율이 얼마나 움직였는지까지만 계산",
             "DART 사업보고서 원문의 '사업의 내용'을 파싱해 단가·물량·환율 언급을 근거로 연결"),
            ("해외 원가 구조",
             "국내만 매출원가·판관비 확보. 해외는 마진 요인 분해 불가",
             "미국은 SEC XBRL로 손익 세부 항목 확보 가능. 일본·중국은 대체 출처 조사"),
            ("뉴스 활용 깊이",
             "제목만 수집. 제목에서 확인되는 사실 이상은 서술하지 않음",
             "본문을 수집해 근거 문장을 인용하고, 인용 여부를 검증 대상에 포함"),
            ("검증 범위",
             "금액과 비율만 대조. 인과 주장은 검증 불가라 생성하지 않음",
             "공시·뉴스 원문을 근거 집합으로 삼아 인과 주장도 출처 대조 대상으로 확장"),
            ("커버리지 우선순위",
             "시가총액 순으로 미리 생성. 공백이 큰 종목이 뒤로 밀림",
             "기존 리포트가 없는 종목을 우선 생성해 같은 비용으로 더 큰 공백을 메움"),
            ("시장 확대",
             "홍콩 보류. 한 거래소에 통화가 섞이고 같은 회사가 중복 상장",
             "통화별 중복 종목 정리와 2차 상장 분리 후 편입"),
            ("캐시 수명",
             "관점과 무관하게 7일 고정",
             "입력이 낡는 속도에 맞춰 관점별로 차등(재무 14일·주가 3일)"),
        ]),
        "stack_rows": _rows([
            ("화면", "Streamlit", "Streamlit Community Cloud 배포"),
            ("LLM", "google-genai (Gemini)", "JSON 스키마로 구조화 응답"),
            ("데이터", "pandas", "CSV 기반. 별도 DB 없음"),
            ("차트", "Plotly / matplotlib", "화면은 Plotly, PDF는 matplotlib"),
            ("PDF", "xhtml2pdf + 나눔고딕", "리포트·문서 공통"),
            ("자동화", "GitHub Actions", "평일 수집 후 자동 커밋"),
            ("테스트", f"pytest {facts_tests()}개", "발견한 버그를 회귀 테스트로 고정"),
        ]),
    }

    path = render(facts, OUT)
    print(f"기능명세서 생성: {path} ({path.stat().st_size:,} 바이트)")
    return 0


def facts_tests() -> int:
    import subprocess

    result = subprocess.run(
        [str(ROOT / ".venv/Scripts/python.exe"), "-m", "pytest", "-q", "--co"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    for line in reversed((result.stdout or "").splitlines()):
        if "test" in line and "collected" in line:
            return int(line.split()[0])
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
