"""DART 재무 데이터를 종목별로 모아 분석용 테이블로 정리한다."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.api.dart_client import get_financials, map_stock_to_corp

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

# 연결재무제표(CFS)를 우선 쓰고, 없는 회사만 개별재무제표(OFS)로 채운다
FS_PRIORITY = {"CFS": 0, "OFS": 1}
# 같은 계정이 손익계산서(IS)와 포괄손익계산서(CIS)에 모두 실리므로 IS를 우선한다
SJ_PRIORITY = {"BS": 0, "IS": 0, "CIS": 1}
# DART는 회사마다 계정명 표기가 조금씩 다르므로 대표 이름으로 통일한다
ACCOUNT_ALIASES = {
    "당기순이익(손실)": "당기순이익",
    "영업이익(손실)": "영업이익",
    "매출액(수익)": "매출액",
}
KEY_ACCOUNTS = [
    "자산총계",
    "부채총계",
    "자본총계",
    "매출액",
    "영업이익",
    "당기순이익",
]


def latest_snapshot() -> Path:
    files = sorted(RAW_DIR.glob("stock_snapshot_*.csv"))
    if not files:
        raise FileNotFoundError(
            "종목 스냅샷이 없습니다. 먼저 src/collectors/stock_collector.py를 실행하세요."
        )
    return files[-1]


def load_target_stocks() -> pd.DataFrame:
    """ETF·ETN·우선주를 제외한 보통주만 분석 대상으로 삼는다."""
    df = pd.read_csv(latest_snapshot(), dtype={"종목코드": str})
    return df[df["종목구분"] == "보통주"].reset_index(drop=True)


def _pick_amount(group: pd.DataFrame) -> pd.Series:
    return group.sort_values("_fs_rank").iloc[0]


def tidy_financials(raw: pd.DataFrame) -> pd.DataFrame:
    """DART 롱포맷 응답을 종목코드 1행 × 계정 1열의 넓은 표로 바꾼다."""
    df = raw.copy()
    df["account_nm"] = df["account_nm"].replace(ACCOUNT_ALIASES)
    df = df[df["account_nm"].isin(KEY_ACCOUNTS)].copy()
    df["_fs_rank"] = df["fs_div"].map(FS_PRIORITY).fillna(9)
    df["_sj_rank"] = df["sj_div"].map(SJ_PRIORITY).fillna(9)
    # 당기만 쓰면 추이를 볼 수 없다. DART가 함께 주는 전기·전전기도 살린다.
    for src, label in [
        ("thstrm_amount", "당기"),
        ("frmtrm_amount", "전기"),
        ("bfefrmtrm_amount", "전전기"),
    ]:
        df[label] = pd.to_numeric(
            df[src].astype(str).str.replace(",", "", regex=False), errors="coerce"
        )

    # 같은 계정이 CFS/OFS로 중복 제공되므로 우선순위가 높은 쪽만 남긴다
    picked = (
        df.sort_values(["_fs_rank", "_sj_rank"])
        .groupby(["stock_code", "account_nm"], as_index=False)
        .first()
    )
    frames = []
    for label in ["당기", "전기", "전전기"]:
        part = picked.pivot(index="stock_code", columns="account_nm", values=label)
        suffix = "" if label == "당기" else f"_{label}"
        part.columns = [f"{c}{suffix}" for c in part.columns]
        frames.append(part)

    wide = pd.concat(frames, axis=1)
    wide.index.name = "종목코드"
    return wide.reset_index()


def add_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """재무비율은 원본 값만으로는 비교가 어려우므로 파생 지표를 계산해 둔다."""
    if "부채총계" in df and "자본총계" in df:
        df["부채비율"] = (df["부채총계"] / df["자본총계"] * 100).round(2)
    if "영업이익" in df and "매출액" in df:
        df["영업이익률"] = (df["영업이익"] / df["매출액"] * 100).round(2)
    if "당기순이익" in df and "자본총계" in df:
        df["ROE_계산"] = (df["당기순이익"] / df["자본총계"] * 100).round(2)
    return df


def collect(year: int, report: str = "사업보고서") -> pd.DataFrame:
    stocks = load_target_stocks()
    mapping = map_stock_to_corp(stocks["종목코드"].tolist())
    print(f"분석 대상 보통주 {len(stocks)}개 중 DART 매칭 {len(mapping)}개")

    raw = get_financials(list(mapping.values()), year, report)
    if raw.empty:
        print(f"{year}년 {report} 데이터가 없습니다.")
        return pd.DataFrame()

    wide = add_derived_metrics(tidy_financials(raw))
    merged = stocks.merge(wide, on="종목코드", how="left")
    merged["기준연도"] = year
    merged["보고서"] = report
    return merged


def save(df: pd.DataFrame, year: int) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / f"financials_{year}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out


# 네이버 스냅샷에서 오는 값들. 나머지 열은 DART 재무라 분기마다만 바뀐다.
SNAPSHOT_COLUMNS = [
    "종목명",
    "시장구분",
    "종목구분",
    "현재가",
    "등락률",
    "시가총액",
    "상장주식수",
    "거래량",
    "외국인비율",
    "PER",
    "ROE",
]


def refresh_prices(year: int) -> int:
    """시세만 최신 스냅샷으로 덮어쓴다.

    주가는 매일 바뀌지만 재무는 분기마다 바뀐다. 그런데 화면이 읽는
    financials_<year>.csv에는 둘이 함께 들어 있어서, 지금까지는 재무를 다시
    받아야만(=DART 2,655회 조회) 주가가 갱신됐다. 매일 돌릴 수 없는 무게였다.

    여기서는 DART를 건드리지 않고 스냅샷의 시세 열만 갈아 끼운다.
    새로 상장된 종목은 들어오지 않으므로, 종목 목록 자체는 전체 갱신 때 맞춘다.
    """
    path = PROCESSED_DIR / f"financials_{year}.csv"
    if not path.exists():
        return 0

    financials = pd.read_csv(path, dtype={"종목코드": str})
    snapshot = pd.read_csv(latest_snapshot(), dtype={"종목코드": str})

    columns = [c for c in SNAPSHOT_COLUMNS if c in snapshot.columns and c in financials.columns]
    if not columns:
        return 0

    order = list(financials.columns)
    fresh = snapshot[["종목코드", *columns]]
    updated = financials.drop(columns=columns).merge(fresh, on="종목코드", how="left")

    # 스냅샷에서 사라진 종목(상장폐지 등)은 갱신할 값이 없다. 그대로 두면 종목명까지
    # 지워져 화면에 'nan'이 뜨므로, 새 값이 없는 칸만 이전 값으로 되돌린다.
    for column in columns:
        updated[column] = updated[column].fillna(financials[column])

    save(updated[order], year)
    return int(updated["현재가"].notna().sum()) if "현재가" in updated else len(updated)


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    result = collect(year)
    if not result.empty:
        path = save(result, year)
        filled = result["매출액"].notna().sum()
        print(f"{len(result)}개 종목 저장 완료 (재무 확보 {filled}개): {path}")
