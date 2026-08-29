import os
import sys

from dotenv import load_dotenv
from notion_client import Client

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID")


def get_client() -> Client:
    return Client(auth=NOTION_API_KEY)


def create_journal_entry(title: str, goal: str, code_summary: str, errors: str, learnings: str) -> str:
    client = get_client()
    page = client.pages.create(
        parent={"page_id": NOTION_PARENT_PAGE_ID},
        properties={"title": [{"text": {"content": title}}]},
        children=[
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🎯 목표"}}]}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": goal}}]}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🧩 핵심 코드 요약"}}]}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": code_summary}}]}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🐛 에러 해결 내역"}}]}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": errors}}]}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "💡 배운 점"}}]}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": learnings}}]}},
        ],
    )
    return page["url"]


if __name__ == "__main__":
    url = create_journal_entry(
        title="연결 테스트",
        goal="Notion API 연동 확인",
        code_summary="notion_logger.py 작성",
        errors="없음",
        learnings="Integration을 페이지에 공유해야 API로 하위 페이지를 생성할 수 있음",
    )
    print(f"생성된 페이지: {url}")
