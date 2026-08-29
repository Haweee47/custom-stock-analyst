"""종목별 업종(대분류·소분류)을 수집한다.

네이버는 79개 소분류만 제공하고 대분류가 없다. 79개를 그대로 필터에 넣으면
고르기 어려우므로 12개 대분류로 묶어 두 단계로 좁힐 수 있게 한다.
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = ROOT / "data" / "processed"
SECTOR_PATH = PROCESSED_DIR / "sectors.csv"

GROUP_URL = "https://finance.naver.com/sise/sise_group.naver"
DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
REQUEST_DELAY = 0.25

# 네이버 소분류 79개를 12개 대분류로 묶는다. 여기에 없는 업종은 '기타'로 간다.
SECTOR_GROUPS = {
    "IT·반도체": [
        "반도체와반도체장비", "디스플레이장비및부품", "디스플레이패널", "전자장비와기기",
        "전자제품", "컴퓨터와주변기기", "사무용전자제품", "통신장비", "핸드셋",
    ],
    "소프트웨어·인터넷": [
        "소프트웨어", "IT서비스", "게임엔터테인먼트", "양방향미디어와서비스",
        "인터넷과카탈로그소매", "건강관리기술",
    ],
    "바이오·헬스케어": [
        "제약", "생물공학", "생명과학도구및서비스", "건강관리업체및서비스",
        "건강관리장비와용품",
    ],
    "화학·소재": ["화학", "포장재", "종이와목재", "건축자재"],
    "철강·금속": ["철강", "비철금속"],
    "자동차·운송장비": ["자동차", "자동차부품", "조선", "우주항공과국방"],
    "기계·전기장비": ["기계", "전기장비", "전기제품", "에너지장비및서비스"],
    "건설·부동산": ["건설", "건축제품", "부동산"],
    "금융": [
        "은행", "증권", "생명보험", "손해보험", "카드", "기타금융", "창업투자", "복합기업",
    ],
    "유통·소비재": [
        "백화점과일반상점", "전문소매", "판매업체", "무역회사와판매업체",
        "식품과기본식료품소매", "화장품", "섬유,의류,신발,호화품", "가구",
        "가정용기기와용품", "가정용품", "레저용장비와제품", "문구류",
    ],
    "식음료·담배": ["식품", "음료", "담배"],
    "미디어·서비스": [
        "방송과엔터테인먼트", "광고", "출판", "교육서비스", "호텔,레스토랑,레저",
        "다각화된소비자서비스", "상업서비스와공급품",
    ],
    "운송·물류": [
        "항공사", "해운사", "도로와철도운송", "항공화물운송과물류", "운송인프라",
    ],
    "에너지·유틸리티": [
        "석유와가스", "전기유틸리티", "가스유틸리티", "복합유틸리티",
    ],
    "통신": ["무선통신서비스", "다각화된통신서비스"],
}

SUB_TO_GROUP = {sub: group for group, subs in SECTOR_GROUPS.items() for sub in subs}


def _soup(url: str, params: dict) -> BeautifulSoup:
    response = requests.get(url, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    response.encoding = "euc-kr"
    return BeautifulSoup(response.text, "lxml")


def fetch_sector_list() -> list[tuple[str, str]]:
    soup = _soup(GROUP_URL, {"type": "upjong"})
    out = []
    for anchor in soup.select("table.type_1 a"):
        href = anchor.get("href", "")
        if "no=" in href:
            out.append((anchor.get_text(strip=True), href.split("no=")[-1]))
    return out


def fetch_sector_members(sector_no: str) -> list[str]:
    soup = _soup(DETAIL_URL, {"type": "upjong", "no": sector_no})
    codes = []
    for anchor in soup.select("div.name_area a"):
        href = anchor.get("href", "")
        if "code=" in href:
            codes.append(href.split("code=")[-1])
    return codes


def collect() -> pd.DataFrame:
    records = []
    for name, number in tqdm(fetch_sector_list(), desc="업종 수집"):
        for code in fetch_sector_members(number):
            records.append(
                {
                    "종목코드": code,
                    "업종_소분류": name,
                    "업종_대분류": SUB_TO_GROUP.get(name, "기타"),
                }
            )
        time.sleep(REQUEST_DELAY)

    df = pd.DataFrame(records)
    # 한 종목이 여러 업종에 걸리는 경우가 있어 첫 번째만 남긴다
    return df.drop_duplicates(subset="종목코드", keep="first").reset_index(drop=True)


def save(df: pd.DataFrame) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(SECTOR_PATH, index=False, encoding="utf-8-sig")
    return SECTOR_PATH


def load() -> pd.DataFrame:
    if not SECTOR_PATH.exists():
        return pd.DataFrame(columns=["종목코드", "업종_소분류", "업종_대분류"])
    return pd.read_csv(SECTOR_PATH, dtype={"종목코드": str})


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    result = collect()
    path = save(result)
    print(f"{len(result)}개 종목 업종 저장: {path}")
    print(result["업종_대분류"].value_counts().to_string())
