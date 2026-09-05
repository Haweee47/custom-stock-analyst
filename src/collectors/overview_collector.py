"""회사가 무엇을 하는 곳인지 한 문단으로 가져온다.

숫자만 있는 리포트는 '이 회사가 뭐 하는 데인지'를 답해 주지 않는다. 삼성전자야
누구나 알지만, 이 서비스의 대상인 초소형주는 이름만 봐서는 알 수가 없다.

모델에게 설명을 맡기면 안 된다. 대형주는 그럴듯하게 쓰지만 초소형주에서는
지어낸다. 그리고 숫자 검증기는 '이 회사는 무엇을 만든다'는 문장이 참인지
가려내지 못한다. 그래서 출처에서 받아 와 그대로 인용한다.

  국내 - 네이버 금융이 쓰는 wisereport의 기업개요 문단
  해외 - 네이버 해외주식 API의 corporateOverview

받아 온 문장은 캐시에 쌓아 두고 재사용한다. 회사 설명은 자주 바뀌지 않는다.
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PROCESSED_DIR = ROOT / "data" / "processed"
CACHE_PATH = PROCESSED_DIR / "overviews.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 20

DOMESTIC_URL = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx"
OVERSEAS_URL = "https://api.stock.naver.com/stock/{code}/integration"

# 기업개요 문단은 대개 '동사는/당사는'으로 시작해 지표 표 직전에서 끝난다
OPENING = re.compile(r"(동사는|당사는|본사는|당사|동사)\s")
STOP_WORDS = ("펀더멘털", "주요지표", "펀더멘탈", "Financial", "재무분석")

# 너무 짧으면 설명이 아니라 잘린 조각이다
MIN_LENGTH = 40
MAX_LENGTH = 600


def _read_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cache(cache: dict) -> None:
    try:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_domestic(stock_code: str) -> str | None:
    """wisereport 기업개요. 네이버 금융 종목 화면이 쓰는 것과 같은 출처다."""
    try:
        response = requests.get(
            DOMESTIC_URL, params={"cmp_cd": stock_code}, headers=HEADERS, timeout=TIMEOUT
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    text = _clean(response.text)
    match = OPENING.search(text)
    if not match:
        return None

    body = text[match.start():]
    # 지표 표가 시작되는 지점에서 자른다
    cut = min((body.find(word) for word in STOP_WORDS if body.find(word) > 0), default=-1)
    if cut > 0:
        body = body[:cut]

    body = body.strip()[:MAX_LENGTH].strip()
    return body if len(body) >= MIN_LENGTH else None


def fetch_overseas(lookup_code: str) -> str | None:
    """네이버 해외주식 API가 한국어 사업 설명을 함께 준다."""
    try:
        response = requests.get(
            OVERSEAS_URL.format(code=lookup_code), headers=HEADERS, timeout=TIMEOUT
        )
        response.raise_for_status()
        overview = (response.json() or {}).get("corporateOverview")
    except (requests.RequestException, ValueError):
        return None

    if not overview:
        return None
    body = _clean(str(overview))[:MAX_LENGTH].strip()
    return body if len(body) >= MIN_LENGTH else None


def get(country: str, stock_code: str, lookup_code: str | None = None, refresh: bool = False) -> str | None:
    """회사 개요 한 문단. 한 번 받아 온 것은 캐시에서 꺼낸다."""
    from src.collectors.markets import KOREA

    key = f"{country}:{stock_code}"
    cache = _read_cache()
    if not refresh and key in cache:
        # 못 받은 것도 기록해 두고 매번 다시 두드리지 않는다
        return cache[key] or None

    body = fetch_domestic(stock_code) if country == KOREA else fetch_overseas(lookup_code or stock_code)
    cache[key] = body or ""
    _write_cache(cache)
    return body


def collect(rows, delay: float = 0.15) -> int:
    """여러 종목의 개요를 미리 받아 둔다. 캐시에 있으면 건너뛴다."""
    from src.collectors.progress import track

    cache = _read_cache()
    added = 0
    for row in track(list(rows), desc="기업개요 수집"):
        key = f"{row['국가']}:{row['종목코드']}"
        if key in cache:
            continue
        time.sleep(delay)
        body = get(row["국가"], str(row["종목코드"]), row.get("조회코드"))
        if body:
            added += 1
    return added


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    from src.collectors import markets

    top = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    universe = markets.load_all()
    picked = []
    for country in [markets.KOREA, *markets.COUNTRIES.values()]:
        pool = universe[universe["국가"] == country].dropna(subset=["시가총액_원화"])
        picked.extend(pool.nlargest(top, "시가총액_원화").to_dict("records"))

    print(f"대상 {len(picked):,}개 종목")
    print(f"새로 받은 개요 {collect(picked):,}건")
