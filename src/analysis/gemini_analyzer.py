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
from functools import lru_cache
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

from src.analysis import peer, usage_limit  # noqa: E402
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

# 프롬프트를 고치면 이 숫자를 올린다. 낮은 버전으로 만들어진 캐시는 만료로 처리한다.
# 이것이 없으면 프롬프트 버그를 고쳐도 이미 저장된 리포트가 7일간 그대로 나간다.
# v2: 금액을 조·억 표기로 바꾸고(10배 오독 수정) 3개년 추이·동종업계 비교를 추가
PROMPT_VERSION = 2

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
    if data.get("프롬프트버전", 1) < PROMPT_VERSION:
        return None
    created = datetime.fromisoformat(data["생성시각"])
    if datetime.now() - created > timedelta(days=CACHE_TTL_DAYS):
        return None
    return data


def _fmt(value, unit: str = "", scale: float = 1.0) -> str:
    if value is None or pd.isna(value):
        return "데이터 없음"
    return f"{value / scale:,.2f}{unit}"


def _money(value) -> str:
    """금액을 조·억으로 끊어 쓴다.

    억원으로 고정하면 삼성전자 매출이 '3,336,059.38억원'이 되는데, 모델이 이
    자릿수를 잘못 읽고 '3,336조원'으로 옮겨 적는 일이 실제로 있었다(실제 333.6조).
    사람이 읽는 방식대로 끊어 주면 그대로 베껴 쓰면 되므로 오독이 사라진다.
    """
    if value is None or pd.isna(value):
        return "데이터 없음"

    sign = "-" if value < 0 else ""
    amount = abs(float(value))
    trillion, remainder = divmod(amount, 1e12)
    billion = remainder / 1e8

    if trillion >= 1:
        return f"{sign}{trillion:,.0f}조 {billion:,.0f}억원"
    if amount >= 1e8:
        return f"{sign}{billion:,.0f}억원"
    return f"{sign}{amount:,.0f}원"


def _growth(current, previous) -> str:
    """전년 대비 증감률. 적자에서 흑자로 돌아선 경우는 비율이 의미가 없다."""
    if current is None or previous is None or pd.isna(current) or pd.isna(previous):
        return ""
    if previous == 0:
        return ""
    if previous < 0 < current:
        return " (흑자 전환)"
    if current < 0 < previous:
        return " (적자 전환)"
    rate = (current - previous) / abs(previous) * 100
    return f" ({rate:+.1f}%)"


def _basic_block(row: pd.Series) -> str:
    lines = [
        f"- 종목명: {row['종목명']} ({row['종목코드']})",
        f"- 시장: {row['시장구분']}",
    ]
    sector = row.get("업종_소분류")
    if sector and not pd.isna(sector) and sector != "미분류":
        group = row.get("업종_대분류")
        lines.append(f"- 업종: {group} > {sector}" if group and not pd.isna(group) else f"- 업종: {sector}")

    price = row.get("현재가")
    lines.append(f"- 현재가: {'데이터 없음' if pd.isna(price) else f'{price:,.0f}원'}")
    if not pd.isna(row.get("등락률")):
        lines.append(f"- 전일 대비: {row.get('등락률'):+.2f}%")
    lines.append(f"- 시가총액: {_money(row.get('시가총액'))}")
    if not pd.isna(row.get("외국인비율")):
        lines.append(f"- 외국인 지분율: {row.get('외국인비율'):.2f}%")

    return "[기본 정보]\n" + "\n".join(lines)


ACCOUNTS = ["매출액", "영업이익", "당기순이익"]


def _trend_block(row: pd.Series) -> str:
    """3개년 추이. 화면 표에는 있는데 프롬프트에 없어서 AI만 못 보던 부분이다."""
    base = row.get("기준연도")
    if base is None or pd.isna(base):
        return ""
    base = int(base)

    lines = []
    for account in ACCOUNTS:
        values = [row.get(f"{account}_전전기"), row.get(f"{account}_전기"), row.get(account)]
        if all(v is None or pd.isna(v) for v in values):
            continue
        parts = [f"{base - 2}년 {_money(values[0])}", f"{base - 1}년 {_money(values[1])}"]
        parts.append(f"{base}년 {_money(values[2])}{_growth(values[2], values[1])}")
        lines.append(f"- {account}: " + " → ".join(parts))

    if not lines:
        return ""
    return (
        f"[3개년 추이 ({base - 2}~{base}년)]\n"
        + "\n".join(lines)
        + "\n(괄호 안은 전년 대비 증감률이다. 이 추세를 반드시 분석에 반영하라.)"
    )


def _pbr(row: pd.Series) -> float | None:
    cap, equity = row.get("시가총액"), row.get("자본총계")
    if cap is None or equity is None or pd.isna(cap) or pd.isna(equity) or equity <= 0:
        return None
    return cap / equity


def _financial_block(row: pd.Series) -> str:
    pbr = _pbr(row)
    block = f"""[재무 ({row.get('기준연도', '')}년 {row.get('보고서', '')} 기준)]
- 매출액: {_money(row.get('매출액'))}
- 영업이익: {_money(row.get('영업이익'))}
- 당기순이익: {_money(row.get('당기순이익'))}
- 자산총계: {_money(row.get('자산총계'))}
- 부채총계: {_money(row.get('부채총계'))}
- 자본총계: {_money(row.get('자본총계'))}
- 부채비율: {_fmt(row.get('부채비율'), '%')}
- 영업이익률: {_fmt(row.get('영업이익률'), '%')}
- ROE: {_fmt(row.get('ROE_계산'), '%')}
- PER: {_fmt(row.get('PER'), '배')}"""
    if pbr is not None:
        block += f"\n- PBR: {pbr:,.2f}배"

    trend = _trend_block(row)
    return f"{block}\n\n{trend}" if trend else block


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
    universe: pd.DataFrame | None = None,
) -> str:
    spec, size = PERSPECTIVES[perspective], LENGTHS[length]

    blocks = [_basic_block(row)]
    if "재무" in spec["데이터"]:
        blocks.append(_financial_block(row))
    if "동종업계" in spec["데이터"] and universe is not None:
        blocks.append(peer.peer_block(row, universe))
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
- 핵심포인트 {size['포인트수']}

[출력 전 자기 점검]
- 금액은 위 데이터에 적힌 표기를 그대로 옮겼는가? 조와 억을 바꿔 쓰지 않았는가?
- 데이터에 없는 수치를 하나라도 새로 만들어내지 않았는가?
- '데이터한계'에 쓴 내용이 실제로 주어진 데이터 범위와 일치하는가?"""


def analyze(
    row: pd.Series,
    perspective: str = "종합",
    length: str = "압축형",
    tech: dict | None = None,
    news: list[dict] | None = None,
    disclosures: list[dict] | None = None,
    universe: pd.DataFrame | None = None,
    force: bool = False,
    batch: bool = False,
) -> dict:
    """한 종목을 분석한다. 캐시가 있으면 API를 호출하지 않는다.

    batch=True는 운영자가 미리 채우는 배치용으로, 세션 상한을 적용하지 않는다.
    일일 상한은 비용의 상한선이므로 배치에도 그대로 걸린다.
    """
    stock_code = row["종목코드"]

    if not force:
        cached = load_cached(stock_code, perspective, length)
        if cached:
            return cached

    usage_limit.check(session=not batch)

    response = _client().models.generate_content(
        model=MODEL,
        contents=build_prompt(row, perspective, length, tech, news, disclosures, universe),
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
        "프롬프트버전": PROMPT_VERSION,
        "생성시각": datetime.now().isoformat(timespec="seconds"),
        "면책": DISCLAIMER,
        "토큰": {"입력": usage.prompt_token_count, "출력": usage.candidates_token_count},
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(stock_code, perspective, length).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    usage_limit.record(session=not batch)
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


@lru_cache(maxsize=1)
def load_universe(year: int = 2025) -> pd.DataFrame:
    """재무에 업종을 붙인 전체 종목 표. 동종업계 비교의 모집단이다."""
    from src.collectors.sector_collector import load as load_sectors

    df = load_financials(year)
    sectors = load_sectors()
    if sectors.empty:
        df["업종_대분류"] = "미분류"
        df["업종_소분류"] = "미분류"
        return df
    merged = df.merge(sectors, on="종목코드", how="left")
    columns = ["업종_대분류", "업종_소분류"]
    merged[columns] = merged[columns].fillna("미분류")
    return merged


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
    if "동종업계" in needed:
        context["universe"] = load_universe()
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

    # --force: 캐시를 무시하고 다시 생성한다 (프롬프트를 고친 뒤 결과를 확인할 때 쓴다)
    force_new = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    code = args[0] if len(args) > 0 else "005930"
    view = args[1] if len(args) > 1 else "종합"
    size = args[2] if len(args) > 2 else "압축형"

    # 업종이 붙은 표를 써야 동종업계 비교 블록이 채워진다
    df = load_universe()
    match = df[df["종목코드"] == code]
    if match.empty:
        sys.exit(f"{code}는 분석 대상에 없습니다.")

    out = analyze(match.iloc[0], view, size, force=force_new, **gather_context(code, view))
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
