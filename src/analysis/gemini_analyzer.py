"""종목 데이터를 Gemini로 분석하고 결과를 캐시한다.

비용이 드는 유일한 구간이므로 세 가지 장치를 둔다.
  1) 캐시  - 같은 종목을 다시 열면 API를 호출하지 않는다
  2) 일일 상한 - 하루 신규 생성 건수를 제한해 최악의 비용을 고정한다
  3) 저가 모델 - flash-lite 계열을 기본으로 쓴다
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = ROOT / "data" / "processed"
CACHE_DIR = PROCESSED_DIR / "analysis"
USAGE_PATH = PROCESSED_DIR / "gemini_usage.json"

load_dotenv(ROOT / ".env")

MODEL = "gemini-3.1-flash-lite"
CACHE_TTL_DAYS = 7
DAILY_LIMIT = 100

DISCLAIMER = (
    "이 분석은 정보 제공 목적이며 투자 권유가 아닙니다. "
    "투자 판단과 그 결과에 대한 책임은 이용자 본인에게 있습니다."
)

# 웹앱이 항상 같은 구조로 렌더링할 수 있도록 응답 형식을 고정한다
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "요약": {"type": "string"},
        "재무_강점": {"type": "array", "items": {"type": "string"}},
        "재무_우려": {"type": "array", "items": {"type": "string"}},
        "밸류에이션": {"type": "string"},
        "유의사항": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["요약", "재무_강점", "재무_우려", "밸류에이션", "유의사항"],
}

SYSTEM_RULES = """너는 재무 데이터를 해석해 설명하는 애널리스트다. 다음 규칙을 반드시 지켜라.

1. 매수/매도/보유를 권유하지 마라. 목표주가나 투자의견을 제시하지 마라.
2. 주어진 수치에서 확인되는 사실만 서술하라. 수치에 없는 내용을 지어내지 마라.
3. 데이터가 없는 항목은 '데이터 없음'이라고 밝혀라.
4. 각 항목은 한국어로, 초보 투자자가 이해할 수 있게 간결히 써라.
5. 재무 지표가 좋아 보여도 그것이 주가 상승을 뜻하지 않음을 전제로 서술하라."""


class DailyLimitReached(RuntimeError):
    """하루 신규 분석 생성 상한에 도달했을 때."""


# 클라이언트를 매번 새로 만들면 임시 객체가 GC되면서 내부 HTTP 연결이 닫힌다
_CLIENT: genai.Client | None = None


def _client() -> genai.Client:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        # 배포 환경(Streamlit Cloud)에서는 .env 대신 Secrets를 쓴다
        try:
            import streamlit as st

            key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            key = None
    if not key:
        raise RuntimeError("GEMINI_API_KEY가 없습니다. .env 또는 Streamlit Secrets에 넣어주세요.")
    _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def _cache_path(stock_code: str) -> Path:
    return CACHE_DIR / f"{stock_code}.json"


def load_cached(stock_code: str) -> dict | None:
    path = _cache_path(stock_code)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    created = datetime.fromisoformat(data["생성시각"])
    if datetime.now() - created > timedelta(days=CACHE_TTL_DAYS):
        return None
    return data


def _usage_today() -> int:
    if not USAGE_PATH.exists():
        return 0
    log = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    return log.get(datetime.now().strftime("%Y-%m-%d"), 0)


def _record_usage() -> None:
    log = json.loads(USAGE_PATH.read_text(encoding="utf-8")) if USAGE_PATH.exists() else {}
    today = datetime.now().strftime("%Y-%m-%d")
    log[today] = log.get(today, 0) + 1
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    USAGE_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt(value, unit: str = "", scale: float = 1.0) -> str:
    if pd.isna(value):
        return "데이터 없음"
    return f"{value / scale:,.2f}{unit}"


def build_prompt(row: pd.Series) -> str:
    return f"""다음은 한국 상장기업 한 곳의 공시 재무 데이터다. 이 수치만 근거로 분석하라.

[기본 정보]
- 종목명: {row['종목명']} ({row['종목코드']})
- 시장: {row['시장구분']}
- 현재가: {_fmt(row.get('현재가'), '원')}
- 시가총액: {_fmt(row.get('시가총액'), '억원', 1e8)}

[재무 ({row.get('기준연도', '')}년 {row.get('보고서', '')})]
- 매출액: {_fmt(row.get('매출액'), '억원', 1e8)}
- 영업이익: {_fmt(row.get('영업이익'), '억원', 1e8)}
- 당기순이익: {_fmt(row.get('당기순이익'), '억원', 1e8)}
- 자산총계: {_fmt(row.get('자산총계'), '억원', 1e8)}
- 부채총계: {_fmt(row.get('부채총계'), '억원', 1e8)}
- 자본총계: {_fmt(row.get('자본총계'), '억원', 1e8)}

[지표]
- 부채비율: {_fmt(row.get('부채비율'), '%')}
- 영업이익률: {_fmt(row.get('영업이익률'), '%')}
- ROE: {_fmt(row.get('ROE_계산'), '%')}
- PER: {_fmt(row.get('PER'))}
"""


def analyze(row: pd.Series, force: bool = False) -> dict:
    """한 종목을 분석한다. 캐시가 있으면 API를 호출하지 않는다."""
    stock_code = row["종목코드"]

    if not force:
        cached = load_cached(stock_code)
        if cached:
            return cached

    if _usage_today() >= DAILY_LIMIT:
        raise DailyLimitReached(
            f"오늘 신규 분석 한도({DAILY_LIMIT}건)에 도달했습니다. 내일 다시 시도해주세요."
        )

    response = _client().models.generate_content(
        model=MODEL,
        contents=build_prompt(row),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_RULES,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    usage = response.usage_metadata
    result = {
        "종목코드": stock_code,
        "종목명": row["종목명"],
        "분석": json.loads(response.text),
        "모델": MODEL,
        "생성시각": datetime.now().isoformat(timespec="seconds"),
        "면책": DISCLAIMER,
        "토큰": {
            "입력": usage.prompt_token_count,
            "출력": usage.candidates_token_count,
        },
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(stock_code).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _record_usage()
    return result


def load_financials(year: int = 2025) -> pd.DataFrame:
    path = PROCESSED_DIR / f"financials_{year}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path}가 없습니다. src/collectors/financial_collector.py를 먼저 실행하세요."
        )
    return pd.read_csv(path, dtype={"종목코드": str})


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    df = load_financials()
    match = df[df["종목코드"] == code]
    if match.empty:
        sys.exit(f"{code}는 분석 대상에 없습니다.")

    out = analyze(match.iloc[0])
    print(f"[{out['종목명']}] {out['모델']} | 오늘 사용 {_usage_today()}/{DAILY_LIMIT}건")
    print(json.dumps(out["분석"], ensure_ascii=False, indent=2))
    if "토큰" in out:
        t = out["토큰"]
        print(f"\n토큰 입력 {t['입력']} / 출력 {t['출력']}"
              f" → 약 {(t['입력']/1e6*0.25 + t['출력']/1e6*1.50)*1400:.2f}원")
