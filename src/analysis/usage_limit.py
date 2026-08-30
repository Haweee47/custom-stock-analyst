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

# 프로세스가 살아 있는 동안 유지되는 카운터. Streamlit이 스크립트를 다시 돌려도
# 모듈은 다시 임포트되지 않으므로 값이 남는다.
_process_counts: dict[str, int] = {}


class DailyLimitReached(RuntimeError):
    """하루 신규 생성 상한에 도달했을 때."""


class SessionLimitReached(RuntimeError):
    """한 방문자가 한 번에 만들 수 있는 양을 넘겼을 때."""


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _file_count() -> int:
    if not USAGE_PATH.exists():
        return 0
    try:
        return json.loads(USAGE_PATH.read_text(encoding="utf-8")).get(_today(), 0)
    except (json.JSONDecodeError, OSError):
        return 0


def used_today() -> int:
    return max(_file_count(), _process_counts.get(_today(), 0))


def remaining_today() -> int:
    return max(DAILY_LIMIT - used_today(), 0)


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


def check() -> None:
    """생성 전에 호출한다. 한도를 넘었으면 예외를 던진다."""
    if used_today() >= DAILY_LIMIT:
        raise DailyLimitReached(
            f"오늘 새로 만들 수 있는 리포트({DAILY_LIMIT}건)를 모두 사용했습니다. "
            "이미 만들어진 리포트는 계속 보실 수 있고, 내일 다시 생성됩니다."
        )
    if session_used() >= SESSION_LIMIT:
        raise SessionLimitReached(
            f"한 번에 만들 수 있는 리포트는 {SESSION_LIMIT}건까지입니다. "
            "잠시 후 페이지를 새로 열면 다시 만들 수 있습니다."
        )


def record() -> None:
    """생성에 성공한 뒤 호출한다."""
    today = _today()
    _process_counts[today] = _process_counts.get(today, 0) + 1

    log = {}
    if USAGE_PATH.exists():
        try:
            log = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log = {}
    log[today] = max(log.get(today, 0), _process_counts[today])
    try:
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        USAGE_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 배포 환경에서 쓰기가 막혀도 프로세스 카운터는 살아 있다

    state = _session_state()
    if state is not None:
        state["gemini_session_count"] = session_used() + 1
