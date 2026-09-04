"""Gemini 신규 생성 건수를 세 겹으로 제한한다.

파일 카운터만 쓰면 배포 환경에서 뚫린다. Streamlit Cloud는 앱이 잠들었다
깨어날 때 실행 중 만든 파일을 지우므로, 재시작마다 카운터가 0으로 돌아간다.
그래서 다음 세 가지를 함께 본다.

  파일   - 로컬 개발에서 날짜별로 누적. 배포에서는 재시작 시 사라진다.
  프로세스 - 앱이 살아 있는 동안 모든 방문자가 공유. 재시작 전까지 유효하다.
  세션   - 방문자 한 명이 한 번에 태울 수 있는 양을 따로 막는다.

파일과 프로세스 중 큰 값을 오늘 사용량으로 본다.
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
USAGE_PATH = ROOT / "data" / "processed" / "gemini_usage.json"

DAILY_LIMIT = 100
SESSION_LIMIT = 10

# 분량별 하루 상한. 상세형은 출력 토큰이 두 배 가까워 1건 5.03원으로 압축형(3.07원)보다
# 비싸다. 비용의 대부분(76%)이 출력에서 나오므로, 전체 상한과 별개로 긴 리포트만
# 따로 조인다. 품질을 낮추지 않고 최악의 비용을 누르는 방법이다.
LENGTH_LIMITS = {"상세형": 10}

# 전체 사용량을 세는 키. 분량 이름과 겹치지 않게 둔다.
TOTAL = "전체"

# 프로세스가 살아 있는 동안 유지되는 카운터. Streamlit이 스크립트를 다시 돌려도
# 모듈은 다시 임포트되지 않으므로 값이 남는다. {날짜: {키: 건수}}
_process_counts: dict[str, dict[str, int]] = {}


class DailyLimitReached(RuntimeError):
    """하루 신규 생성 상한에 도달했을 때."""


class SessionLimitReached(RuntimeError):
    """한 방문자가 한 번에 만들 수 있는 양을 넘겼을 때."""


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize(value) -> dict[str, int]:
    """예전 형식({날짜: 정수})도 읽을 수 있게 맞춘다."""
    if isinstance(value, int):
        return {TOTAL: value}
    if isinstance(value, dict):
        return {k: int(v) for k, v in value.items() if isinstance(v, int)}
    return {}


def _read_log() -> dict[str, dict[str, int]]:
    if not USAGE_PATH.exists():
        return {}
    try:
        raw = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {day: _normalize(value) for day, value in raw.items()}


def _file_count(key: str = TOTAL) -> int:
    return _read_log().get(_today(), {}).get(key, 0)


def used_today(length: str | None = None) -> int:
    """오늘 사용량. length를 주면 그 분량만 센다."""
    key = length or TOTAL
    process = _process_counts.get(_today(), {}).get(key, 0)
    return max(_file_count(key), process)


def remaining_today(length: str | None = None) -> int:
    """남은 건수. 분량 상한이 있으면 전체 상한과 함께 보고 더 작은 쪽을 돌려준다."""
    left = max(DAILY_LIMIT - used_today(), 0)
    if length and length in LENGTH_LIMITS:
        left = min(left, max(LENGTH_LIMITS[length] - used_today(length), 0))
    return left


def _session_state():
    """Streamlit이 없으면(스크립트 실행) 세션 제한을 적용하지 않는다."""
    try:
        import streamlit as st

        return st.session_state
    except Exception:
        return None


def session_used() -> int:
    state = _session_state()
    if state is None:
        return 0
    return state.get("gemini_session_count", 0)


def check(length: str | None = None, session: bool = True) -> None:
    """생성 전에 호출한다. 한도를 넘었으면 예외를 던진다.

    session=False는 운영자가 돌리는 배치용이다. 세션 상한은 '방문자 한 명이 한 번에
    너무 많이 태우는 것'을 막는 장치라 배치에는 해당하지 않는다. 반면 일일 상한은
    실제 비용의 상한선이므로 배치에도 그대로 건다.
    """
    if used_today() >= DAILY_LIMIT:
        raise DailyLimitReached(
            f"오늘 새로 만들 수 있는 리포트({DAILY_LIMIT}건)를 모두 사용했습니다. "
            "이미 만들어진 리포트는 계속 보실 수 있고, 내일 다시 생성됩니다."
        )

    limit = LENGTH_LIMITS.get(length or "")
    if limit is not None and used_today(length) >= limit:
        raise DailyLimitReached(
            f"오늘 만들 수 있는 {length} 리포트({limit}건)를 모두 사용했습니다. "
            "압축형은 아직 만들 수 있고, 상세형은 내일 다시 열립니다."
        )

    if session and session_used() >= SESSION_LIMIT:
        raise SessionLimitReached(
            f"한 번에 만들 수 있는 리포트는 {SESSION_LIMIT}건까지입니다. "
            "잠시 후 페이지를 새로 열면 다시 만들 수 있습니다."
        )


def record(length: str | None = None, session: bool = True) -> None:
    """생성에 성공한 뒤 호출한다.

    session=False면 세션 카운터를 건드리지 않는다. 배치에는 세션이라는 개념이
    없을뿐더러, streamlit 밖에서 session_state에 접근하면 경고가 줄줄이 찍힌다.
    """
    today = _today()
    keys = [TOTAL] + ([length] if length else [])

    process = _process_counts.setdefault(today, {})
    for key in keys:
        process[key] = process.get(key, 0) + 1

    log = _read_log()
    # 파일 카운터는 그 자체로 누적시킨다. 프로세스 카운터와 max를 취하면, 새 프로세스가
    # 0에서 시작하므로 앞선 프로세스가 쌓아 둔 사용량이 지워진다. (배치를 한 번 돌리면
    # 그날 방문자들이 만든 건수가 통째로 사라졌다.)
    entry = log.setdefault(today, {})
    for key in keys:
        entry[key] = entry.get(key, 0) + 1
    try:
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        USAGE_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 배포 환경에서 쓰기가 막혀도 프로세스 카운터는 살아 있다

    if not session:
        return
    state = _session_state()
    if state is not None:
        state["gemini_session_count"] = session_used() + 1
