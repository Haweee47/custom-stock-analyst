# 초소형주 맞춤형 AI 리포트 생성기

국내·미국·일본·중국 전 종목(17,395개)의 시세와 재무 데이터를 모아,
Gemini로 분석한 종목 리포트를 웹에서 볼 수 있게 만드는 프로젝트입니다.

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

실측 기준 1종목 분석에 **압축형 3.07원 / 상세형 5.03원**입니다.
비용의 **76%가 출력 토큰**에서 나오므로, 프롬프트를 줄이는 것보다 분량을 조절하는 것이
훨씬 효과적입니다. 그래서 전체 상한(하루 100건)과 별개로 **상세형만 하루 10건**으로 조입니다.

| 시나리오 | 하루 | 월 |
|---|---|---|
| 전부 압축형 100건 | 307원 | 9,210원 |
| 상세형 10 + 압축형 90 (현재 상한) | 327원 | 9,800원 |

전 종목(17,395개)을 매일 돌리면 월 160만 원이 되므로 배치 분석은 하지 않습니다.

| 단계 | 모듈 | 상태 |
|---|---|---|
| 1. 데이터 수집 | `src/collectors/` | 완료 |
| 2. API 연동 | `src/api/` (DART 재무·공시) | 완료 |
| 3. Gemini 분석 | `src/analysis/` | 완료 |
| 4. 리포트·웹앱 | `src/report/`, `app.py` | 완료 |

### 다루는 시장

| 시장 | 종목 수 | 재무 | 공시 | 뉴스 | 쓸 수 있는 지표 |
|---|---|---|---|---|---|
| 국내 (코스피·코스닥) | 2,655 | DART | O | O | PER·부채비율·영업이익률·ROE |
| 미국 (나스닥·뉴욕) | 6,775 | 네이버 해외 | X | X | PER·PBR·영업이익률·ROA |
| 일본 (도쿄) | 3,977 | 네이버 해외 | X | X | PER·PBR·영업이익률·ROA |
| 중국 (상해·심천) | 3,988 | 네이버 해외 | X | X | PER·PBR·영업이익률·ROA |

합계 **17,395종목**.

해외는 자산·부채·자본총계가 제공되지 않아 **부채비율과 ROE를 계산할 수 없습니다.**
그래서 해당 스크리너 조건을 감추고, 프롬프트에도 "그 지표는 알 수 없다"고 명시합니다.
공시·뉴스가 없으므로 '이슈·트렌드' 관점도 국내에서만 열립니다.

금액은 현지 통화로 보여주고(`2,159억달러`, `50조 6,850억엔`), 정렬·필터·업종
비교는 원화로 환산해서 합니다. **엔화 고시는 100엔 기준**이라 1엔당으로 풀어
씁니다(862.25원/100엔 → 8.62원/엔). 이걸 놓치면 일본 종목 시총이 100배가 됩니다. 동종업계 비교는 **같은 시장 안에서만** 합니다.
회계 기준과 업종 분류 체계가 달라 국내 반도체와 미국 반도체를 한 줄에 세우면
중앙값이 뜻을 잃기 때문입니다.

배포 주소: https://custom-stock-analyst.streamlit.app

### 홍콩을 넣지 않은 이유

목록 API는 `HONG_KONG` 코드로 열립니다(2,832개). 그런데 데이터를 믿기 어렵습니다.

- **한 거래소에 통화가 섞여 있습니다.** HKD와 CNY가 함께 옵니다.
- **같은 회사가 통화별로 중복 상장됩니다.** 텐센트가 `0700.HK`(HKD)와
  `80700.HK`(CNY) 두 개로 나옵니다.
- **해외 2차 상장의 시가총액이 실제와 맞지 않습니다.** 마이크로소프트(`4338.HK`)가
  11.88조 HKD(약 1.5조 달러)로 나오는데 실제 시가총액은 그 두 배가 넘습니다.

넣으려면 중복 종목을 걸러내고 2차 상장을 분리하는 작업이 먼저 필요합니다.
다만 이 조사 덕분에 **시장 하나에 통화가 하나라고 가정하던 버그**를 찾아
고쳤습니다(`markets._overseas`는 이제 행마다 그 종목의 통화로 환산합니다).

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

## 캐시 미리 채우기 (warmup)

배포 환경에서는 **커밋된 캐시만이 진짜 캐시**입니다. Streamlit Cloud는 앱이 잠들거나
재시작하면 실행 중 만든 파일을 지우기 때문에, 방문자가 만든 리포트는 얼마 못 가 사라집니다.
그래서 자주 열릴 종목은 미리 만들어 저장소에 넣어 둡니다.

```powershell
python warmup.py --dry-run    # 몇 건에 얼마 드는지만 확인
python warmup.py              # 시총 상위 30개, 앱 기본값(펀더멘탈·압축형)
python warmup.py --top 50 --view 종합
```

이미 캐시가 있는 종목은 건너뛰므로 여러 번 돌려도 중복 비용이 들지 않습니다.
실측 기준 30건에 약 **92원**입니다.

만든 뒤에는 커밋해야 배포에 반영됩니다.

```powershell
git add data/processed/analysis
git commit -m "chore: 리포트 캐시 워밍"
git push
```

> 일일 생성 상한(100건)은 배치에도 그대로 적용됩니다. 남은 건수보다 많이 요청하면
> 남은 만큼만 만들고 멈춥니다. 반면 세션 상한(10건)은 방문자 한 명을 막기 위한 것이라
> 배치에는 적용하지 않습니다.

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

## 매일 자동 갱신 (GitHub Actions)

`.github/workflows/daily-update.yml`이 **평일 18:30(KST)**에 데이터를 갱신하고
바뀐 파일을 자동으로 커밋·푸시합니다. 푸시되면 Streamlit Cloud가 다시 배포하므로
사람이 손댈 일이 없습니다.

```
장 마감(15:30) → 18:30 자동 실행
   시세 갱신 (네이버, 무료)
   공시 갱신 (DART, 무료)
   캐시 워밍 (Gemini, 만료된 것만 하루 4~5건)
   → data/processed 커밋 & 푸시 → 재배포
```

### 켜기 전에 할 일

저장소 **Settings → Secrets and variables → Actions**에서 두 개를 등록합니다.

| 이름 | 값 |
|---|---|
| `DART_API_KEY` | opendart.fss.or.kr 인증키 |
| `GEMINI_API_KEY` | aistudio.google.com 키 |

`GEMINI_API_KEY`를 넣지 않으면 캐시 워밍만 건너뛰고 데이터 수집은 정상 동작합니다.

### 직접 돌리기

**Actions → 일일 데이터 갱신 → Run workflow**로 언제든 실행할 수 있습니다.

- `full`: 재무·업종까지 전체 갱신. DART를 2,655회 조회하므로 오래 걸립니다.
  재무는 분기마다 바뀌므로 **새 분기보고서가 나왔을 때만** 켜면 됩니다.
- `warmup_top`: 캐시를 미리 채울 종목 수. `0`이면 건너뜁니다.

### 시세와 재무를 나눠 갱신하는 이유

화면이 읽는 `financials_<연도>.csv`에는 주가와 재무가 함께 들어 있습니다.
주가는 매일 바뀌지만 재무는 분기마다 바뀝니다. 그래서 매일 갱신은 DART를 건드리지 않고
스냅샷의 시세 열만 갈아 끼웁니다(`financial_collector.refresh_prices`).
재무를 다시 받아야만 주가가 갱신되던 구조였다면 매일 돌릴 수 없었습니다.

### 비용

수집은 전부 무료입니다. Gemini만 돈이 드는데, 캐시가 7일 뒤 만료되므로
상위 30종목 기준 **하루 4~5건(약 15원)**만 새로 만듭니다. 월 500원 안팎입니다.

## 데이터 출처

주가·시가총액은 **네이버 금융**에서 가져옵니다. KRX 공식 API(`pykrx`)는 정책 변경으로
회원 로그인이 필요해져 사용하지 않습니다. 자세한 배경은 `CLAUDE.md` 참고.
