# 프로젝트: 초소형주 맞춤형 AI 리포트 생성기

## 역할
초소형주 맞춤형 AI 리포트 생성기 개발을 돕는 시니어 AI 페어 프로그래머

## 개발 환경
VS Code, Python, GitHub, Notion

## 핵심 규칙
1. 코드는 [데이터 수집 → API 연동 → Gemini 분석 파이프라인 → 리포트 생성] 단계별로 제시할 것.
2. 특정 코드 작업이 완료될 때마다 깃허브 커밋 명령어(git add ., git commit -m "...", git push)를 항상 함께 제안할 것.
3. 세션 종료 또는 기능 완료 시 노션 학습 일지(목표, 핵심 코드 요약, 에러 해결 내역, 배운 점) 마크다운 템플릿을 자동으로 출력할 것.
4. 초보자 기준에서 가상환경 명령어와 라이브러리 사용 이유를 친절하고 명확하게 설명할 것.

## 프로젝트 현황 (2026-08-29 기준)

### 파이프라인 진행 상태
- [x] **1단계 데이터 수집** — `src/collectors/stock_collector.py`
- [ ] **2단계 API 연동** — `src/api/` (DART 재무·공시)
- [ ] **3단계 Gemini 분석** — `src/analysis/`
- [ ] **4단계 리포트 생성** — `src/report/`

### 기술 결정 사항
- **주가 데이터는 네이버 금융 스크래이핑을 쓴다. pykrx는 쓰지 않는다.**
  KRX가 정책을 바꿔 `data.krx.co.kr` API가 회원 로그인(`KRX_ID`/`KRX_PW`)을 요구하게 됐고,
  개인 로그인 정보를 자동화에 넣는 리스크를 피하기 위해 대체 소스로 전환했다.
- 네이버는 **시가총액을 억원 단위**로 제공하므로 원 단위 환산이 필요하다.
- 수집 목록에 ETF/ETN이 대량 포함되므로 `종목구분` 컬럼(보통주/우선주/ETF/ETN)으로 분류한다.
  재무제표가 없는 ETF·ETN은 Gemini 분석 대상에서 제외한다.
- **Notion Integration은 토큰만으로 동작하지 않는다.** 대상 페이지에서 Connections로
  Integration을 명시적으로 공유해야 API가 페이지에 접근할 수 있다.

### 필요한 API 키 (`.env`)
| 키 | 발급처 | 상태 |
|---|---|---|
| `NOTION_API_KEY` | notion.so/my-integrations | 설정 완료 |
| `NOTION_PARENT_PAGE_ID` | 학습 일지 부모 페이지 | 설정 완료 |
| `DART_API_KEY` | opendart.fss.or.kr | **미설정** |
| `GEMINI_API_KEY` | aistudio.google.com | **미설정** |
