"""DART 기업개황의 표준산업분류(KSIC)를 받아 네이버 업종과 대조한다.

신약 개발사 메지온이 네이버 분류로 '식음료·담배 / 식품'이라, 리포트가 삼양식품·
오리온과 부채비율을 비교했다(2026-09-12에 발견). 숫자는 전부 맞아서 숫자 검증기가
잡지 못한다. 업종은 동종업계 비교의 모집단을 정하므로, 틀리면 계산이 맞아도 결론이 틀린다.

두 분류 체계는 기준이 달라 일대일로 맞출 수 없다. 그래서 이름을 맞추는 대신
**같은 네이버 업종 안에서 혼자 다른 산업코드를 쓰는 종목**을 찾는다. 메지온은
식품 업종에 있지만 산업코드가 의학·약학 연구개발업(701)이라 여기에 걸린다.

    python -m src.collectors.industry_collector        수집하고 대조 결과를 보여 준다
    python -m src.collectors.industry_collector --report   이미 받은 것으로 대조만
"""
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

from src.collectors.progress import track

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "processed" / "industry_codes.csv"
OVERRIDES = ROOT / "data" / "processed" / "industry_overrides.csv"
DELAY = 0.05

COLUMNS = ["종목코드", "표준산업분류", "수집일"]
OVERRIDE_COLUMNS = ["종목코드", "종목명", "업종_대분류", "업종_소분류", "근거"]

# 업종 하나에서 이 비율보다 드문 산업코드를 쓰면 분류를 의심한다.
RARE_SHARE = 0.05
# 표본이 적은 업종은 '드물다'는 말이 성립하지 않는다.
MIN_GROUP = 20


def fetch_industry(corp_code: str) -> str | None:
    """기업개황의 표준산업분류 코드. 조회에 실패하면 None."""
    from src.api.dart_client import _get

    try:
        payload = _get("company.json", corp_code=corp_code)
    except Exception:
        return None
    code = str(payload.get("induty_code") or "").strip()
    return code or None


def collect(pairs, fetch=fetch_industry, delay: float = DELAY) -> pd.DataFrame:
    """(종목코드, corp_code) 쌍을 받아 산업코드를 모은다. 실패한 종목은 기록하지 않는다."""
    today = date.today().isoformat()
    rows, failed = [], 0
    for stock_code, corp_code in track(list(pairs), desc="표준산업분류"):
        code = fetch(corp_code)
        if delay:
            time.sleep(delay)
        if code is None:
            failed += 1
            continue
        rows.append({"종목코드": str(stock_code), "표준산업분류": code, "수집일": today})
    if failed:
        print(f"조회 실패 {failed}건은 기록하지 않았습니다.")
    return pd.DataFrame(rows, columns=COLUMNS)


def load() -> pd.DataFrame:
    if not OUT.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(
        OUT, dtype={"종목코드": str, "표준산업분류": str}, encoding="utf-8-sig"
    )


def load_overrides() -> pd.DataFrame:
    if not OVERRIDES.exists():
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)
    return pd.read_csv(OVERRIDES, dtype={"종목코드": str}, encoding="utf-8-sig")


def apply_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """확인된 오분류를 바로잡는다.

    자동 판정만으로 업종을 갈아끼우지 않는다. 상위 25개를 직접 확인해 보니 진짜
    오분류는 3개뿐이었다(2026-09-21). 나머지는 KSIC가 제조 공정을, 네이버가 테마를
    기준으로 삼아 갈린 것이고, 동종업계 재무 비교에는 네이버 쪽이 낫다.
    그래서 사람이 확인한 것만 파일에 적어 두고 여기서 덮어쓴다. 근거도 같이 적는다.
    """
    fixes = load_overrides()
    if fixes.empty or "종목코드" not in df.columns:
        return df

    indexed = fixes.drop_duplicates("종목코드").set_index("종목코드")
    if not df["종목코드"].isin(indexed.index).any():
        return df

    df = df.copy()
    df["업종_원본"] = df["업종_소분류"]
    for column in ("업종_대분류", "업종_소분류"):
        if column in indexed.columns:
            df[column] = df["종목코드"].map(indexed[column]).fillna(df[column])
    return df


def mismatches(universe: pd.DataFrame, industry: pd.DataFrame) -> pd.DataFrame:
    """네이버 업종 안에서 혼자 다른 산업을 하는 종목을 찾는다.

    산업코드는 앞 세 자리로 묶는다(메지온 70113 → 701 의학·약학 연구개발업).
    다섯 자리를 그대로 쓰면 같은 산업도 잘게 쪼개져 전부 '드문' 코드가 된다.
    """
    merged = universe.merge(industry, on="종목코드", how="inner")
    merged = merged.dropna(subset=["업종_소분류", "표준산업분류"])
    if merged.empty:
        return merged

    merged["산업"] = merged["표준산업분류"].str[:3]
    sizes = merged.groupby("업종_소분류")["종목코드"].transform("size")
    counts = merged.groupby(["업종_소분류", "산업"])["종목코드"].transform("size")
    merged["비중"] = counts / sizes

    # 그 산업코드가 주로 어느 업종에 모여 있는지 — '어디로 갔어야 하나'의 단서
    home = (
        merged.groupby(["산업", "업종_소분류"])["종목코드"].size().reset_index(name="수")
        .sort_values("수", ascending=False)
        .drop_duplicates("산업")
        .set_index("산업")["업종_소분류"]
    )
    merged["주로_속한_업종"] = merged["산업"].map(home)

    suspect = merged[(sizes >= MIN_GROUP) & (merged["비중"] < RARE_SHARE)]
    return suspect[
        ["종목코드", "종목명", "업종_소분류", "표준산업분류", "주로_속한_업종", "비중"]
    ].sort_values("비중")


def report() -> int:
    from src.analysis.gemini_analyzer import load_universe
    from src.collectors import markets

    universe = load_universe()
    domestic = universe[universe["국가"] == markets.KOREA]
    industry = load()
    if industry.empty:
        print("산업코드가 없습니다. 먼저 수집하세요: python -m src.collectors.industry_collector")
        return 1

    suspect = mismatches(domestic, industry)
    covered = domestic["종목코드"].isin(industry["종목코드"]).sum()
    print(f"\n대조 대상 {covered:,}종목 · 분류가 의심되는 종목 {len(suspect):,}개")
    if not suspect.empty:
        print("\n가장 동떨어진 20개")
        for _, row in suspect.head(20).iterrows():
            print(
                f"  {row['종목명']:14} {row['종목코드']} · 네이버 '{row['업종_소분류']}' · "
                f"산업코드 {row['표준산업분류']} (보통 '{row['주로_속한_업종']}')"
            )
    return 0


def main() -> int:
    if "--report" in sys.argv:
        return report()

    from src.analysis.gemini_analyzer import load_universe
    from src.api.dart_client import map_stock_to_corp
    from src.collectors import markets

    universe = load_universe()
    codes = universe.loc[universe["국가"] == markets.KOREA, "종목코드"].astype(str).tolist()
    lookup = map_stock_to_corp(codes)
    print(f"국내 {len(codes):,}종목 중 DART 고유번호가 있는 {len(lookup):,}종목을 조회합니다.")

    frame = collect(lookup.items())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT} ({len(frame):,}종목)")
    return report()


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
