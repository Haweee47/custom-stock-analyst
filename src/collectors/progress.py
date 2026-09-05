"""진행률 표시. 터미널이면 tqdm 한 줄로 갱신하고, 로그로 나갈 때는 띄엄띄엄 찍는다.

tqdm은 커서를 되감아(\\r) 같은 줄을 다시 쓴다. GitHub Actions처럼 터미널이 아닌
곳에서는 되감기가 먹지 않아 갱신할 때마다 줄이 쌓인다. 실제로 KOSPI 49페이지를
받는 동안 로그가 100줄 넘게 밀려서, 뒤 단계의 실패 원인을 찾으려면 한참
스크롤해야 했다.

그래서 로그로 나갈 때는 tqdm을 쓰지 않고 30초에 한 줄씩 직접 찍는다.
진행 중이라는 신호는 남으면서 로그는 읽을 수 있다.
"""
import sys
import time

from tqdm import tqdm

# 터미널이 아닐 때 진행 상황을 찍는 간격(초)
LOG_INTERVAL = 30


def is_terminal() -> bool:
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def _length_of(iterable) -> int | None:
    try:
        return len(iterable)
    except TypeError:
        return None


def _logged(iterable, desc: str, interval: float):
    total = _length_of(iterable)
    started = last = time.time()
    count = 0

    for item in iterable:
        yield item
        count += 1
        now = time.time()
        if now - last >= interval:
            last = now
            share = f"{count:,}/{total:,} ({count / total * 100:.0f}%)" if total else f"{count:,}건"
            print(f"  {desc}: {share} · {now - started:.0f}초", flush=True)

    elapsed = time.time() - started
    print(f"  {desc}: 완료 {count:,}건 · {elapsed:.0f}초", flush=True)


def track(iterable, desc: str = "", interval: float = LOG_INTERVAL, **kwargs):
    """tqdm과 같게 쓰되, 로그로 나갈 때는 줄 단위로 띄엄띄엄 찍는다."""
    if is_terminal():
        return tqdm(iterable, desc=desc, **kwargs)
    return _logged(iterable, desc or "진행", interval)
