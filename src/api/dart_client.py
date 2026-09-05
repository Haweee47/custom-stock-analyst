import io
import os
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import requests
from dotenv import load_dotenv

from src.collectors.progress import track

load_dotenv()

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
BASE_URL = "https://opendart.fss.or.kr/api"
CORP_CODE_PATH = RAW_DIR / "dart_corp_codes.csv"
REQUEST_DELAY = 0.2
# 100개를 한 번에 요청하면 응답이 커져 DART가 JSON 대신 HTML 오류 페이지를 준다
MULTI_BATCH_SIZE = 50

# 보고서 코드: 사업보고서(연간), 반기, 1분기, 3분기
REPORT_CODES = {"사업보고서": "11011", "반기보고서": "11012", "1분기": "11013", "3분기": "11014"}

# DART 응답 status 코드 중 재시도가 무의미한 정상 종료 케이스
NO_DATA_STATUS = "013"


class DartError(RuntimeError):
    """DART API가 정상(000)이 아닌 status를 돌려줬을 때."""


class DartOversizedResponse(RuntimeError):
    """응답이 커서 DART가 JSON 대신 HTML 오류 페이지를 돌려줬을 때."""


def _api_key() -> str:
    key = os.getenv("DART_API_KEY")
    if not key or key.startswith("your_"):
        raise RuntimeError(
            "DART_API_KEY가 설정되지 않았습니다. "
            "https://opendart.fss.or.kr 에서 인증키를 발급받아 .env에 넣어주세요."
        )
    return key


def _get(endpoint: str, **params) -> dict:
    params["crtfc_key"] = _api_key()
    response = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
    response.raise_for_status()

    if not response.headers.get("content-type", "").startswith("application/json"):
        raise DartOversizedResponse(f"{endpoint}: JSON이 아닌 응답 (요청량 초과 추정)")
    payload = response.json()

    status = payload.get("status")
    if status == NO_DATA_STATUS:
        return {"status": status, "list": []}
    if status != "000":
        raise DartError(f"{endpoint} 실패 (status={status}): {payload.get('message')}")
    return payload


def download_corp_codes(force: bool = False) -> pd.DataFrame:
    """DART 고유번호(corp_code) 전체 목록을 받아 CSV로 캐시한다.

    DART API는 종목코드가 아니라 자체 고유번호(corp_code)로 조회하므로,
    종목코드 → corp_code 매핑이 모든 재무 조회의 전제가 된다.
    """
    if CORP_CODE_PATH.exists() and not force:
        return pd.read_csv(CORP_CODE_PATH, dtype=str)

    response = requests.get(
        f"{BASE_URL}/corpCode.xml", params={"crtfc_key": _api_key()}, timeout=60
    )
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml_bytes = archive.read(archive.namelist()[0])

    root = ElementTree.fromstring(xml_bytes)
    records = [
        {
            "corp_code": node.findtext("corp_code", "").strip(),
            "corp_name": node.findtext("corp_name", "").strip(),
            "stock_code": node.findtext("stock_code", "").strip(),
        }
        for node in root.iter("list")
    ]

    df = pd.DataFrame(records)
    # 종목코드가 빈 값이면 비상장사이므로 분석 대상이 아니다
    df = df[df["stock_code"].str.len() == 6].reset_index(drop=True)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CORP_CODE_PATH, index=False, encoding="utf-8-sig")
    return df


def map_stock_to_corp(stock_codes: list[str]) -> dict[str, str]:
    corp_df = download_corp_codes()
    lookup = dict(zip(corp_df["stock_code"], corp_df["corp_code"]))
    return {code: lookup[code] for code in stock_codes if code in lookup}


def get_financials(
    corp_codes: list[str], year: int, report: str = "사업보고서"
) -> pd.DataFrame:
    """여러 회사의 주요 재무계정을 한 번에 조회한다.

    fnlttMultiAcnt는 한 요청에 최대 100개 회사를 처리하므로,
    2,600여 종목도 27회 요청이면 끝난다 (단건 조회 대비 100배 절약).
    """
    reprt_code = REPORT_CODES[report]
    frames = []

    def fetch(batch: list[str]) -> None:
        try:
            payload = _get(
                "fnlttMultiAcnt.json",
                corp_code=",".join(batch),
                bsns_year=str(year),
                reprt_code=reprt_code,
            )
        except DartOversizedResponse:
            # 응답이 크면 절반으로 나눠 다시 시도한다
            if len(batch) == 1:
                return
            mid = len(batch) // 2
            fetch(batch[:mid])
            fetch(batch[mid:])
            return

        if payload["list"]:
            frames.append(pd.DataFrame(payload["list"]))
        time.sleep(REQUEST_DELAY)

    for start in track(
        range(0, len(corp_codes), MULTI_BATCH_SIZE), desc=f"DART 재무 {year} {report}"
    ):
        fetch(corp_codes[start : start + MULTI_BATCH_SIZE])

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def get_disclosures(corp_code: str, bgn_de: str, end_de: str) -> pd.DataFrame:
    """한 회사의 기간별 공시 목록을 조회한다. 날짜는 YYYYMMDD 형식."""
    payload = _get(
        "list.json",
        corp_code=corp_code,
        bgn_de=bgn_de,
        end_de=end_de,
        page_count="100",
    )
    return pd.DataFrame(payload["list"])


if __name__ == "__main__":
    import sys

    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    corp_df = download_corp_codes()
    print(f"DART 고유번호 {len(corp_df)}건 확보: {CORP_CODE_PATH}")
    print(corp_df.head().to_string(index=False))
