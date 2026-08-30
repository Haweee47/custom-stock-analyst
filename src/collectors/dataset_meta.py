"""데이터가 언제 만들어졌는지 기록하고 읽는다.

주식 서비스에서 이틀 전 시세를 오늘 값처럼 보여주면 오해를 부른다.
배치가 돌 때마다 기준일을 남기고 화면에 그대로 표시한다.
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
META_PATH = ROOT / "data" / "processed" / "dataset_meta.json"

LABELS = {
    "시세": "주가·시가총액",
    "재무": "재무제표",
    "업종": "업종 분류",
    "공시": "공시 등급",
}


def stamp(dataset: str, note: str = "") -> None:
    meta = read()
    meta[dataset] = {
        "갱신": datetime.now().strftime("%Y-%m-%d %H:%M"),
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


def days_old() -> int | None:
    oldest = oldest_date()
    if not oldest:
        return None
    return (datetime.now().date() - datetime.strptime(oldest, "%Y-%m-%d").date()).days


def summary_line() -> str:
    """사이드바 한 줄 요약."""
    oldest = oldest_date()
    if not oldest:
        return "데이터 기준일 정보 없음"
    age = days_old()
    if age == 0:
        return f"데이터 기준 {oldest} (오늘)"
    return f"데이터 기준 {oldest} ({age}일 전)"
