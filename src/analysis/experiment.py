"""리포트 생성 A/B 테스트.

비용의 76%가 출력 토큰에서 나온다. 프롬프트에 분량 상한을 명시하면 출력이 줄어드는지,
줄어들 때 검증 통과율이 유지되는지를 무작위 배정으로 확인한다.

설계는 docs/experiments/2026-09-25-output-cap-v1.md 에 미리 적어 두었다.
지표를 나중에 고르면 좋아 보이는 것만 고르게 되므로 시작 전에 고정한다.
"""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "data" / "processed" / "experiments"

EXPERIMENT_ID = "output-cap-v1"

# 처치군에만 붙는 지시. 분량 기준 자체는 두 군이 같고, 그것을 상한으로 지키라는
# 문장과 중복 서술 금지만 추가한다. 내용 요건을 바꾸면 무엇이 효과인지 알 수 없다.
TREATMENT_SUFFIX = """
- 위 분량 기준은 목표가 아니라 상한이다. 더 짧게 쓸 수 있으면 짧게 써라.
- 같은 내용을 표현만 바꿔 반복하지 마라.
- 데이터에 없는 배경 설명이나 일반론으로 분량을 채우지 마라.
- 한 문장에 하나의 사실만 담아라."""


def enabled() -> bool:
    """EXPERIMENT_OFF=1 이면 전부 대조군으로 돌아간다(긴급 정지용)."""
    return os.getenv("EXPERIMENT_OFF", "") not in ("1", "true", "True")


def assign(stock_code: str) -> str:
    """종목코드로 군을 정한다.

    난수를 쓰지 않고 해시를 쓰는 이유는 같은 종목이 다시 생성돼도 같은 군에 남아야
    하기 때문이다. 재생성 때마다 군이 바뀌면 두 군의 내용이 섞인다.
    실험 ID를 소금으로 넣어 다음 실험에서 배정이 되풀이되지 않게 한다.
    """
    if not enabled():
        return "A"
    seed = f"{EXPERIMENT_ID}:{stock_code}".encode()
    return "AB"[int(hashlib.md5(seed).hexdigest(), 16) % 2]


def prompt_suffix(arm: str) -> str:
    return TREATMENT_SUFFIX if arm == "B" else ""


def log(record: dict) -> None:
    """관측치 한 건을 append 한다. 캐시로 응답한 건은 호출이 없었으므로 기록하지 않는다."""
    if not enabled():
        return
    record = {"실험": EXPERIMENT_ID, "기록시각": datetime.now().isoformat(timespec="seconds"), **record}
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"{EXPERIMENT_ID}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # 기록에 실패했다고 리포트 생성을 죽이지 않는다. 배포 환경은 파일이 휘발되고
        # 쓰기가 막힐 수도 있다. 실험 관측치보다 리포트가 나가는 것이 먼저다.
        pass
