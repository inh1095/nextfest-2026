"""Browser checks using in-memory fixtures; never writes synthetic public data.

Run a local static server, then: python3 tests/browser_smoke.py [base_url]
Requires an installed Playwright browser. Not used by the scheduled collector.
"""
import copy
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
DATA = json.loads((ROOT / "site/data/observations.json").read_text())
CONFIG = json.loads((ROOT / "site/data/config.json").read_text())
OUTPUT = ROOT / "test-results"
OUTPUT.mkdir(exist_ok=True)


def load_page(browser, data=None, *, now=None, mobile=False):
    page = browser.new_page(viewport={"width": 390 if mobile else 1440, "height": 844 if mobile else 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    if now:
        page.add_init_script(f"Date.now = () => Date.parse({json.dumps(now)});")
    if data is not None:
        page.route("**/data/observations.json*", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps(data)))
    page.goto(BASE, wait_until="networkidle")
    page.locator("#detail-panel").wait_for(state="visible")
    assert not errors, errors
    return page, errors


def synthetic(first=0, second=10, gap=False):
    data = copy.deepcopy(DATA)
    data["analyses"] = []
    data["samples"] = [
        {"game_id": "hela", "metric": "demo_ccu", "observed_at": at, "value": value,
         "status": "ok", "source_url": "https://api.steampowered.com/example", "error_code": None}
        for at, value in [
            ("2026-10-20T08:00:00Z", first),
            ("2026-10-20T10:00:00Z" if gap else "2026-10-20T08:20:00Z", second)
        ]
    ]
    return data


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page, errors = load_page(browser)
    assert page.locator(".game-card").count() == 2
    assert all(page.locator(".game-art img").evaluate_all("(xs)=>xs.map(x=>x.complete&&x.naturalWidth>0)"))
    assert page.locator("body").evaluate("(e)=>e.scrollWidth") <= 1440
    assert "최초 관측 이전" in page.locator("#event-detail").inner_text()
    assert "미확보" in page.locator(".followers").inner_text()
    page.locator('[data-game="lethal-wedding"]').click()
    assert "Lethal Wedding" in page.locator("#detail-title").inner_text()
    assert page.locator(".demo_ccu .metric-value").inner_text().strip().startswith("0")
    page.locator('[data-range="6"]').click()
    assert page.locator('[data-range="6"]').get_attribute("aria-pressed") == "true"
    page.locator('[data-range="all"]').click()
    with page.expect_download() as info:
        page.locator("#download-csv").click()
    download = info.value
    text = Path(download.path()).read_text(encoding="utf-8-sig")
    assert "lethal-wedding" in text and '"0"' in text
    page.locator('[data-game="hela"]').click()
    page.screenshot(path=str(OUTPUT / "desktop.png"), full_page=True)
    assert not errors
    page.close()
    print("PASS live dataset, game/range selection, sources and CSV export")

    mobile, errors = load_page(browser, mobile=True)
    assert mobile.locator("body").evaluate("(e)=>e.scrollWidth") <= 390
    mobile.locator('[data-game="lethal-wedding"]').click()
    mobile.screenshot(path=str(OUTPUT / "mobile.png"), full_page=True)
    assert not errors
    mobile.close()
    print("PASS mobile width, game switching and layout")

    one = copy.deepcopy(DATA)
    first = next(s for s in one["samples"] if s["game_id"] == "hela" and s["metric"] == "demo_ccu")
    one["samples"] = [first]
    page, _ = load_page(browser, one)
    assert page.locator(".demo_ccu circle").count() == 1
    assert page.locator(".demo_ccu polyline").count() == 0
    assert "기준선 수집 중" in page.locator("#growth-insights").inner_text()
    page.close()
    print("PASS single observation does not invent trend")

    page, _ = load_page(browser, synthetic(), now="2026-10-20T08:30:00Z")
    assert "+10" in page.locator("#growth-insights").inner_text()
    assert "증가율은 계산하지 않습니다" in page.locator("#growth-insights").inner_text()
    assert "Infinity" not in page.locator("body").inner_text()
    page.close()
    page, _ = load_page(browser, synthetic(gap=True), now="2026-10-20T10:10:00Z")
    assert page.locator(".demo_ccu polyline").count() == 0
    assert "확인된 증가 없음" in page.locator("#growth-insights").inner_text()
    page.close()
    print("PASS zero denominator and missing-interval separation")

    failed = synthetic(5, 10)
    failed["samples"][-1].update(value=None, status="error", error_code="network_error")
    failed["news_status"]["hela"].update(status="error", error_codes=["http_500"])
    page, _ = load_page(browser, failed, now="2026-10-20T09:30:00Z")
    assert page.locator(".demo_ccu .metric-value").inner_text().strip().startswith("5")
    assert "수집 오류" in page.locator(".demo_ccu").inner_text()
    assert "지연" in page.locator(".demo_ccu").inner_text()
    assert "수집 오류" in page.locator("#news-freshness").inner_text()
    assert page.locator(".event-button").count() > 0
    page.close()
    print("PASS partial failures preserve prior values/events and expose freshness")

    page, _ = load_page(browser, now="2026-10-27T00:00:00Z")
    assert "수집 종료" in page.locator("#collection-status").inner_text()
    assert "지연" not in page.locator(".demo_ccu .metric-observed").inner_text()
    page.close()
    print("PASS archive status without an end-of-event collection")

    injected = copy.deepcopy(DATA)
    injected["events"][0]["title"] = '<img src=x onerror="window.bad=1">'
    page, _ = load_page(browser, injected)
    assert page.locator(".event-title img").count() == 0
    assert page.evaluate("window.bad || null") is None
    page.close()
    print("PASS event text escapes untrusted markup")
    browser.close()
