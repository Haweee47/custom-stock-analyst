# 초소형주 맞춤형 AI 리포트 생성기

KOSPI·KOSDAQ 전 종목의 시세와 재무 데이터를 모아, Gemini로 분석한 종목 리포트를
웹에서 볼 수 있게 만드는 프로젝트입니다.

> **투자 유의 안내**
> 이 서비스가 제공하는 모든 내용은 정보 제공을 목적으로 하며, 특정 종목의 매수·매도를
> 권유하지 않습니다. AI가 생성한 분석은 부정확할 수 있으며, 투자 판단과 그 결과에 대한
> 책임은 이용자 본인에게 있습니다.

## 구조

**데이터 수집은 무료라서 매일 전 종목을 돌리고, 비용이 드는 Gemini 분석은
실제로 요청받은 종목만 생성해 캐시에 쌓습니다.**

```
[수집 배치 - 매일, 무료]
네이버 금융 시세 + DART 재무·공시  →  data/raw, data/processed

[웹앱 - 상시]
방문자가 종목 열기
      │
      ├─ 캐시에 있음  → 바로 표시            (Gemini 호출 0회)
      └─ 캐시에 없음  → Gemini 분석 → 캐시 저장 → 표시
                        (일일 생성 상한으로 비용 한도 고정)
```

실측 기준 1종목 분석에 **0.80원**입니다. 전 종목을 매일 돌리면 월 약 64,000원이지만,
필요한 종목만 생성하면 하루 20건 기준 **월 약 480원**입니다.
일일 생성 상한(100건)이 걸려 있어 최악의 경우에도 하루 80원을 넘지 않습니다.

| 단계 | 모듈 | 상태 |
|---|---|---|
| 1. 데이터 수집 | `src/collectors/` | 완료 |
| 2. API 연동 | `src/api/` | 진행 중 |
| 3. Gemini 분석 | `src/analysis/` | 예정 |
| 4. 리포트·웹앱 | `src/report/`, `app.py` | 예정 |

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
| `google-genai` | Gemini에 분석을 요청할 때 (현행 SDK) |
| `jinja2` | 분석 결과를 리포트 템플릿에 채워 넣을 때 |
| `streamlit` | 분석 결과를 웹 화면으로 보여줄 때 (파이썬만으로 웹 UI 구성) |
| `plotly` | 웹 화면에서 주가·재무 차트를 그릴 때 |
| `tqdm` | 수집 진행률을 표시할 때 |
| `notion-client` | 학습 일지를 Notion에 자동 기록할 때 |

## 웹앱 실행

로컬에서 확인:

```powershell
streamlit run app.py
```

브라우저에서 `http://localhost:8501`이 열립니다. 이 주소는 **내 PC에서만** 보입니다.

## 배포 (다른 사람도 볼 수 있게)

[Streamlit Community Cloud](https://share.streamlit.io)에 무료로 배포합니다.

1. https://share.streamlit.io 접속 → **GitHub 계정으로 로그인**
2. **Create app** → **Deploy a public app from GitHub** 선택
3. 아래 값을 입력
   | 항목 | 값 |
   |---|---|
   | Repository | `Haweee47/custom-stock-analyst` |
   | Branch | `main` |
   | Main file path | `app.py` |
4. **Advanced settings** → Python version `3.11` 선택
5. 같은 화면의 **Secrets** 칸에 `.streamlit/secrets.toml.example` 내용을 붙여넣고
   실제 키로 채웁니다
6. **Deploy** 클릭 → 몇 분 뒤 `https://<앱이름>.streamlit.app` 주소가 생성됩니다

배포 후 GitHub에 push하면 앱이 자동으로 다시 배포됩니다.

### 배포 시 알아둘 점

- **분석 캐시는 재시작하면 사라집니다.** Streamlit Cloud는 앱이 잠들거나 재시작하면
  실행 중 만든 파일이 초기화됩니다. 캐시가 비면 그만큼 Gemini를 다시 호출하므로,
  자주 조회되는 종목은 로컬에서 미리 생성해 `data/processed/analysis/`에 커밋해두면 좋습니다.
- **키는 저장소에 올리지 않습니다.** `.env`와 `.streamlit/secrets.toml`은 `.gitignore`에
  등록되어 있습니다. 배포용 키는 Streamlit Cloud의 Secrets 칸에만 넣습니다.
- 공개 배포 전에 키를 **새로 발급**받는 것을 권합니다.

## 데이터 출처

주가·시가총액은 **네이버 금융**에서 가져옵니다. KRX 공식 API(`pykrx`)는 정책 변경으로
회원 로그인이 필요해져 사용하지 않습니다. 자세한 배경은 `CLAUDE.md` 참고.
