"""데이터가 언제 만들어졌는지 기록하고 읽는다.

주식 서비스에서 이틀 전 시세를 오늘 값처럼 보여주면 오해를 부른다.
배치가 돌 때마다 기준일을 남기고 화면에 그대로 표시한다.
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
META_PATH = ROOT / "data" / "processed" / "dataset_meta.json"

# 한국 시장 데이터이므로 날짜는 한국 시간으로 센다. 수집은 GitHub Actions(UTC)에서 돌고
# 배포도 UTC 서버라, 그냥 now()를 쓰면 화면에 '시세 기준 2026-09-20 (-1일 전)'처럼
# 음수가 찍힌다. 실제로 그렇게 나왔다.
KST = ZoneInfo("Asia/Seoul")


def now() -> datetime:
    return datetime.now(KST)

LABELS = {
    "시세": "국내 주가·시가총액",
    "재무": "국내 재무제표",
    "업종": "국내 업종 분류",
    "공시": "국내 공시 등급",
    "해외시세": "해외 주가·시가총액",
    "해외재무": "해외 재무제표",
}


def stamp(dataset: str, note: str = "") -> None:
    meta = read()
    meta[dataset] = {
        "갱신": now().strftime("%Y-%m-%d %H:%M"),
        "비고": note,
    }
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def read() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def oldest_date() -> str | None:
    """가장 오래된 데이터의 날짜. 화면에 '기준일'로 쓴다."""
    meta = read()
    dates = [v.get("갱신", "")[:10] for v in meta.values() if v.get("갱신")]
    return min(dates) if dates else None


def date_of(name: str) -> str | None:
    """항목 하나의 갱신일('시세', '재무', '공시' 등). 없으면 None."""
    stamp = (read().get(name) or {}).get("갱신", "")[:10]
    return stamp or None


def price_date() -> str | None:
    """시세 기준일. 매일 바뀌는 값이라 '데이터가 낡았는가'는 이것으로 판단한다."""
    stamp = (read().get("시세") or {}).get("갱신", "")[:10]
    return stamp or None


def days_old() -> int | None:
    """시세가 며칠 된 것인지.

    예전에는 가장 오래된 항목을 기준으로 삼았다. 그런데 가장 오래된 것은 거의 언제나
    재무(연간 사업보고서)라, 시세가 오늘 것이어도 화면에 '19일 전' 경고가 떠 있었다.
    낡아서 문제가 되는 것은 매일 바뀌는 시세다. 항목별 날짜는 '데이터별 갱신 시각'에 있다.
    """
    stamp = price_date()
    if not stamp:
        return None
    age = (now().date() - datetime.strptime(stamp, "%Y-%m-%d").date()).days
    # 수집이 배포 서버보다 앞선 시간대에서 돌면 음수가 나올 수 있다. 그건 '오늘'이다.
    return max(age, 0)


def summary_line() -> str:
    """사이드바 한 줄 요약."""
    stamp = price_date()
    if not stamp:
        return "데이터 기준일 정보 없음"
    age = days_old()
    when = "오늘" if age == 0 else "어제" if age == 1 else f"{age}일 전"
    return f"시세 기준 {stamp} ({when})"
