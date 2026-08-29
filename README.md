# 초소형주 맞춤형 AI 리포트 생성기

KOSPI·KOSDAQ 전 종목의 시세와 재무 데이터를 모아, Gemini로 분석한 종목 리포트를 자동 생성합니다.

## 파이프라인

```
데이터 수집 → API 연동 → Gemini 분석 → 리포트 생성
 (네이버 금융)   (DART)      (Gemini)     (Markdown)
```

| 단계 | 모듈 | 상태 |
|---|---|---|
| 1. 데이터 수집 | `src/collectors/` | 완료 |
| 2. API 연동 | `src/api/` | 진행 중 |
| 3. Gemini 분석 | `src/analysis/` | 예정 |
| 4. 리포트 생성 | `src/report/` | 예정 |

## 시작하기

### 1. 가상환경 만들기

가상환경은 이 프로젝트 전용 라이브러리 공간입니다. 시스템 전체 Python에 설치하면
다른 프로젝트와 버전이 충돌할 수 있어, 프로젝트마다 독립된 방을 만들어 씁니다.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API 키 설정

`.env.example`을 복사해 `.env`를 만들고 각 키를 채웁니다.
`.env`는 `.gitignore`에 등록되어 있어 저장소에 올라가지 않습니다.

```powershell
copy .env.example .env
```

| 키 | 발급처 |
|---|---|
| `DART_API_KEY` | https://opendart.fss.or.kr → 인증키 신청 |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
| `NOTION_API_KEY` | https://notion.so/my-integrations |
| `NOTION_PARENT_PAGE_ID` | 학습 일지를 모을 Notion 페이지 URL 끝의 32자리 ID |

> Notion은 토큰만으로는 접근이 안 됩니다. 대상 페이지의 `···` → `Connections`에서
> 만든 Integration을 연결해야 API가 동작합니다.

### 3. 종목 데이터 수집

```powershell
python src/collectors/stock_collector.py
```

KOSPI·KOSDAQ 전 종목(약 4,300개)의 시세·시가총액을
`data/raw/stock_snapshot_<날짜>.csv`로 저장합니다.

## 사용 라이브러리

| 라이브러리 | 쓰는 이유 |
|---|---|
| `requests` | 네이버 금융·DART에 HTTP 요청을 보낼 때 |
| `beautifulsoup4`, `lxml` | 네이버 금융 HTML에서 표 데이터를 뽑아낼 때 |
| `pandas` | 수집한 데이터를 표로 다루고 CSV로 저장할 때 |
| `python-dotenv` | `.env`의 API 키를 코드로 안전하게 불러올 때 |
| `google-generativeai` | Gemini에 분석을 요청할 때 |
| `jinja2` | 분석 결과를 리포트 템플릿에 채워 넣을 때 |
| `tqdm` | 수집 진행률을 표시할 때 |
| `notion-client` | 학습 일지를 Notion에 자동 기록할 때 |

## 데이터 출처

주가·시가총액은 **네이버 금융**에서 가져옵니다. KRX 공식 API(`pykrx`)는 정책 변경으로
회원 로그인이 필요해져 사용하지 않습니다. 자세한 배경은 `CLAUDE.md` 참고.
