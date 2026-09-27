"""저장된 리포트를 정적 웹페이지로 만든다.

왜 정적인가:
  1) 지금 배포처(Streamlit Community Cloud)는 약관상 상업적 이용이 금지돼 있다.
     광고를 붙이려면 옮겨야 한다.
  2) 광고 수익은 검색 유입에서 나오는데, Streamlit은 주소가 하나뿐이라 검색엔진이
     색인할 것이 없다. '포스코엠텍 실적'을 검색한 사람이 닿을 길이 없다.
     리포트마다 독립된 주소를 주면 그 수만큼 유입 경로가 생긴다.
  3) 정적 파일은 서버가 없어 잠들지도, 모듈이 옛것으로 남지도 않는다.

읽기만 한다. 리포트를 새로 만들지 않으므로 Gemini 호출이 없고 비용도 0이다.

    python site_build.py              site/ 에 생성
    python site_build.py --limit 20   앞의 20건만 (빠른 확인용)
"""
import argparse
import html
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.analysis.gemini_analyzer import CACHE_DIR, MARKET_CODES  # noqa: E402
from src.collectors import markets  # noqa: E402
from src.report.report_view import (  # noqa: E402
    body_html,
    footer_html,
    header_html,
    issues_html,
    metrics_html,
    styles_html,
    verification_html,
    yearly_table_html,
)

OUT = ROOT / "site"
SITE_NAME = "리포트 셀프바"
TAGLINE = "애널리스트가 다루지 않는 종목까지, 오늘 데이터로 만드는 AI 기업 리포트"
# 배포 주소가 정해지면 여기만 바꾸면 sitemap·canonical이 함께 따라간다.
BASE_URL = "https://report-selfbar.pages.dev"

MARKET_SLUGS = {"KR": "kr", "US": "us", "JP": "jp", "CN": "cn"}
MARKET_NAMES = {code: name for name, code in MARKET_CODES.items()}

# 화면 전체를 감싸는 껍데기. 검색엔진이 읽는 것은 대부분 여기 들어간다.
PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="{site}">
{structured}
<style>{css}</style>
</head>
<body>
<header class="site-top">
  <a class="site-logo" href="{root}/">{site}</a>
  <nav class="site-nav">{nav}</nav>
</header>
<main class="site-main">
{main}
</main>
<footer class="site-foot">
  <p class="site-disclaimer">{disclaimer}</p>
  <p><a href="{root}/about.html">소개</a> · <a href="{root}/privacy.html">개인정보처리방침</a>
     · <a href="https://github.com/Haweee47/custom-stock-analyst">코드</a></p>
  <p class="site-small">{updated} 기준 · 리포트 {count:,}건</p>
</footer>
</body>
</html>"""

SITE_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin:0; background:#f6f7f9; color:#1b1f27;
  font-family:'Pretendard','Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif; }
a { color:#1a4fd6; text-decoration:none; }
a:hover { text-decoration:underline; }
.site-top { display:flex; align-items:center; justify-content:space-between; gap:16px;
  padding:14px 20px; background:#0f1b2d; color:#fff; }
.site-logo { color:#fff; font-weight:700; font-size:18px; }
.site-nav a { color:#9fb3d1; margin-left:14px; font-size:14px; }
.site-main { max-width:980px; margin:0 auto; padding:24px 16px 48px; }
.site-foot { max-width:980px; margin:0 auto; padding:24px 16px 56px; color:#5f6672; font-size:13px; }
.site-disclaimer { background:#fff; border:1px solid #e5e8ec; border-radius:8px; padding:12px 14px; }
.site-small { color:#8a919c; }
.hero { background:#fff; border:1px solid #e5e8ec; border-radius:12px; padding:28px 24px; margin-bottom:20px; }
.hero h1 { margin:0 0 8px; font-size:26px; }
.hero p { margin:6px 0; color:#4a5261; }
.hero .stat { display:inline-block; margin-right:18px; font-weight:700; color:#0f1b2d; }
.card-list { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:12px; }
.card { background:#fff; border:1px solid #e5e8ec; border-radius:10px; padding:14px 16px; }
.card b { display:block; font-size:16px; margin-bottom:4px; }
.card small { color:#6b7280; }
.card p { margin:8px 0 0; font-size:14px; color:#3d4452; line-height:1.5; }
.market-tabs { margin:18px 0 10px; }
.market-tabs a { display:inline-block; padding:6px 12px; margin-right:6px; border-radius:999px;
  background:#fff; border:1px solid #e5e8ec; font-size:14px; }
.crumb { font-size:13px; color:#6b7280; margin-bottom:12px; }
.search { width:100%; padding:12px 14px; font-size:15px; border:1px solid #d7dbe0; border-radius:8px; }
.doc { background:#fff; border:1px solid #e5e8ec; border-radius:12px; padding:24px; line-height:1.7; }
.doc h2 { font-size:18px; margin-top:24px; }
"""


def esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


def page(title, description, canonical, main, *, count, updated, root="", og_type="website", structured=""):
    return PAGE.format(
        title=esc(title),
        description=esc(description)[:300],
        canonical=canonical,
        og_type=og_type,
        structured=structured,
        site=SITE_NAME,
        css=SITE_CSS + styles_html().replace("<style>", "").replace("</style>", ""),
        nav='<a href="{r}/kr/">국내</a><a href="{r}/us/">미국</a>'
            '<a href="{r}/jp/">일본</a><a href="{r}/cn/">중국</a>'.format(r=root),
        main=main,
        root=root,
        disclaimer="이 리포트는 AI가 공개 데이터로 생성한 정보이며 투자 권유가 아닙니다. "
                   "투자의견과 목표주가는 제공하지 않습니다. "
                   "투자 판단과 그 결과에 대한 책임은 이용자 본인에게 있습니다.",
        updated=updated,
        count=count,
    )


def load_reports(limit: int | None = None) -> list[dict]:
    """캐시된 리포트를 읽는다. 파일 이름에서 시장·종목·관점·분량을 얻는다."""
    reports = []
    for path in sorted(CACHE_DIR.glob("*.json")):
        parts = path.stem.split("_")
        if len(parts) != 4 or parts[0] not in MARKET_SLUGS:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        data["_시장코드"], data["_종목코드"] = parts[0], parts[1]
        reports.append(data)
        if limit and len(reports) >= limit:
            break
    return reports


def report_structured(row: pd.Series, result: dict, url: str) -> str:
    """검색 결과에 제목·날짜가 제대로 뜨도록 구조화 데이터를 넣는다."""
    payload = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": f"{row['종목명']}({row['종목코드']}) {result['리포트']['헤드라인']}"[:110],
        "datePublished": result["생성시각"],
        "dateModified": result["생성시각"],
        "author": {"@type": "Organization", "name": SITE_NAME},
        "publisher": {"@type": "Organization", "name": SITE_NAME},
        "mainEntityOfPage": url,
        "inLanguage": "ko",
    }
    return f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'


def report_page(row: pd.Series, result: dict, root: str, url: str, count: int, updated: str) -> str:
    report = result["리포트"]
    body = "".join(
        [
            f'<p class="crumb"><a href="{root}/">홈</a> › '
            f'<a href="{root}/{MARKET_SLUGS[result["_시장코드"]]}/">{MARKET_NAMES[result["_시장코드"]]}</a> › '
            f'{esc(row["종목명"])}</p>',
            header_html(row, result),
            metrics_html(row, None, None),
            body_html(result),
            issues_html(report.get("주요이슈") or []),
            yearly_table_html(row),
            verification_html(result),
            footer_html(result),
        ]
    )
    title = f"{row['종목명']}({row['종목코드']}) 실적·재무 분석 | {SITE_NAME}"
    return page(
        title,
        report["헤드라인"],
        url,
        body,
        count=count,
        updated=updated,
        root=root,
        og_type="article",
        structured=report_structured(row, result, url),
    )


def card(row: pd.Series, result: dict, href: str) -> str:
    return (
        f'<a class="card" href="{href}">'
        f'<b>{esc(row["종목명"])}</b>'
        f'<small>{esc(row["종목코드"])} · {esc(row.get("업종_소분류") or "")}</small>'
        f'<p>{esc(result["리포트"]["헤드라인"])}</p></a>'
    )


def build(limit: int | None = None) -> int:
    universe = markets.load_all()
    if universe.empty:
        sys.exit("종목 데이터가 없습니다. 먼저 수집을 돌리세요.")
    # set_index를 쓰면 종목코드가 열에서 빠져 렌더링 함수(row['종목코드'])가 죽는다
    lookup = {}
    for name, market_code in MARKET_CODES.items():
        for _, row in universe[universe["국가"] == name].iterrows():
            lookup[(market_code, str(row["종목코드"]))] = row

    reports = load_reports(limit)
    if not reports:
        sys.exit("리포트 캐시가 없습니다.")
    updated = date.today().isoformat()

    OUT.mkdir(parents=True, exist_ok=True)
    made, skipped, by_market, urls = 0, 0, {}, []

    for result in reports:
        key = (result["_시장코드"], result["_종목코드"])
        row = lookup.get(key)
        if row is None:  # 상장폐지 등으로 목록에서 빠진 종목
            skipped += 1
            continue

        slug = MARKET_SLUGS[result["_시장코드"]]
        rel = f"{slug}/{result['_종목코드']}.html"
        url = f"{BASE_URL}/{rel}"
        target = OUT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            report_page(row, result, "..", url, len(reports), updated), encoding="utf-8"
        )
        by_market.setdefault(result["_시장코드"], []).append((row, result, f"{result['_종목코드']}.html"))
        urls.append(url)
        made += 1

    # 시장별 목록
    for market_code, entries in by_market.items():
        cards = "".join(card(row, result, href) for row, result, href in entries)
        name = MARKET_NAMES[market_code]
        body = (
            f'<p class="crumb"><a href="..">홈</a> › {esc(name)}</p>'
            f"<div class='hero'><h1>{esc(name)} 리포트 {len(entries):,}건</h1>"
            f"<p>{esc(TAGLINE)}</p></div>"
            f'<div class="card-list">{cards}</div>'
        )
        url = f"{BASE_URL}/{MARKET_SLUGS[market_code]}/"
        (OUT / MARKET_SLUGS[market_code] / "index.html").write_text(
            page(f"{name} AI 기업 리포트 | {SITE_NAME}", f"{name} {len(entries):,}종목 분석",
                 url, body, count=len(reports), updated=updated, root=".."),
            encoding="utf-8",
        )
        urls.append(url)

    write_home(by_market, reports, updated, urls)
    write_policy_pages(len(reports), updated, urls)
    write_sitemap(urls)
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8"
    )

    print(f"생성 {made:,}쪽 · 건너뜀 {skipped}건 · 출력 {OUT}")
    print("시장별:", {MARKET_NAMES[k]: len(v) for k, v in by_market.items()})
    return 0


def write_home(by_market, reports, updated, urls) -> None:
    latest = sorted(reports, key=lambda r: r["생성시각"], reverse=True)[:12]
    cards = []
    for result in latest:
        slug = MARKET_SLUGS[result["_시장코드"]]
        cards.append(
            f'<a class="card" href="{slug}/{result["_종목코드"]}.html">'
            f'<b>{esc(result["종목명"])}</b><small>{esc(result["_종목코드"])}</small>'
            f'<p>{esc(result["리포트"]["헤드라인"])}</p></a>'
        )
    tabs = "".join(
        f'<a href="{MARKET_SLUGS[code]}/">{MARKET_NAMES[code]} {len(entries):,}</a>'
        for code, entries in by_market.items()
    )
    body = f"""
<div class="hero">
  <h1>{esc(SITE_NAME)}</h1>
  <p>{esc(TAGLINE)}</p>
  <p><span class="stat">국내 상장사의 74.9%</span>는 최근 3개월 안에 나온 증권사 리포트가 없습니다.
     초소형주는 91.7%입니다.</p>
  <p>계산은 코드가 하고, AI는 주어진 값만 인용해 서술하고, 생성된 문장의 숫자는
     기계가 원본과 대조합니다. 대조 결과를 리포트에 함께 표시합니다.</p>
</div>
<div class="market-tabs">{tabs}</div>
<h2>최근 작성</h2>
<div class="card-list">{''.join(cards)}</div>
"""
    (OUT / "index.html").write_text(
        page(f"{SITE_NAME} — {TAGLINE}", TAGLINE, f"{BASE_URL}/", body,
             count=len(reports), updated=updated),
        encoding="utf-8",
    )
    urls.append(f"{BASE_URL}/")


def write_policy_pages(count: int, updated: str, urls: list) -> None:
    """광고 심사와 신뢰 확보에 필요한 고정 페이지."""
    about = """<div class="doc">
<h1>소개</h1>
<p>리포트 셀프바는 증권사 리포트가 없는 종목까지 공개 데이터로 기업 분석을 만들어 공개합니다.
국내·미국·일본·중국 상장사를 다룹니다.</p>
<h2>어떻게 만드나</h2>
<p>증감률, 영업레버리지, 이익 변화의 매출·마진 분해, 업종 중앙값 비교 같은 계산은 코드가 합니다.
AI는 그 값만 인용해 문장을 씁니다. 생성된 문장에서 금액과 비율을 다시 뽑아 원본과 대조하고,
대조 결과를 리포트에 함께 표시합니다.</p>
<h2>무엇을 하지 않나</h2>
<p>투자의견과 목표주가는 만들지 않습니다. 특정 종목의 매수·매도를 권유하지 않습니다.
투자 판단과 그 결과에 대한 책임은 이용자 본인에게 있습니다.</p>
<h2>데이터 출처</h2>
<p>금융감독원 전자공시시스템(DART)의 재무제표와 공시, 네이버 금융의 시세와 기업 개요를 씁니다.</p>
</div>"""
    privacy = """<div class="doc">
<h1>개인정보처리방침</h1>
<p>리포트 셀프바는 회원가입을 받지 않으며 이름, 연락처 같은 개인정보를 직접 수집하지 않습니다.</p>
<h2>쿠키와 광고</h2>
<p>이 사이트는 방문 통계와 광고 게재를 위해 제3자 도구를 사용할 수 있습니다. 해당 도구는
쿠키를 사용해 방문 기록을 수집할 수 있으며, 이용자는 브라우저 설정에서 쿠키를 거부할 수 있습니다.
구글 광고를 사용하는 경우 <a href="https://policies.google.com/technologies/ads">구글 광고 정책</a>을 따릅니다.</p>
<h2>문의</h2>
<p>문의는 GitHub 저장소의 이슈로 받습니다.</p>
</div>"""
    for name, body, title in [
        ("about.html", about, f"소개 | {SITE_NAME}"),
        ("privacy.html", privacy, f"개인정보처리방침 | {SITE_NAME}"),
    ]:
        url = f"{BASE_URL}/{name}"
        (OUT / name).write_text(
            page(title, title, url, body, count=count, updated=updated), encoding="utf-8"
        )
        urls.append(url)


def write_sitemap(urls: list[str]) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d")
    entries = "".join(
        f"<url><loc>{html.escape(u)}</loc><lastmod>{stamp}</lastmod></url>" for u in urls
    )
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>',
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="리포트를 정적 웹페이지로 만든다")
    parser.add_argument("--limit", type=int, default=None, help="앞의 N건만 (확인용)")
    args = parser.parse_args()
    return build(args.limit)


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
