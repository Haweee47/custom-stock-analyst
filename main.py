"""프로젝트 진입점 안내.

실제 기능은 아래 두 곳에 있다.

    streamlit run app.py       웹앱 실행
    python update_all.py       데이터 갱신 배치
"""
import sys


def main() -> int:
    print(__doc__.strip())
    print("\n개별 배치를 따로 돌리려면:")
    for command, note in [
        ("python src/collectors/stock_collector.py", "시세·시가총액"),
        ("python src/collectors/financial_collector.py", "DART 재무"),
        ("python src/collectors/sector_collector.py", "업종 분류"),
        ("python src/collectors/disclosure_batch.py", "공시 등급"),
    ]:
        print(f"    {command:48} {note}")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
