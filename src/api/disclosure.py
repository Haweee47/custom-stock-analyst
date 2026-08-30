"""공시 목록을 중요도 순으로 추린다.

DART가 돌려주는 공시는 대부분 '임원·주요주주 소유상황보고서'처럼 정기적으로
쌓이는 잡음이다. 주가와 실적에 직접 연결되는 것만 골라야 리포트에 쓸모가 있다.
"""
from datetime import date, timedelta

import pandas as pd

from src.api.dart_client import get_disclosures, map_stock_to_corp

# 위 단계일수록 중요하다. 앞에서부터 검사해 처음 걸리는 등급을 매긴다.
PRIORITY_TIERS = [
    (
        5,
        [
            "영업(잠정)실적", "매출액또는손익구조", "단일판매ㆍ공급계약", "단일판매·공급계약",
            "유상증자결정", "무상증자결정", "전환사채", "신주인수권부사채", "교환사채",
            "합병", "분할", "영업양수", "영업양도", "주식교환",
        ],
    ),
    (
        4,
        [
            "주요사항보고서", "자기주식", "현금ㆍ현물배당", "현금·현물배당", "신규시설투자",
            "타법인주식및출자증권", "유형자산", "특허", "소송",
        ],
    ),
    (3, ["사업보고서", "분기보고서", "반기보고서", "감사보고서", "연결재무제표"]),
    (2, ["기타경영사항", "수시공시의무관련사항", "공정공시", "투자판단"]),
]

# 정기적으로 쌓이기만 하고 해석할 거리가 없는 공시
NOISE = [
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "임원·주요주주특정증권등소유상황보고서",
    "주식등의대량보유상황보고서",
    "최대주주등소유주식변동신고서",
]


def _score(report_name: str) -> int:
    if any(noise in report_name for noise in NOISE):
        return 0
    for score, keywords in PRIORITY_TIERS:
        if any(keyword in report_name for keyword in keywords):
            return score
    return 1


def fetch_important(stock_code: str, months: int = 6, limit: int = 6) -> list[dict]:
    """최근 공시 중 중요한 것부터 고른다.

    중요도를 먼저 보고 같은 등급 안에서 최신순으로 정렬한다.
    최근 것만 뽑으면 소유상황보고서만 나오고, 중요도만 보면 오래된 게 섞인다.
    """
    mapping = map_stock_to_corp([stock_code])
    if stock_code not in mapping:
        return []

    end = date.today()
    begin = end - timedelta(days=months * 31)
    raw = get_disclosures(
        mapping[stock_code], begin.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    )
    if raw.empty:
        return []

    raw = raw.copy()
    raw["중요도"] = raw["report_nm"].map(_score)
    raw = raw[raw["중요도"] > 0]
    if raw.empty:
        return []

    raw = raw.sort_values(["중요도", "rcept_dt"], ascending=[False, False])
    return [
        {
            "일자": pd.to_datetime(row["rcept_dt"], format="%Y%m%d").strftime("%Y-%m-%d"),
            "제목": row["report_nm"].strip(),
            "중요도": int(row["중요도"]),
        }
        for _, row in raw.head(limit).iterrows()
    ]
