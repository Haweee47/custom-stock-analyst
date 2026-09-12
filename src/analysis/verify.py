"""리포트에 적힌 숫자가 원본 데이터와 맞는지 대조한다.

금융 리포트에서 가장 위험한 건 문장이 어색한 게 아니라 숫자가 틀리는 것이다.
이 프로젝트에서 실제로 네 번 겪었다.

  1) 매출 333조를 '3,336조'로 (억/조 오독, 10배)
  2) '2023년 대비 6.4% 증가' (6.4%는 전년 대비 값)
  3) '3년 연속 감소' (실제로는 968 → 977 → 948로 중간에 늘었다)
  4) 영업이익 증감률 자리에 당기순이익 값(-46.8%)

넷 다 화면에는 멀쩡해 보였고 사람이 원본과 대조해야만 드러났다. 프롬프트 규칙으로
줄일 수는 있어도 없앨 수는 없으므로, 생성된 뒤에 기계로 한 번 더 검산한다.

방식은 단순하다. 리포트에 등장하는 금액과 비율을 모두 뽑고, 원본에서 나올 수 있는
값들의 목록과 대조한다. 목록에 없는 숫자는 '출처 미확인'으로 표시한다.
확실하게 틀렸다고 단정하기보다, 사람이 봐야 할 곳을 좁혀 주는 것이 목적이다.
"""
import re

import pandas as pd

# 금액이 맞다고 볼 오차. 조·억으로 끊어 쓰면서 반올림이 생긴다.
AMOUNT_TOLERANCE = 0.015
# 비율이 맞다고 볼 오차(퍼센트포인트). 소수 첫째 자리 반올림을 흡수한다.
PERCENT_TOLERANCE = 0.15

MONEY_FIELDS = [
    "매출액",
    "영업이익",
    "당기순이익",
    "EBITDA",
    "자산총계",
    "부채총계",
    "자본총계",
    "시가총액",
]
SUFFIXES = ["", "_전기", "_전전기"]

RATIO_FIELDS = [
    "부채비율",
    "영업이익률",
    "ROE_계산",
    "ROA",
    "PER",
    "PBR",
    "배당수익률",
    "등락률",
    # 프롬프트의 기본 정보 블록에 들어가는 값이다. 재무가 없는 종목(인프라 펀드 등)은
    # 리포트가 이것을 근거로 삼는데, 출처 목록에 없어서 미확인으로 잡혔다.
    "외국인비율",
]

# '333조 6,059억원' / '2,159억달러' / '약 333조원' / '950억원' / '-1조 7,224억원'
# 적자 종목은 금액에 마이너스가 붙는다. 부호를 버리고 읽으면 영업손실을 적은
# 문장이 전부 미확인으로 잡힌다. 앞이 숫자면 연도 범위('2023-2025')이므로 뺀다.
AMOUNT_PATTERN = re.compile(
    r"(?P<부호>(?<![\d.])-)?\s*"
    r"(?:(?P<조>\d[\d,]*(?:\.\d+)?)\s*조)?\s*"
    r"(?:(?P<억>\d[\d,]*(?:\.\d+)?)\s*억)?\s*"
    r"(?P<단위>원|달러|엔|위안|홍콩달러)?"
)
# '8%대'처럼 범위를 말하는 표기도 함께 잡는다. '4.22%대비'의 '대'는 범위가 아니다.
PERCENT_PATTERN = re.compile(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*%(대(?!비))?")


def _to_number(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def report_text(report: dict) -> str:
    """리포트의 사람이 읽는 부분만 모은다."""
    parts = [report.get("헤드라인", "")]
    parts += list(report.get("핵심포인트") or [])
    parts += [f"{s.get('소제목', '')} {s.get('본문', '')}" for s in report.get("섹션") or []]
    parts += list(report.get("체크포인트") or [])
    parts += list(report.get("리스크요인") or [])
    parts.append(report.get("데이터한계", ""))
    for issue in report.get("주요이슈") or []:
        parts.append(f"{issue.get('제목', '')} {issue.get('인사이트', '')}")
    return "\n".join(p for p in parts if p)


def find_amounts(text: str) -> list[tuple[str, float]]:
    """'333조 6,059억원' 같은 표기를 (원문, 값)으로 뽑는다."""
    found = []
    for match in AMOUNT_PATTERN.finditer(text):
        trillion = _to_number(match.group("조"))
        billion = _to_number(match.group("억"))
        if trillion is None and billion is None:
            continue
        value = (trillion or 0) * 1e12 + (billion or 0) * 1e8
        if match.group("부호"):
            value = -value
        found.append((match.group(0).strip(), value))
    return found


def find_percents(text: str) -> list[tuple[str, float]]:
    return [
        (m.group(0).strip(), _to_number(m.group(1)))
        for m in PERCENT_PATTERN.finditer(text)
        if _to_number(m.group(1)) is not None
    ]


def amount_step(literal: str) -> float:
    """그 표기가 감출 수 있는 반올림 폭. '7억원'은 6.5억~7.5억 중 무엇이든 될 수 있다.

    money()가 억 단위에서 반올림하므로(`{billion:,.0f}억`), 금액이 작을수록
    반올림 폭이 상대 오차보다 커진다. 748,000,000원을 '7억원'으로 적은 것은
    표기 규칙을 그대로 따른 것인데, 상대 오차 1.5%로만 재면 미확인으로 잡혔다.
    표기에 남은 자릿수를 보고 그 표기가 허용하는 폭만큼만 넓혀 준다.
    """
    match = AMOUNT_PATTERN.search(literal)
    if not match:
        return 0.0
    # 억이 적혀 있으면 그것이 가장 작은 자리다. 없으면 조가 가장 작은 자리다.
    for group, scale in [("억", 1e8), ("조", 1e12)]:
        raw = match.group(group)
        if raw:
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            return scale / (10**decimals) / 2
    return 0.0


def percent_band(literal: str) -> tuple[float, float] | None:
    """'8%대'가 가리키는 범위. 범위 표기가 아니면 None.

    '영업이익률이 다시 8%대로 회복될지'는 전년 8.50%를 가리키는 맞는 문장인데,
    8.0으로 읽어 0.15%p 안에서만 찾으니 미확인으로 잡혔다(미쓰이상선).
    한국어에서 8%대는 8~9%, 10%대는 10~19%, 100%대는 100~199%다.
    끝자리 0의 개수가 폭을 정한다.
    """
    if not literal.endswith("대"):
        return None
    raw = literal[:-1].rstrip().rstrip("%").strip().lstrip("+-").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    if "." in raw:
        width = 10 ** -len(raw.split(".")[1])
    else:
        digits = str(int(value))
        width = 10 ** (len(digits) - len(digits.rstrip("0"))) if int(value) else 1
    return value, value + width


def _growth(current, previous) -> float | None:
    if current is None or previous is None or pd.isna(current) or pd.isna(previous):
        return None
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def source_amounts(row: pd.Series) -> dict[str, float]:
    """리포트에 나올 수 있는 금액들."""
    values = {}
    for name in MONEY_FIELDS:
        for suffix in SUFFIXES:
            key = f"{name}{suffix}"
            value = row.get(key)
            if value is not None and not pd.isna(value):
                values[key] = float(value)
                # 한국어는 '영업손실 1조 7,224억원'처럼 부호를 말로 옮겨 적기도 한다.
                # 비율에 이미 같은 규칙을 뒀는데 금액에는 빠져 있었다.
                values[f"{key}_절대값"] = abs(float(value))

    # 이익 변화를 매출 몫과 마진 몫으로 나눈 금액도 프롬프트에 들어간다
    from src.analysis import trend

    for label, suffixes in [("최근", ("", "_전기")), ("직전", ("_전기", "_전전기"))]:
        linked = trend.compare(row, *suffixes)
        if not linked:
            continue
        for key in ("매출효과", "마진효과", "실제변화"):
            value = linked.get(key)
            if value is not None:
                values[f"연동_{label}_{key}"] = float(value)
                values[f"연동_{label}_{key}_절대값"] = abs(float(value))
    return values


def source_percents(row: pd.Series, peers: dict | None = None, tech: dict | None = None) -> dict[str, float]:
    """리포트에 나올 수 있는 비율들. 증감률은 계산해서 함께 넣는다."""
    values = {}
    for name in RATIO_FIELDS:
        value = row.get(name)
        if value is not None and not pd.isna(value):
            values[name] = float(value)

    # 3개년 증감률: 전년 대비와 2년 전 대비 모두 정당한 인용이다.
    #
    # 부호는 양쪽 다 넣는다. 한국어 리포트는 '21.5% 감소'처럼 방향을 말로 쓰고
    # 숫자에는 마이너스를 붙이지 않는다. 계산값 -21.46과 본문의 21.5를 그대로
    # 비교하면 맞는 문장이 전부 틀린 것으로 잡힌다.
    for name in ["매출액", "영업이익", "당기순이익", "EBITDA"]:
        current, previous, before = (row.get(f"{name}{s}") for s in SUFFIXES)
        for label, rate in [
            (f"{name}_전년비", _growth(current, previous)),
            (f"{name}_2년비", _growth(current, before)),
            (f"{name}_전기_전년비", _growth(previous, before)),
        ]:
            if rate is not None:
                values[label] = rate
                values[f"{label}_절대값"] = abs(rate)

    # 매출·이익 연동 분석에서 나온 값들. 계산해서 프롬프트에 넣었으므로
    # 리포트가 인용하는 것은 정당하다.
    from src.analysis import trend

    for label, suffixes in [("최근", ("", "_전기")), ("직전", ("_전기", "_전전기"))]:
        linked = trend.compare(row, *suffixes)
        if not linked:
            continue
        for key in ("영업이익률_전", "영업이익률_당", "영업이익률_변화", "레버리지"):
            value = linked.get(key)
            if value is not None:
                values[f"연동_{label}_{key}"] = float(value)
                values[f"연동_{label}_{key}_절대값"] = abs(float(value))

    # 마진이 왜 움직였는지도 계산해서 프롬프트에 넣는다. '원가율 100.66% → 93.62%'는
    # 모델이 지어낸 게 아니라 우리가 준 값이다. 여기에 넣지 않으면 프롬프트가 시킨 대로
    # 쓴 문장이 통째로 미확인으로 잡힌다(국내 리포트 통과율이 이것 때문에 눌렸다).
    for label, suffixes in [("최근", ("", "_전기")), ("직전", ("_전기", "_전전기"))]:
        for name, data in (trend.cost_split(row, *suffixes) or {}).items():
            for key in ("전", "당", "변화"):
                value = data.get(key)
                if value is None:
                    continue
                values[f"원가_{label}_{name}_{key}"] = float(value)
                values[f"원가_{label}_{name}_{key}_절대값"] = abs(float(value))

    if peers:
        for name, data in (peers.get("지표") or {}).items():
            if data.get("중앙값") is not None:
                values[f"업종중앙값_{name}"] = float(data["중앙값"])
            if data.get("백분위") is not None:
                values[f"업종백분위_{name}"] = float(data["백분위"])
                values[f"업종상위_{name}"] = 100 - float(data["백분위"])
            # 프롬프트가 '업종 대비 어디쯤인지' 쓰라고 시키므로 '중앙값보다 14.50%p
            # 낮다'가 나온다. 두 값 다 출처에 있으니 그 차이도 인용으로 본다.
            if data.get("값") is not None and data.get("중앙값") is not None:
                gap = float(data["값"]) - float(data["중앙값"])
                values[f"업종차이_{name}"] = gap
                values[f"업종차이_{name}_절대값"] = abs(gap)

    if tech:
        # 지표도 부호를 양쪽 다 넣는다. '60일선_대비: -7.7%'를 본문은
        # '60일선 대비 7.7% 낮은'이라고 쓴다. 방향을 말로 옮긴 것이지 틀린 게 아니다.
        for key, value in tech.items():
            number = _to_number(str(value).rstrip("%").lstrip("+")) if value is not None else None
            if number is not None:
                values[f"지표_{key}"] = number
                values[f"지표_{key}_절대값"] = abs(number)

    return values


def _closest(value: float, candidates: dict[str, float], relative: float | None, absolute: float | None):
    """가장 가까운 출처를 찾는다. 허용 오차 안이면 (이름, 차이)를 준다."""
    best = None
    for name, candidate in candidates.items():
        gap = abs(value - candidate)
        # 둘 다 주면 넉넉한 쪽을 쓴다. 큰 금액은 상대 오차가, 작은 금액은
        # 표기 반올림 폭이 실제로 필요한 여유다.
        limit = absolute or 0.0
        if relative is not None:
            limit = max(limit, relative * max(abs(candidate), 1e-9))
        if gap <= limit and (best is None or gap < best[1]):
            best = (name, gap)
    return best


def quoted_numbers(sources: list[dict] | None) -> tuple[dict[str, float], dict[str, float]]:
    """뉴스·공시 제목에 실린 숫자를 출처 목록에 더한다.

    '자기주식 1.7조원 취득 결정' 같은 제목을 모델에게 줬으면, 본문에 1.7조원이
    나오는 것은 지어낸 게 아니라 인용이다. 이걸 빼면 이슈·트렌드 관점이
    통째로 '출처 미확인'으로 잡힌다.
    """
    amounts, percents = {}, {}
    for index, item in enumerate(sources or []):
        title = str(item.get("제목", ""))
        for literal, value in find_amounts(title):
            amounts[f"인용_{index}_{literal}"] = value
        for literal, value in find_percents(title):
            percents[f"인용_{index}_{literal}"] = value
    return amounts, percents


def verify(
    report: dict,
    row: pd.Series,
    peers: dict | None = None,
    tech: dict | None = None,
    news: list[dict] | None = None,
    disclosures: list[dict] | None = None,
    overview: str | None = None,
) -> dict:
    """리포트의 숫자를 원본과 대조한 결과를 돌려준다.

    돌려주는 것:
      확인   - 원본에서 출처를 찾은 숫자 수
      미확인 - 출처를 못 찾은 숫자 (사람이 봐야 할 곳)
      통과   - 미확인이 없으면 True
    """
    text = report_text(report)
    amounts = source_amounts(row)
    percents = source_percents(row, peers, tech)

    for source in (news, disclosures):
        quoted_amounts, quoted_percents = quoted_numbers(source)
        amounts.update(quoted_amounts)
        percents.update(quoted_percents)

    # 리포트가 옮겨 적은 이슈 제목의 숫자도 인용으로 본다
    quoted_amounts, quoted_percents = quoted_numbers(report.get("주요이슈"))
    amounts.update(quoted_amounts)
    percents.update(quoted_percents)

    # 회사 개요도 우리가 프롬프트에 넣어 준 문장이다. '에너지솔루션이 매출의 94%'는
    # 개요에 적혀 있던 값이지 모델이 만든 값이 아니다.
    if overview:
        over_amounts, over_percents = quoted_numbers([{"제목": overview}])
        amounts.update({f"개요_{k}": v for k, v in over_amounts.items()})
        percents.update({f"개요_{k}": v for k, v in over_percents.items()})

    checked, unmatched = 0, []

    for literal, value in find_amounts(text):
        if value == 0:
            continue
        if _closest(value, amounts, relative=AMOUNT_TOLERANCE, absolute=amount_step(literal)):
            checked += 1
        else:
            unmatched.append({"종류": "금액", "표기": literal, "값": value})

    for literal, value in find_percents(text):
        band = percent_band(literal)
        if band:
            low, high = band
            found = any(low <= candidate < high for candidate in percents.values())
        else:
            found = _closest(value, percents, relative=None, absolute=PERCENT_TOLERANCE)
        if found:
            checked += 1
        else:
            unmatched.append({"종류": "비율", "표기": literal, "값": value})

    total = checked + len(unmatched)
    return {
        "확인": checked,
        "전체": total,
        "미확인": unmatched,
        "통과": not unmatched,
        "대조율": round(checked / total * 100, 1) if total else 100.0,
    }
