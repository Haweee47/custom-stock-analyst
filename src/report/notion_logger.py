"""학습 일지를 Notion 페이지로 기록한다."""
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from notion_client import Client

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# Notion은 rich_text 하나당 2000자를 넘길 수 없다
TEXT_LIMIT = 2000

_CLIENT: Client | None = None


def get_client() -> Client:
    global _CLIENT
    if _CLIENT is None:
        key = os.getenv("NOTION_API_KEY")
        if not key:
            raise RuntimeError("NOTION_API_KEY가 없습니다. .env를 확인하세요.")
        _CLIENT = Client(auth=key)
    return _CLIENT


def _text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": content[:TEXT_LIMIT]}}]


def _heading(content: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _text(content)}}


def _paragraph(content: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _text(content)}}


def _bullet(content: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _text(content)},
    }


def _section(heading: str, body: str | list[str]) -> list[dict]:
    """문자열은 문단으로, 리스트는 불릿으로 렌더링한다."""
    blocks = [_heading(heading)]
    if isinstance(body, str):
        blocks.append(_paragraph(body))
    else:
        blocks.extend(_bullet(item) for item in body)
    return blocks


def create_journal_entry(
    title: str,
    goal: str | list[str],
    code_summary: str | list[str],
    errors: str | list[str],
    learnings: str | list[str],
    next_step: str | list[str] | None = None,
    parent_page_id: str | None = None,
) -> str:
    parent_page_id = parent_page_id or os.getenv("NOTION_PARENT_PAGE_ID")
    if not parent_page_id:
        raise RuntimeError("NOTION_PARENT_PAGE_ID가 없습니다. .env를 확인하세요.")

    children = [
        *_section("🎯 목표", goal),
        *_section("🧩 핵심 코드 요약", code_summary),
        *_section("🐛 에러 해결 내역", errors),
        *_section("💡 배운 점", learnings),
    ]
    if next_step:
        children.extend(_section("🔜 다음 단계", next_step))

    page = get_client().pages.create(
        parent={"page_id": parent_page_id},
        properties={"title": [{"text": {"content": title}}]},
        children=children,
    )
    return page["url"]


def today_title(topic: str) -> str:
    return f"{date.today().isoformat()} · {topic}"


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    print("이 모듈은 create_journal_entry()를 임포트해 사용합니다.")
