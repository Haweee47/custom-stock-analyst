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

from src.analysis import money as money_module  # noqa: E402
from src.analysis import peer, usage_limit, verify  # noqa: E402
# app.py가 여기서 가져다 쓰므로 그대로 다시 내보낸다
from src.analysis.usage_limit import (  # noqa: E402,F401
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
# v3: 해외 시장 지원. 통화별 표기, 시장별 데이터 제약 안내, 증감률 비교 대상 명시
# v4: 추세를 한 방향으로 단정하는 문제 수정('968→977→948'을 3년 연속 감소로 적었다)
#     및 다른 계정의 증감률을 옮겨 쓰는 문제 수정
PROMPT_VERSION = 4

# 숫자 검증에 걸리면 다시 만들어 보는 횟수(첫 시도 포함). 2면 최대 한 번 더 부른다.
VERIFY_RETRIES = 2

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


def _retry_note(previous) -> str:
    """다시 만들 때 무엇이 틀렸는지 알려 준다. 같은 실수를 반복하지 않게."""
    _, _, checked = previous
    items = ", ".join(f"'{u['표기']}'" for u in checked["미확인"][:6])
    return (
        "[직전 시도에서 발견된 문제 — 반드시 고칠 것]\n"
        f"다음 숫자는 위 데이터에서 출처를 찾을 수 없었다: {items}\n"
        "데이터에 적힌 값을 그대로 쓰거나, 확실하지 않으면 그 수치를 빼고 서술하라. "
        "특히 금액은 조와 억을 바꿔 쓰지 말고, 증감률은 해당 계정의 값만 인용하라."
    )


# 시장을 파일 이름에 넣지 않으면 한국과 중국이 부딪친다. 심천도 6자리 코드를 쓰기
# 때문에 000810이 삼성화재이면서 창유디지털이다(실제로 54개가 겹친다).
# 그대로 두면 두 회사가 같은 캐시 파일을 쓰고, 삼성화재를 열었는데 중국 회사
# 리포트가 나온다.
MARKET_CODES = {"국내주식": "KR", "미국주식": "US", "일본주식": "JP", "중국주식": "CN"}


def market_code(country: str | None) -> str:
    return MARKET_CODES.get(country or "국내주식", "KR")


def _cache_path(stock_code: str, perspective: str, length: str, country: str | None = None) -> Path:
    return CACHE_DIR / f"{market_code(country)}_{stock_code}_{perspective}_{length}.json"


def load_cached(
    stock_code: str, perspective: str, length: str, country: str | None = None
) -> dict | None:
    path = _cache_path(stock_code, perspective, length, country)
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


def _money(value, currency: str = "KRW") -> str:
    """금액을 조·억으로 끊어 쓴다. 단위 이름은 통화를 따른다.

    억원으로 고정하면 삼성전자 매출이 '3,336,059.38억원'이 되는데, 모델이 이
    자릿수를 잘못 읽고 '3,336조원'으로 옮겨 적는 일이 실제로 있었다(실제 333.6조).
    사람이 읽는 방식대로 끊어 주면 그대로 베껴 쓰면 되므로 오독이 사라진다.
    """
    return money_module.money(value, currency)


def _growth(current, previous) -> str:
    """전년 대비 증감률. 적자에서 흑자로 돌아선 경우는 비율이 의미가 없다."""
    return money_module.growth(current, previous)


def _currency(row: pd.Series) -> str:
    value = row.get("통화")
    return "KRW" if value is None or pd.isna(value) else str(value)


def _basic_block(row: pd.Series) -> str:
    currency = _currency(row)
    lines = [
        f"- 종목명: {row['종목명']} ({row['종목코드']})",
        f"- 시장: {row['시장구분']}",
    ]
    english = row.get("영문명")
    if english and not pd.isna(english):
        lines.append(f"- 영문명: {english}")

    sector = row.get("업종_소분류")
    if sector and not pd.isna(sector) and sector != "미분류":
        group = row.get("업종_대분류")
        same = group is None or pd.isna(group) or group == sector
        lines.append(f"- 업종: {sector}" if same else f"- 업종: {group} > {sector}")

    lines.append(f"- 현재가: {money_module.price(row.get('현재가'), currency)}")
    if not pd.isna(row.get("등락률")):
        lines.append(f"- 전일 대비: {row.get('등락률'):+.2f}%")
    lines.append(f"- 시가총액: {_money(row.get('시가총액'), currency)}")
    if not pd.isna(row.get("외국인비율")):
        lines.append(f"- 외국인 지분율: {row.get('외국인비율'):.2f}%")

    # 통화를 못 박아 둬야 모델이 달러를 원화로 착각하지 않는다
    if currency != "KRW":
        unit = money_module.unit_of(currency)
        lines.append(f"- 표시 통화: {currency}. 모든 금액은 {unit} 기준이며 원화가 아니다.")

    return "[기본 정보]\n" + "\n".join(lines)


ACCOUNTS = ["매출액", "영업이익", "당기순이익"]


def _trend_block(row: pd.Series) -> str:
    """3개년 추이. 화면 표에는 있는데 프롬프트에 없어서 AI만 못 보던 부분이다."""
    base = row.get("기준연도")
    if base is None or pd.isna(base):
        return ""
    base = int(base)

    currency = _currency(row)
    lines = []
    for account in ACCOUNTS:
        values = [row.get(f"{account}_전전기"), row.get(f"{account}_전기"), row.get(account)]
        years = [base - 2, base - 1, base]

        # 값이 있는 해만 남긴다. '데이터 없음 → 데이터 없음 → 1,349억달러'는
        # 추이가 아니라 잡음이고, 모델이 그 빈칸을 감소로 읽을 수도 있다.
        have = [(year, value) for year, value in zip(years, values) if pd.notna(value)]
        if len(have) < 2:
            continue

        parts = [f"{year}년 {_money(value, currency)}" for year, value in have]
        if have[-1][0] == base and len(have) >= 2:
            parts[-1] += _growth(have[-1][1], have[-2][1])
        lines.append(f"- {account}: " + " → ".join(parts))

    if not lines:
        return ""
    return (
        f"[3개년 추이 ({base - 2}~{base}년)]\n"
        + "\n".join(lines)
        + f"\n(괄호 안 증감률은 {base - 1}년 대비 {base}년 값이다. 직전 연도 기준이며 "
        f"{base - 2}년 대비가 아니다. 이 추세를 반드시 분석에 반영하라.)"
    )


def _pbr(row: pd.Series) -> float | None:
    cap, equity = row.get("시가총액"), row.get("자본총계")
    if cap is None or equity is None or pd.isna(cap) or pd.isna(equity) or equity <= 0:
        return None
    return cap / equity


# 항목마다 (열 이름, 표기, 단위). 값이 없는 줄은 아예 넣지 않는다.
# 해외는 자산·부채·자본총계가 없는데 '데이터 없음'을 여섯 줄 늘어놓으면
# 모델이 그 빈칸을 근거처럼 다루거나 없는 값을 지어내기 쉽다.
MONEY_FIELDS = ["매출액", "영업이익", "당기순이익", "EBITDA", "자산총계", "부채총계", "자본총계"]
RATIO_FIELDS = [
    ("부채비율", "부채비율", "%"),
    ("영업이익률", "영업이익률", "%"),
    ("ROE_계산", "ROE", "%"),
    ("ROA", "ROA", "%"),
    ("PER", "PER", "배"),
    ("PBR", "PBR", "배"),
    ("배당수익률", "배당수익률", "%"),
]


def _financial_block(row: pd.Series) -> str:
    currency = _currency(row)
    period = f"{row.get('기준연도', '')}년"
    report = row.get("보고서")
    if report and not pd.isna(report):
        period += f" {report}"

    lines = [
        f"- {name}: {_money(row.get(name), currency)}"
        for name in MONEY_FIELDS
        if pd.notna(row.get(name))
    ]

    pbr = _pbr(row)
    for key, label, unit in RATIO_FIELDS:
        value = row.get(key)
        if key == "PBR" and (value is None or pd.isna(value)) and pbr is not None:
            value = pbr
        if pd.notna(value):
            lines.append(f"- {label}: {_fmt(value, unit)}")

    block = f"[재무 ({period} 기준)]\n" + "\n".join(lines)

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


def _market_limits(country: str) -> str:
    """이 시장에서 못 쓰는 재료를 미리 알려 준다.

    관점 지시문은 국내 기준으로 쓰여 있어서 '부채비율과 ROE를 다뤄라'라고 말한다.
    해외 종목에 그대로 주면 모델이 없는 값을 지어내거나 '확인 불가'를 반복한다.
    """
    from src.collectors import markets

    if country == markets.KOREA:
        return ""

    missing = []
    if country not in markets.HAS_DISCLOSURE:
        missing.append("공시")
    if country not in markets.HAS_NEWS:
        missing.append("뉴스")

    lines = [
        "\n[이 시장의 데이터 제약 — 반드시 지켜라]",
        "- 자산·부채·자본총계가 제공되지 않는다. 따라서 부채비율과 ROE는 알 수 없다. "
        "위 지시에 그 지표가 있더라도 다루지 마라. 추정하지도 마라.",
        "- 재무 안정성을 논할 근거가 없으므로 '재무가 건전하다/불안하다'고 단정하지 마라.",
        "- 수익성은 영업이익률, 자본 효율성은 ROA로 대신 본다. "
        "영업이익은 EBIT(이자·세금 차감 전 이익) 기준이다.",
    ]
    if missing:
        lines.append(
            f"- {'·'.join(missing)} 데이터가 제공되지 않는다. 그 내용을 지어내지 말고, "
            "재무와 주가로 확인되는 것만 서술하라."
        )
    return "\n".join(lines)


def build_prompt(
    row: pd.Series,
    perspective: str,
    length: str,
    tech: dict | None = None,
    news: list[dict] | None = None,
    disclosures: list[dict] | None = None,
    universe: pd.DataFrame | None = None,
) -> str:
    from src.collectors import markets

    spec, size = PERSPECTIVES[perspective], LENGTHS[length]
    country = row.get("국가") or markets.KOREA

    blocks = [_basic_block(row)]
    if "재무" in spec["데이터"]:
        blocks.append(_financial_block(row))
    if "동종업계" in spec["데이터"] and universe is not None:
        blocks.append(peer.peer_block(row, universe))
    if "기술" in spec["데이터"]:
        blocks.append(_technical_block(tech or {}))
    # 시장에 없는 재료는 블록 자체를 넣지 않는다. '없음'이라고 적어 두면
    # 모델이 그것을 사실처럼 다루거나 빈칸을 채우려 든다.
    if "뉴스" in spec["데이터"] and markets.has_news(country):
        blocks.append(_news_block(news or []))
    if "공시" in spec["데이터"] and markets.has_disclosure(country):
        blocks.append(_disclosure_block(disclosures or []))

    data = "\n\n".join(blocks)
    limits = _market_limits(country)
    return f"""다음 데이터로 기업 리포트를 작성하라.

{data}

[분석 관점: {perspective}]
{spec['지시']}{limits}

[분량: {length}]
- 섹션 {size['섹션수']}, {size['본문길이']}
- 핵심포인트 {size['포인트수']}

[출력 전 자기 점검]
- 금액은 위 데이터에 적힌 표기를 그대로 옮겼는가? 조와 억을 바꿔 쓰지 않았는가?
- 통화를 바꿔 쓰지 않았는가? 달러를 원으로 적지 않았는가?
- 증감률을 쓸 때 비교 대상을 정확히 밝혔는가? 주어진 증감률은 직전 연도 대비다.
  'A년 대비 B% 증가'라고 쓸 거라면 그 A년과 B가 실제로 짝이 맞는지 확인하라.
  짝이 맞는지 자신이 없으면 비율 대신 '늘었다/줄었다'로만 쓰라.
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
        cached = load_cached(stock_code, perspective, length, row.get("국가"))
        if cached:
            return cached

    usage_limit.check(length, session=not batch)

    prompt = build_prompt(row, perspective, length, tech, news, disclosures, universe)
    peers = (
        peer.sector_stats(universe, row.get("업종_소분류"), row) if universe is not None else None
    )

    # 숫자가 틀리면 한 번 다시 만든다. 프롬프트 규칙으로 줄일 수는 있어도 없앨 수는
    # 없어서(실제로 10배 오독·증감률 오지정을 겪었다) 생성 뒤에 기계로 검산한다.
    attempts = []
    for attempt in range(1, VERIFY_RETRIES + 1):
        response = _client().models.generate_content(
            model=MODEL,
            contents=prompt if attempt == 1 else f"{prompt}\n\n{_retry_note(attempts[-1])}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_RULES,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
            ),
        )
        usage = response.usage_metadata
        report = json.loads(response.text)
        checked = verify.verify(report, row, peers, tech, news, disclosures)
        attempts.append((report, usage, checked))
        if checked["통과"]:
            break
        print(
            f"[검증] {row['종목명']} {perspective} — 출처 미확인 {len(checked['미확인'])}건"
            f" (시도 {attempt}/{VERIFY_RETRIES})",
            file=sys.stderr,
        )

    # 다시 만들어도 안 되면 대조율이 가장 높은 것을 쓰고 결과를 함께 남긴다
    report, usage, checked = max(attempts, key=lambda a: a[2]["대조율"])

    result = {
        "종목코드": stock_code,
        "종목명": row["종목명"],
        "관점": perspective,
        "분량": length,
        "리포트": report,
        "모델": MODEL,
        "프롬프트버전": PROMPT_VERSION,
        "생성시각": datetime.now().isoformat(timespec="seconds"),
        "면책": DISCLAIMER,
        "검증": checked,
        "생성시도": len(attempts),
        "토큰": {"입력": usage.prompt_token_count, "출력": usage.candidates_token_count},
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(stock_code, perspective, length, row.get("국가")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 재시도까지 실제 호출한 횟수만큼 사용량을 센다
    for _ in attempts:
        usage_limit.record(length, session=not batch)
    return result


def _usage_today(length: str | None = None) -> int:
    return usage_limit.used_today(length)


def load_financials(year: int = 2025) -> pd.DataFrame:
    path = PROCESSED_DIR / f"financials_{year}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path}가 없습니다. src/collectors/financial_collector.py를 먼저 실행하세요."
        )
    return pd.read_csv(path, dtype={"종목코드": str})


@lru_cache(maxsize=1)
def load_universe() -> pd.DataFrame:
    """국내와 해외를 합친 전체 종목 표. 동종업계 비교의 모집단이다."""
    from src.collectors.markets import load_all

    return load_all()


def gather_context(row, perspective: str) -> dict:
    """관점에 필요한 데이터만 모은다. 시장에 없는 재료는 아예 부르지 않는다.

    해외는 뉴스와 공시가 없다. 없는 것을 빈 값으로 넘기면 모델이 '뉴스 없음'을
    근거처럼 다루므로, 애초에 그 관점을 열지 않는 쪽(markets.PERSPECTIVES)과
    여기서 호출을 건너뛰는 쪽을 함께 둔다.
    """
    from src.collectors import markets

    # 문자열(종목코드)로 불러도 동작하도록 남겨 둔다 - 국내 CLI에서 그렇게 쓴다
    if isinstance(row, str):
        universe = load_universe()
        match = universe[universe["종목코드"] == row]
        if match.empty:
            raise ValueError(f"{row}는 분석 대상에 없습니다.")
        row = match.iloc[0]

    country = row.get("국가") or markets.KOREA
    code = row["종목코드"]
    needed = PERSPECTIVES[perspective]["데이터"]
    context: dict = {}

    if "동종업계" in needed:
        context["universe"] = load_universe()
    if "기술" in needed:
        try:
            prices = markets.price_history(country, code, row.get("조회코드"))
            context["tech"] = technical_summary(prices) if not prices.empty else {}
        except Exception as exc:
            print(f"[시세 조회 실패] {code}: {type(exc).__name__}: {exc}", file=sys.stderr)
            context["tech"] = {}
    if "뉴스" in needed and markets.has_news(country):
        from src.collectors.news_collector import fetch_news

        context["news"] = fetch_news(code)
    if "공시" in needed and markets.has_disclosure(country):
        from src.api.disclosure import fetch_important

        context["disclosures"] = fetch_important(code)

    return context


def technical_summary(prices: pd.DataFrame) -> dict:
    from src.collectors.news_collector import technical_summary as summarize

    return summarize(prices)


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    # --force: 캐시를 무시하고 다시 생성한다 (프롬프트를 고친 뒤 결과를 확인할 때 쓴다)
    force_new = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    code = args[0] if len(args) > 0 else "005930"
    view = args[1] if len(args) > 1 else "종합"
    size = args[2] if len(args) > 2 else "압축형"

    # 국내·해외가 합쳐진 표를 써야 동종업계 비교 블록이 채워진다
    df = load_universe()
    match = df[df["종목코드"] == code]
    if match.empty:
        sys.exit(f"{code}는 분석 대상에 없습니다.")

    row = match.iloc[0]
    out = analyze(row, view, size, force=force_new, **gather_context(row, view))
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
