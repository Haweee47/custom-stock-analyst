"""종목 데이터를 Gemini로 분석해 리포트를 만들고 캐시한다.

비용이 드는 유일한 구간이므로 세 가지 장치를 둔다.
  1) 캐시 - 같은 종목·관점·분량 조합을 다시 열면 API를 호출하지 않는다
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
sys.path.insert(0, str(ROOT))

from src.analysis.report_spec import (  # noqa: E402
    LENGTHS,
    PERSPECTIVES,
    RESPONSE_SCHEMA,
    SYSTEM_RULES,
)

from src.analysis import usage_limit  # noqa: E402
from src.analysis.usage_limit import (  # noqa: E402
    DAILY_LIMIT,
    DailyLimitReached,
    SessionLimitReached,
)

PROCESSED_DIR = ROOT / "data" / "processed"
CACHE_DIR = PROCESSED_DIR / "analysis"

load_dotenv(ROOT / ".env")

MODEL = "gemini-3.1-flash-lite"
CACHE_TTL_DAYS = 7

DISCLAIMER = (
    "이 리포트는 AI가 공개 데이터로 생성한 정보이며 투자 권유가 아닙니다. "
    "투자의견과 목표주가는 제공하지 않습니다. "
    "투자 판단과 그 결과에 대한 책임은 이용자 본인에게 있습니다."
)

_CLIENT: genai.Client | None = None


class ApiKeyMissing(RuntimeError):
    """API 키가 설정되지 않았을 때. 이용자 잘못이 아니라 운영자 설정 문제다."""


def _client() -> genai.Client:
    # 클라이언트를 매번 새로 만들면 임시 객체가 GC되면서 내부 HTTP 연결이 닫힌다
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        try:
            import streamlit as st

            key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            key = None
    if not key:
        raise ApiKeyMissing(
            "GEMINI_API_KEY가 설정되지 않았습니다. "
            "로컬은 .env, 배포 환경은 Streamlit Cloud의 Settings > Secrets에 넣어주세요."
        )
    _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def _cache_path(stock_code: str, perspective: str, length: str) -> Path:
    return CACHE_DIR / f"{stock_code}_{perspective}_{length}.json"


def load_cached(stock_code: str, perspective: str, length: str) -> dict | None:
    path = _cache_path(stock_code, perspective, length)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    created = datetime.fromisoformat(data["생성시각"])
    if datetime.now() - created > timedelta(days=CACHE_TTL_DAYS):
        return None
    return data


def _fmt(value, unit: str = "", scale: float = 1.0) -> str:
    if value is None or pd.isna(value):
        return "데이터 없음"
    return f"{value / scale:,.2f}{unit}"


def _financial_block(row: pd.Series) -> str:
    return f"""[재무 ({row.get('기준연도', '')}년 {row.get('보고서', '')})]
- 매출액: {_fmt(row.get('매출액'), '억원', 1e8)}
- 영업이익: {_fmt(row.get('영업이익'), '억원', 1e8)}
- 당기순이익: {_fmt(row.get('당기순이익'), '억원', 1e8)}
- 자산총계: {_fmt(row.get('자산총계'), '억원', 1e8)}
- 부채총계: {_fmt(row.get('부채총계'), '억원', 1e8)}
- 자본총계: {_fmt(row.get('자본총계'), '억원', 1e8)}
- 부채비율: {_fmt(row.get('부채비율'), '%')}
- 영업이익률: {_fmt(row.get('영업이익률'), '%')}
- ROE: {_fmt(row.get('ROE_계산'), '%')}
- PER: {_fmt(row.get('PER'), '배')}"""


def _technical_block(tech: dict) -> str:
    if not tech:
        return "[주가 지표]\n- 데이터 없음"
    lines = "\n".join(f"- {k}: {v}" for k, v in tech.items())
    return f"[주가 지표 (계산 완료, 해석만 하라)]\n{lines}"


def _news_block(news: list[dict]) -> str:
    if not news:
        return "[최근 뉴스]\n- 최근 뉴스 없음"
    lines = "\n".join(f"- [{n['일자']}] {n['제목']}" for n in news)
    return f"[최근 뉴스 제목 (본문 없음, 내용 추측 금지)]\n{lines}"


def _disclosure_block(disclosures: list[dict]) -> str:
    if not disclosures:
        return "[최근 공시]\n- 최근 공시 없음"
    lines = "\n".join(f"- [{d['일자']}] {d['제목']}" for d in disclosures)
    return f"[최근 주요 공시 (중요도순, 최근 6개월)]\n{lines}"


def build_prompt(
    row: pd.Series,
    perspective: str,
    length: str,
    tech: dict | None = None,
    news: list[dict] | None = None,
    disclosures: list[dict] | None = None,
) -> str:
    spec, size = PERSPECTIVES[perspective], LENGTHS[length]

    blocks = [
        f"""[기본 정보]
- 종목명: {row['종목명']} ({row['종목코드']})
- 시장: {row['시장구분']}
- 현재가: {_fmt(row.get('현재가'), '원')}
- 시가총액: {_fmt(row.get('시가총액'), '억원', 1e8)}"""
    ]
    if "재무" in spec["데이터"]:
        blocks.append(_financial_block(row))
    if "기술" in spec["데이터"]:
        blocks.append(_technical_block(tech or {}))
    if "뉴스" in spec["데이터"]:
        blocks.append(_news_block(news or []))
    if "공시" in spec["데이터"]:
        blocks.append(_disclosure_block(disclosures or []))

    data = "\n\n".join(blocks)
    return f"""다음 데이터로 기업 리포트를 작성하라.

{data}

[분석 관점: {perspective}]
{spec['지시']}

[분량: {length}]
- 섹션 {size['섹션수']}, {size['본문길이']}
- 핵심포인트 {size['포인트수']}"""


def analyze(
    row: pd.Series,
    perspective: str = "종합",
    length: str = "압축형",
    tech: dict | None = None,
    news: list[dict] | None = None,
    disclosures: list[dict] | None = None,
    force: bool = False,
) -> dict:
    """한 종목을 분석한다. 캐시가 있으면 API를 호출하지 않는다."""
    stock_code = row["종목코드"]

    if not force:
        cached = load_cached(stock_code, perspective, length)
        if cached:
            return cached

    usage_limit.check()

    response = _client().models.generate_content(
        model=MODEL,
        contents=build_prompt(row, perspective, length, tech, news, disclosures),
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
        "관점": perspective,
        "분량": length,
        "리포트": json.loads(response.text),
        "모델": MODEL,
        "생성시각": datetime.now().isoformat(timespec="seconds"),
        "면책": DISCLAIMER,
        "토큰": {"입력": usage.prompt_token_count, "출력": usage.candidates_token_count},
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(stock_code, perspective, length).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    usage_limit.record()
    return result


def _usage_today() -> int:
    return usage_limit.used_today()


def load_financials(year: int = 2025) -> pd.DataFrame:
    path = PROCESSED_DIR / f"financials_{year}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path}가 없습니다. src/collectors/financial_collector.py를 먼저 실행하세요."
        )
    return pd.read_csv(path, dtype={"종목코드": str})


def gather_context(stock_code: str, perspective: str) -> dict:
    """관점에 필요한 데이터만 수집한다. 불필요한 호출을 하지 않는다."""
    from src.collectors.news_collector import (
        fetch_news,
        fetch_price_history,
        technical_summary,
    )

    from src.api.disclosure import fetch_important

    needed = PERSPECTIVES[perspective]["데이터"]
    context: dict = {}
    if "기술" in needed:
        # 일목균형표는 78거래일, 120일선은 120거래일이 필요해 1년치를 받는다
        context["tech"] = technical_summary(fetch_price_history(stock_code, pages=25))
    if "뉴스" in needed:
        context["news"] = fetch_news(stock_code)
    if "공시" in needed:
        context["disclosures"] = fetch_important(stock_code)
    return context


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    view = sys.argv[2] if len(sys.argv) > 2 else "종합"
    size = sys.argv[3] if len(sys.argv) > 3 else "압축형"

    df = load_financials()
    match = df[df["종목코드"] == code]
    if match.empty:
        sys.exit(f"{code}는 분석 대상에 없습니다.")

    out = analyze(match.iloc[0], view, size, **gather_context(code, view))
    report = out["리포트"]

    print(f"■ {out['종목명']} | {view} · {size} | {out['모델']}")
    print(f"\n【{report['헤드라인']}】\n")
    for point in report["핵심포인트"]:
        print(f"  · {point}")
    for section in report["섹션"]:
        print(f"\n▸ {section['소제목']}\n  {section['본문']}")
    print("\n[체크포인트]")
    for item in report["체크포인트"]:
        print(f"  · {item}")
    print("\n[리스크요인]")
    for item in report["리스크요인"]:
        print(f"  · {item}")
    print(f"\n[데이터한계] {report['데이터한계']}")

    if "토큰" in out:
        t = out["토큰"]
        cost = (t["입력"] / 1e6 * 0.25 + t["출력"] / 1e6 * 1.50) * 1400
        print(f"\n토큰 {t['입력']}/{t['출력']} → 약 {cost:.2f}원")
