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
OUTPUT = ROOT / "test-results"
OUTPUT.mkdir(exist_ok=True)


def load_page(browser, data=None, *, now=None, mobile=False, route="overview"):
    page = browser.new_page(viewport={"width": 390 if mobile else 1440, "height": 900})
    page.emulate_media(reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    if now:
        page.add_init_script(f"Date.now = () => Date.parse({json.dumps(now)});")
    if data is not None:
        page.route("**/data/observations.json*", lambda request: request.fulfill(
            content_type="application/json", body=json.dumps(data)))
    page.goto(BASE.rstrip("/") + "/#/" + route, wait_until="networkidle")
    page.locator(f'#route-view[data-page="{route}"]').wait_for(state="visible")
    assert not errors, errors
    return page, errors


def navigate(page, route):
    page.locator(f'#sidebar a[data-route="{route}"]').click()
    page.locator(f'#route-view[data-page="{route}"]').wait_for(state="visible")


def sample(value, at, game="hela", status="ok"):
    return {
        "game_id": game, "metric": "demo_ccu", "observed_at": at,
        "value": value, "status": status,
        "source_url": "https://api.steampowered.com/example",
        "error_code": "network_error" if status == "error" else None,
    }


def fixture(first=0, second=10, gap=False):
    data = copy.deepcopy(DATA)
    data["samples"] = [
        sample(first, "2026-10-20T08:00:00Z"),
        sample(second, "2026-10-20T10:00:00Z" if gap else "2026-10-20T08:20:00Z"),
        sample(0, "2026-10-20T08:00:00Z", game="lethal-wedding"),
        sample(0, "2026-10-20T08:20:00Z", game="lethal-wedding"),
    ]
    data["analyses"] = []
    data["events"] = [
        {
            "id": "fixture-before", "game_id": "hela", "kind": "announcement",
            "title": "공식 데모 업데이트", "summary": "브라우저 내부 검증용 이벤트",
            "occurred_at": None, "published_at": "2026-10-20T08:10:00Z",
            "time_precision": "minute", "source_url": "https://store.steampowered.com/",
            "verified_at": "2026-10-20T08:30:00Z", "content_review": "source_verified",
            "discovery_method": "verified_official_steam_news",
        },
        {
            "id": "fixture-after", "game_id": "hela", "kind": "video",
            "title": "공식 개발 영상", "summary": "증가 구간 이후 게시",
            "occurred_at": None, "published_at": "2026-10-20T08:25:00Z",
            "time_precision": "minute", "source_url": "https://www.youtube.com/",
            "verified_at": "2026-10-20T08:30:00Z", "content_review": "source_verified",
            "discovery_method": "verified_official_video",
        },
    ]
    return data


def assert_width(page, width):
    assert page.locator("body").evaluate("(e) => e.scrollWidth") <= width


def screenshot(page, name):
    page.evaluate("""async () => {
        window.scrollTo(0, 0);
        document.activeElement?.blur();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")
    page.screenshot(path=str(OUTPUT / name), full_page=True)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page, errors = load_page(browser)
    assert_width(page, 1440)
    screenshot(page, "desktop-overview.png")
    for route in ["compare", "analysis", "events", "collection"]:
        navigate(page, route)
        assert page.locator("#page-title").inner_text().strip()
        assert_width(page, 1440)
    page.go_back()
    page.locator('#route-view[data-page="events"]').wait_for()
    navigate(page, "analysis")
    page.locator("#game-select").select_option("lethal-wedding")
    page.locator('[data-range="6"]').click()
    navigate(page, "overview")
    navigate(page, "analysis")
    assert page.locator("#game-select").input_value() == "lethal-wedding"
    assert page.locator('[data-range="6"]').get_attribute("aria-pressed") == "true"
    page.locator('[data-range="all"]').click()
    with page.expect_download() as download_info:
        page.locator("#download-csv").click()
    downloaded = Path(download_info.value.path()).read_text(encoding="utf-8-sig")
    assert "lethal-wedding" in downloaded and "demo_ccu" in downloaded
    page.locator("#refresh-data").click()
    page.wait_for_load_state("networkidle")
    assert page.locator("#game-select").input_value() == "lethal-wedding"
    page.locator("#game-select").select_option("hela")
    screenshot(page, "desktop-analysis.png")
    assert not errors, errors
    page.close()
    print("PASS five screens, browser back, persistent filters, refresh and CSV")

    mobile, errors = load_page(browser, mobile=True)
    mobile.locator("#menu-toggle").click()
    navigate(mobile, "analysis")
    mobile.locator("#game-select").select_option("lethal-wedding")
    assert_width(mobile, 390)
    screenshot(mobile, "mobile-analysis.png")
    mobile.locator("#menu-toggle").click()
    mobile.keyboard.press("Escape")
    assert mobile.locator("#menu-toggle").get_attribute("aria-expanded") == "false"
    assert not errors, errors
    mobile.close()
    print("PASS mobile navigation, Escape and contained table scrolling")

    one = fixture()
    one["samples"] = [one["samples"][0]]
    page, _ = load_page(browser, one, now="2026-10-20T08:30:00Z", route="analysis")
    assert page.locator("[data-interval-id]").count() == 0
    assert page.locator("#analysis-chart polyline").count() == 0
    assert "Infinity" not in page.locator("#route-view").inner_text()
    page.close()
    print("PASS one observation creates neither an interval nor a trend")

    page, _ = load_page(browser, fixture(), now="2026-10-20T08:30:00Z", route="analysis")
    intervals = page.locator("[data-interval-id]")
    assert intervals.count() == 1
    assert "+10" in intervals.first.locator("xpath=ancestor::tr").inner_text()
    assert "Infinity" not in page.locator("#route-view").inner_text()
    intervals.first.click()
    assert "공식 데모 업데이트" in page.locator("#interval-detail").inner_text()
    page.locator("#metric-select").select_option("followers")
    assert "미확보" in page.locator("#route-view").inner_text()
    assert page.locator("#analysis-chart polyline").count() == 0
    page.close()
    print("PASS zero baseline, selected increase evidence and unavailable metric")

    gap = fixture(gap=True)
    interrupted = fixture()
    interrupted["samples"].append(sample(None, "2026-10-20T08:10:00Z", status="error"))
    for name, data, now in [
        ("long gap", gap, "2026-10-20T10:10:00Z"),
        ("failed observation", interrupted, "2026-10-20T08:30:00Z"),
    ]:
        page, _ = load_page(browser, data, now=now, route="analysis")
        assert page.locator("[data-interval-id]").count() == 0, name
        assert page.locator("#analysis-chart polyline").count() == 0, name
        page.close()
    print("PASS missing and failed observations break chart lines and increase pairs")

    page, _ = load_page(browser, fixture(), now="2026-10-20T08:30:00Z", route="events")
    page.locator("#events-search").fill("개발 영상")
    assert page.locator("[data-event-id]").count() == 1
    assert "공식 개발 영상" in page.locator("[data-event-id]").inner_text()
    page.locator("#events-search").fill("")
    page.locator("#events-kind").select_option("announcement")
    assert page.locator("[data-event-id]").count() == 1
    page.locator("#events-game").select_option("lethal-wedding")
    assert page.locator("[data-event-id]").count() == 0
    page.close()
    print("PASS event search, type and game filters")

    period = fixture(5, 10)
    for observation in period["samples"]:
        observation["observed_at"] = observation["observed_at"].replace("2026-10-20", "2026-10-21")
    period["samples"].append(sample(999, "2026-10-20T08:00:00Z"))
    page, _ = load_page(browser, period, now="2026-10-21T08:30:00Z", route="compare")
    page.locator('[data-range="24"]').click()
    hela = page.locator("#comparison-table tbody tr").filter(has_text="Hela")
    assert hela.locator("td").nth(2).inner_text() == "10명"
    assert hela.locator("td").nth(4).inner_text() == "+5"
    assert hela.locator("td").nth(5).inner_text() == "2회"
    page.locator('[data-range="all"]').click()
    assert hela.locator("td").nth(2).inner_text() == "999명"
    page.close()
    print("PASS comparison uses the chosen common period and excludes outside peaks")

    boundary = fixture()
    boundary["events"][0]["published_at"] = "2026-10-19T14:59:00Z"
    boundary["events"][1]["published_at"] = "2026-10-19T15:01:00Z"
    page, _ = load_page(browser, boundary, now="2026-10-20T08:30:00Z", route="events")
    page.locator("#events-from").fill("2026-10-20")
    page.locator("#events-to").fill("2026-10-20")
    page.locator("#events-to").press("Tab")
    assert page.locator("[data-event-id]").count() == 1
    assert page.locator("[data-event-id]").get_attribute("data-event-id") == "fixture-after"
    page.close()
    print("PASS event date filtering uses KST midnight")

    failed = fixture(5, 10)
    failed["samples"][1].update(value=None, status="error", error_code="network_error")
    failed["news_status"]["hela"].update(status="error", error_codes=["http_500"])
    page, _ = load_page(browser, failed, now="2026-10-20T09:30:00Z", route="collection")
    assert "오류" in page.locator("#collection-table").inner_text()
    assert "http_500" in page.locator("#route-view").inner_text()
    navigate(page, "events")
    assert page.locator("[data-event-id]").count() == 2
    navigate(page, "analysis")
    assert page.locator(".chart-stat strong").first.inner_text().strip() == "5명"
    assert "수집 오류" in page.locator(".chart-card .card-header").inner_text()
    page.close()
    print("PASS source failures stay visible without removing previous events")

    page, _ = load_page(browser, fixture(5, 10), now="2026-10-20T08:30:00Z", route="analysis")
    page.unroute("**/data/observations.json*")
    page.route("**/data/observations.json*", lambda request: request.fulfill(status=503, body="unavailable"))
    page.locator("#refresh-data").click()
    page.locator("#refresh-status").wait_for(state="visible")
    assert page.locator(".chart-stat strong").first.inner_text().strip() == "10명"
    assert page.locator("#samples-table tbody tr").count() == 2
    assert page.locator("#refresh-data").is_enabled()
    page.close()
    print("PASS failed refresh preserves loaded data and allows retry")

    page, _ = load_page(browser, now="2026-10-27T00:00:00Z")
    assert "종료" in page.locator("#sidebar-collection").inner_text()
    page.close()
    print("PASS scheduled end is reflected even without a final collection")

    injected = fixture()
    injected["events"][0]["title"] = '<img src=x onerror="window.bad=1">'
    page, _ = load_page(browser, injected, now="2026-10-20T08:30:00Z", route="events")
    assert page.locator("#route-view img").count() == 0
    assert page.evaluate("window.bad || null") is None
    page.close()
    print("PASS untrusted event text cannot create markup")
    browser.close()
