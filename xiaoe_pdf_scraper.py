from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, Response, TimeoutError as PlaywrightTimeoutError, sync_playwright

try:
    import browser_cookie3
except ImportError:
    browser_cookie3 = None


DEFAULT_TAG_URL = (
    "https://quanzi.xiaoe-tech.com/"
    "c_6784b0c7f2fe0_MvZcjz4r1642/"
    "tag_detail?listType=477732&tagName=%E8%AF%95%E9%A2%98&app_id=apphihyjorj6008"
)
DEFAULT_FEED_URL = (
    "https://quanzi.xiaoe-tech.com/"
    "c_6784b0c7f2fe0_MvZcjz4r1642/"
    "feed_list?app_id=apphihyjorj6008"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
PDF_URL_RE = re.compile(r"https?://[^\s\"'<>]+\.pdf(?:\?[^\s\"'<>]*)?", re.IGNORECASE)
DETAIL_URL_RE = re.compile(r"(?:https?://[^\s\"'<>]+)?/[^\s\"'<>]*/feed_detail\?[^\s\"'<>]*feeds?_id=", re.IGNORECASE)
INVALID_FILENAME_CHARS = '<>:"/\\|?*'
LOGIN_SUCCESS_HINTS = ("圈子", "试题", "帖子", "动态")
LOGIN_INPUT_SELECTORS = (
    'input[type="password"]',
    'input[placeholder*="手机号"]',
    'input[placeholder*="手机"]',
    'button:has-text("登录")',
    'text=验证码',
)
MATH_INCLUDE_KEYWORDS = ("数学",)
PAPER_INCLUDE_KEYWORDS = ("卷", "试卷", "答案")
SUBJECT_EXCLUDE_KEYWORDS = ("语文", "英语", "物理", "化学", "生物", "历史", "地理", "政治")
NAME_FIELDS = [
    "origin_name",
    "originName",
    "file_name",
    "fileName",
    "filename",
    "attachment_name",
    "attachmentName",
    "name",
    "title",
    "resource_title",
    "resourceTitle",
    "material_title",
    "materialTitle",
    "display_name",
    "displayName",
    "doc_name",
    "docName",
]
PAGE_TITLE_FIELDS = [
    "title",
    "feed_title",
    "feedTitle",
    "post_title",
    "postTitle",
    "subject",
]
URL_FIELDS = ["url", "link", "href", "download_url", "downloadUrl", "jump_url", "jumpUrl"]
LOGIN_COOKIE_HINTS = ("pc_token_", "user_id_", "union_id", "ko_token", "pc_user_key")
COOKIE_DOMAINS = ("xiaoe-tech.com", "xiaoeknow.com")


def canonical_pdf_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def sanitize_filename(name: str | None, fallback_url: str) -> str:
    candidate = (name or "").strip()
    if not candidate:
        candidate = Path(urllib.parse.urlsplit(fallback_url).path).name or "download.pdf"
    candidate = urllib.parse.unquote(candidate)
    candidate = candidate.replace("\n", " ").replace("\r", " ").strip().rstrip(".")
    candidate = "".join("_" if ch in INVALID_FILENAME_CHARS else ch for ch in candidate)
    candidate = re.sub(r"\s+", " ", candidate)
    if not candidate.lower().endswith(".pdf"):
        candidate = f"{candidate}.pdf"
    return candidate[:180] or "download.pdf"


def is_target_math_pdf(record: dict[str, Any]) -> bool:
    haystacks = [
        str(record.get("filename", "")),
        str(record.get("page_title", "")),
        str(record.get("page_url", "")),
        str(record.get("url", "")),
    ]
    text = " ".join(haystacks)
    if any(keyword in text for keyword in SUBJECT_EXCLUDE_KEYWORDS):
        return False
    if not any(keyword in text for keyword in MATH_INCLUDE_KEYWORDS):
        return False
    if not any(keyword in text for keyword in PAPER_INCLUDE_KEYWORDS):
        return False
    return True


def better_name(current_name: str | None, new_name: str | None) -> str | None:
    if not new_name:
        return current_name
    if not current_name:
        return new_name
    return new_name if len(urllib.parse.unquote(new_name)) > len(urllib.parse.unquote(current_name)) else current_name


def env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def choose_chrome_executable(explicit_path: str | None) -> str:
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise RuntimeError(f"指定的 Chrome 路径不存在: {path}")
        return str(path)

    local_app_data = env_path("LOCALAPPDATA")
    user_profile = env_path("USERPROFILE")
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        (local_app_data / r"Google\Chrome\Application\chrome.exe") if local_app_data else None,
        (user_profile / r"AppData\Local\Google\Chrome\Application\chrome.exe") if user_profile else None,
        Path(r"C:\Program Files\Google\Chrome for Testing\chrome.exe"),
        (local_app_data / r"Google\Chrome for Testing\chrome.exe") if local_app_data else None,
        Path(r"C:\Program Files\Google\Chrome for Testing\Application\chrome.exe"),
        (local_app_data / r"Google\Chrome for Testing\Application\chrome.exe") if local_app_data else None,
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    raise RuntimeError("未找到 Chrome 或 Chrome for Testing，请用 --chrome-path 显式指定 chrome.exe。")


def merge_cookie_jars(cookie_jars: list[http.cookiejar.CookieJar]) -> list[http.cookiejar.Cookie]:
    merged: dict[tuple[str, str, str], http.cookiejar.Cookie] = {}
    for jar in cookie_jars:
        for cookie in jar:
            merged[(cookie.domain, cookie.path, cookie.name)] = cookie
    return list(merged.values())


def cookie_jar_for_chrome() -> list[http.cookiejar.Cookie]:
    if browser_cookie3 is None:
        raise RuntimeError("缺少 browser-cookie3，请先执行: pip install -r requirements.txt")
    jars = []
    for domain in COOKIE_DOMAINS:
        try:
            jars.append(browser_cookie3.chrome(domain_name=domain))
        except Exception:
            continue
    return merge_cookie_jars(jars)


def playwright_same_site(cookie: http.cookiejar.Cookie) -> str:
    same_site = None
    for attr_name in ("SameSite", "sameSite", "samesite"):
        if hasattr(cookie, "_rest"):
            same_site = cookie._rest.get(attr_name)
        if same_site:
            break
    if not same_site:
        return "Lax"
    same_site = str(same_site).lower()
    if same_site == "strict":
        return "Strict"
    if same_site == "none":
        return "None"
    return "Lax"


def import_chrome_cookies(context: BrowserContext) -> int:
    cookies = cookie_jar_for_chrome()
    playwright_cookies = []
    for cookie in cookies:
        if not cookie.name or not cookie.domain:
            continue
        item = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain.lstrip("."),
            "path": cookie.path or "/",
            "httpOnly": "httponly" in str(getattr(cookie, "_rest", {})).lower(),
            "secure": bool(cookie.secure),
            "sameSite": playwright_same_site(cookie),
        }
        if cookie.expires:
            item["expires"] = float(cookie.expires)
        playwright_cookies.append(item)
    if playwright_cookies:
        context.add_cookies(playwright_cookies)
    return len(playwright_cookies)


def create_context(
    *,
    chrome_path: str,
    storage_state: str | None,
    accept_downloads: bool,
) -> BrowserContext:
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        headless=False,
        executable_path=chrome_path,
        slow_mo=50,
    )
    context_options: dict[str, Any] = {
        "accept_downloads": accept_downloads,
        "viewport": {"width": 1440, "height": 960},
        "user_agent": DEFAULT_USER_AGENT,
        "extra_http_headers": {
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    }
    if storage_state and Path(storage_state).exists():
        context_options["storage_state"] = storage_state
    context = browser.new_context(**context_options)
    context.set_default_timeout(20_000)
    setattr(context, "_owned_playwright", playwright)
    return context


def close_context(context: BrowserContext) -> None:
    browser = context.browser
    context.close()
    if browser:
        browser.close()
    owned = getattr(context, "_owned_playwright", None)
    if owned:
        owned.stop()


def page_looks_logged_in(page: Page) -> bool:
    current_url = page.url.lower()
    if "login" in current_url or "/auth" in current_url:
        return False

    try:
        cookies = page.context.cookies()
    except Exception:
        cookies = []
    cookie_names = {cookie.get("name", "") for cookie in cookies}
    has_login_cookie = any(
        any(name.startswith(hint) if hint.endswith("_") else name == hint for name in cookie_names)
        for hint in LOGIN_COOKIE_HINTS
    )

    try:
        local_storage_dump = page.evaluate(
            """
            () => {
              const items = {};
              for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                items[key] = localStorage.getItem(key);
              }
              return items;
            }
            """
        )
    except Exception:
        local_storage_dump = {}
    has_user_storage = any("user_default_info/" in key for key in local_storage_dump.keys())

    try:
        body_text = page.locator("body").inner_text(timeout=5_000)
    except Exception:
        body_text = ""
    has_success_hint = any(hint in body_text for hint in LOGIN_SUCCESS_HINTS)
    has_login_input = any(page.locator(selector).count() > 0 for selector in LOGIN_INPUT_SELECTORS)
    return (has_login_cookie or has_user_storage or has_success_hint) and not has_login_input


def login_diagnostics(page: Page) -> str:
    try:
        cookies = page.context.cookies()
        cookie_names = sorted(cookie.get("name", "") for cookie in cookies if cookie.get("name"))
    except Exception:
        cookie_names = []
    try:
        body_text = page.locator("body").inner_text(timeout=5_000)
    except Exception:
        body_text = ""
    has_login_input = any(page.locator(selector).count() > 0 for selector in LOGIN_INPUT_SELECTORS)
    return (
        f"url={page.url}\n"
        f"cookie_count={len(cookie_names)}\n"
        f"login_cookies={[name for name in cookie_names if any(name.startswith(h) if h.endswith('_') else name == h for h in LOGIN_COOKIE_HINTS)]}\n"
        f"has_login_input={has_login_input}\n"
        f"body_preview={body_text[:200]!r}"
    )


def save_storage_state(page: Page, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page.context.storage_state(path=str(output_path))


def run_login(feed_url: str, chrome_path: str, storage_state_path: Path) -> int:
    context = create_context(chrome_path=chrome_path, storage_state=None, accept_downloads=False)
    try:
        page = context.new_page()
        page.goto(feed_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except PlaywrightTimeoutError:
            pass
        print("请在打开的 Chrome 窗口中手动完成登录。确认已经进入圈子页面后，回到终端按回车。")
        input()
        page.wait_for_timeout(2000)
        if not page_looks_logged_in(page):
            print("登录校验失败，下面是诊断信息：", file=sys.stderr)
            print(login_diagnostics(page), file=sys.stderr)
            print("我将尝试仍然保存当前 storage_state，供后续 fetch 实测验证。", file=sys.stderr)
        save_storage_state(page, storage_state_path)
        print(f"已保存登录态: {storage_state_path}")
        return 0
    finally:
        close_context(context)


def looks_like_pdf_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://")) and ".pdf" in value.lower()


def looks_like_detail_link(value: str) -> bool:
    lowered = value.lower()
    return "/feed_detail" in lowered or "feeds_id=" in lowered or "feed_id=" in lowered


def join_url(base_url: str, value: str) -> str:
    return urllib.parse.urljoin(base_url, value)


def build_detail_url(tag_url: str, feed_id: str | int) -> str:
    parsed = urllib.parse.urlsplit(tag_url)
    query = urllib.parse.parse_qs(parsed.query)
    app_id = query.get("app_id", [""])[0]
    detail_path = parsed.path.replace("/tag_detail", "/feed_detail")
    detail_query = {"feeds_id": str(feed_id)}
    if app_id:
        detail_query["app_id"] = app_id
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, detail_path, urllib.parse.urlencode(detail_query), "")
    )


def pick_name_from_context(nodes: list[dict[str, Any]], url: str) -> str | None:
    for node in reversed(nodes):
        for field in NAME_FIELDS:
            value = node.get(field)
            if isinstance(value, str):
                value = value.strip()
                if value and "http" not in value[:6]:
                    return sanitize_filename(value, url)
    return None


def pick_page_title_from_context(nodes: list[dict[str, Any]]) -> str | None:
    for node in reversed(nodes):
        for field in PAGE_TITLE_FIELDS:
            value = node.get(field)
            if isinstance(value, str):
                value = value.strip()
                if value and "http" not in value[:6]:
                    return value[:200]
    return None


class Collector:
    def __init__(self, tag_url: str) -> None:
        self.tag_url = tag_url
        self.pdfs: dict[str, dict[str, Any]] = {}
        self.detail_links: set[str] = set()
        self.seen_response_urls: set[str] = set()

    def add_pdf(
        self,
        url: str,
        *,
        name: str | None = None,
        page_title: str | None = None,
        page_url: str | None = None,
        source: str | None = None,
        response_url: str | None = None,
    ) -> None:
        if not looks_like_pdf_url(url):
            return
        canonical = canonical_pdf_url(url)
        record = self.pdfs.get(canonical, {})
        record["canonical_url"] = canonical
        record["url"] = url
        record["filename"] = better_name(record.get("filename"), sanitize_filename(name, url) if name else None)
        record["page_title"] = page_title or record.get("page_title")
        record["page_url"] = page_url or record.get("page_url")
        record["source"] = source or record.get("source")
        record["response_url"] = response_url or record.get("response_url")
        if not record.get("filename"):
            record["filename"] = sanitize_filename(None, url)
        self.pdfs[canonical] = record

    def add_detail_link(self, value: str, base_url: str) -> None:
        if not looks_like_detail_link(value):
            return
        url = join_url(base_url, value)
        if "/feed_detail" in url.lower():
            self.detail_links.add(url)

    def scan_payload(self, payload: Any, *, base_url: str, response_url: str, page_url: str) -> None:
        self._scan_any(payload, base_url=base_url, response_url=response_url, page_url=page_url, stack=[])

    def _scan_any(
        self,
        value: Any,
        *,
        base_url: str,
        response_url: str,
        page_url: str,
        stack: list[dict[str, Any]],
    ) -> None:
        if isinstance(value, dict):
            current_stack = stack + [value]
            feed_id = value.get("feeds_id") or value.get("feed_id")
            if isinstance(feed_id, (str, int)) and str(feed_id).strip():
                self.detail_links.add(build_detail_url(self.tag_url, str(feed_id).strip()))
            for field in URL_FIELDS:
                field_value = value.get(field)
                if isinstance(field_value, str):
                    if looks_like_pdf_url(field_value):
                        self.add_pdf(
                            field_value,
                            name=pick_name_from_context(current_stack, field_value),
                            page_title=pick_page_title_from_context(current_stack),
                            page_url=page_url,
                            source="json",
                            response_url=response_url,
                        )
                    elif looks_like_detail_link(field_value):
                        self.add_detail_link(field_value, base_url)
            for nested_value in value.values():
                self._scan_any(
                    nested_value,
                    base_url=base_url,
                    response_url=response_url,
                    page_url=page_url,
                    stack=current_stack,
                )
            return

        if isinstance(value, list):
            for item in value:
                self._scan_any(item, base_url=base_url, response_url=response_url, page_url=page_url, stack=stack)
            return

        if isinstance(value, str):
            if looks_like_pdf_url(value):
                self.add_pdf(
                    value,
                    name=pick_name_from_context(stack, value),
                    page_title=pick_page_title_from_context(stack),
                    page_url=page_url,
                    source="json",
                    response_url=response_url,
                )
                return
            for match in PDF_URL_RE.findall(value):
                self.add_pdf(
                    match,
                    name=pick_name_from_context(stack, match),
                    page_title=pick_page_title_from_context(stack),
                    page_url=page_url,
                    source="json-string",
                    response_url=response_url,
                )
            for match in DETAIL_URL_RE.findall(value):
                self.add_detail_link(match, base_url)


def attach_response_listener(page: Page, collector: Collector) -> None:
    def handle_response(response: Response) -> None:
        if response.url in collector.seen_response_urls:
            return
        collector.seen_response_urls.add(response.url)
        try:
            content_type = response.headers.get("content-type", "").lower()
            if ".pdf" in response.url.lower():
                collector.add_pdf(
                    response.url,
                    page_title=page.title(),
                    page_url=page.url,
                    source="network-pdf",
                    response_url=response.url,
                )
                return
            if "json" not in content_type:
                return
            payload = response.json()
            collector.scan_payload(payload, base_url=page.url, response_url=response.url, page_url=page.url)
        except Exception:
            return

    page.on("response", handle_response)


def collect_dom_links(page: Page, collector: Collector) -> None:
    items = page.evaluate(
        """
        () => {
          const attrs = ['href', 'src', 'data-href', 'data-url', 'data-src'];
          const nodes = [];
          const seen = new Set();
          for (const el of document.querySelectorAll('[href], [src], [data-href], [data-url], [data-src]')) {
            let url = '';
            for (const attr of attrs) {
              const value = el.getAttribute(attr);
              if (value) {
                url = value;
                break;
              }
            }
            if (!url) continue;
            const key = `${url}::${(el.textContent || '').trim()}`;
            if (seen.has(key)) continue;
            seen.add(key);
            nodes.push({ url, text: (el.textContent || '').trim().slice(0, 200) });
          }
          return nodes;
        }
        """
    )
    page_url = page.url
    page_title = page.title()
    for item in items:
        url = join_url(page_url, item.get("url", ""))
        text = item.get("text", "").strip()
        if looks_like_pdf_url(url):
            collector.add_pdf(url, name=text or None, page_title=page_title, page_url=page_url, source="dom")
        elif looks_like_detail_link(url):
            collector.add_detail_link(url, page_url)


def auto_scroll(page: Page, idle_rounds: int = 4, pause_ms: int = 1500) -> None:
    stable_rounds = 0
    last_height = 0
    while stable_rounds < idle_rounds:
        page.evaluate(
            """
            () => {
              window.scrollBy(0, window.innerHeight * 0.9);
              window.scrollTo(0, document.body.scrollHeight);
            }
            """
        )
        page.wait_for_timeout(pause_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass
        new_height = page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
        if new_height <= last_height + 8:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_height = new_height


def visit_page(page: Page, url: str, collector: Collector, *, scroll: bool) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=7_000)
    except Exception:
        pass
    if scroll:
        auto_scroll(page)
    collect_dom_links(page, collector)


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {"items": {}}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def save_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def unique_target_path(output_dir: Path, desired_name: str, manifest: dict[str, Any], canonical_url: str) -> Path:
    existing = manifest["items"].get(canonical_url)
    if existing and existing.get("saved_path"):
        saved_path = Path(existing["saved_path"])
        if saved_path.exists():
            return saved_path
    base = output_dir / desired_name
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix or ".pdf"
    index = 2
    while True:
        candidate = output_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def download_file(url: str, target_path: Path, referer: str, timeout: int = 90) -> tuple[int | None, int]:
    tmp_path = target_path.with_suffix(target_path.suffix + ".part")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": referer,
        },
    )
    size = 0
    with urllib.request.urlopen(req, timeout=timeout) as response, tmp_path.open("wb") as handle:
        status = getattr(response, "status", None)
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
            size += len(chunk)
    tmp_path.replace(target_path)
    return status, size


def run_fetch(
    *,
    tag_url: str,
    output_dir: Path,
    manifest_path: Path,
    storage_state_path: Path,
    chrome_path: str,
    max_details: int | None,
    stats_only: bool,
) -> int:
    collector = Collector(tag_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    context = create_context(
        chrome_path=chrome_path,
        storage_state=str(storage_state_path) if storage_state_path.exists() else None,
        accept_downloads=False,
    )
    try:
        page = context.new_page()
        attach_response_listener(page, collector)
        visit_page(page, tag_url, collector, scroll=False)
        if not page_looks_logged_in(page):
            imported = import_chrome_cookies(context)
            print(f"storage_state 不可用，已从 Chrome 导入 {imported} 个 cookie，正在重试。")
            page = context.new_page()
            attach_response_listener(page, collector)
            visit_page(page, tag_url, collector, scroll=False)
            if not page_looks_logged_in(page):
                print("Chrome cookie 导入后仍未登录成功，请重新执行 login。", file=sys.stderr)
                return 1
        visit_page(page, tag_url, collector, scroll=True)

        detail_links = sorted(collector.detail_links)
        if max_details is not None:
            detail_links = detail_links[:max_details]
        print(f"已发现 {len(detail_links)} 个详情页，开始补抓。")

        for index, detail_url in enumerate(detail_links, start=1):
            print(f"[{index}/{len(detail_links)}] 访问详情页: {detail_url}")
            visit_page(page, detail_url, collector, scroll=False)

        filtered_records = [record for record in collector.pdfs.values() if is_target_math_pdf(record)]
        print(f"共发现 {len(collector.pdfs)} 个 PDF 候选，其中数学试卷/答案 {len(filtered_records)} 个。")
        if stats_only:
            return 0

        print("开始下载数学试卷/答案。")
        for index, record in enumerate(filtered_records, start=1):
            target_path = unique_target_path(output_dir, record["filename"], manifest, record["canonical_url"])
            if target_path.exists() and target_path.stat().st_size > 0:
                manifest["items"][record["canonical_url"]] = {
                    **record,
                    "saved_path": str(target_path),
                    "size": target_path.stat().st_size,
                    "downloaded_at": int(time.time()),
                }
                print(f"[{index}/{len(filtered_records)}] 跳过已存在: {target_path.name}")
                continue

            print(f"[{index}/{len(filtered_records)}] 下载: {target_path.name}")
            status, size = download_file(record["url"], target_path, referer=record.get("page_url") or tag_url)
            manifest["items"][record["canonical_url"]] = {
                **record,
                "saved_path": str(target_path),
                "http_status": status,
                "size": size,
                "downloaded_at": int(time.time()),
            }
            save_manifest(manifest_path, manifest)
        save_manifest(manifest_path, manifest)
        return 0
    finally:
        close_context(context)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小鹅通圈子 PDF 抓取工具。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="打开浏览器手动登录，并保存 storage_state.json")
    login_parser.add_argument("--login-url", "--feed-url", dest="feed_url", default=DEFAULT_FEED_URL, help="登录用页面 URL。")
    login_parser.add_argument("--chrome-path", default=None, help="显式指定 chrome.exe 路径。")
    login_parser.add_argument("--storage-state", default="state/storage_state.json", help="storage_state.json 输出路径。")

    fetch_parser = subparsers.add_parser("fetch", help="复用 storage_state.json 抓取并下载 PDF")
    fetch_parser.add_argument("--crawl-url", "--tag-url", dest="tag_url", default=DEFAULT_TAG_URL, help="抓取页 URL。")
    fetch_parser.add_argument("--output-dir", default="downloads", help="PDF 下载目录。")
    fetch_parser.add_argument("--manifest", default="downloads/manifest.json", help="下载记录文件路径。")
    fetch_parser.add_argument("--storage-state", default="state/storage_state.json", help="storage_state.json 路径。")
    fetch_parser.add_argument("--chrome-path", default=None, help="显式指定 chrome.exe 路径。")
    fetch_parser.add_argument("--max-details", type=int, default=None, help="仅处理前 N 个详情页。")
    fetch_parser.add_argument("--stats-only", action="store_true", help="只统计详情页和 PDF 候选数量，不下载。")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        chrome_path = choose_chrome_executable(getattr(args, "chrome_path", None))
        if args.command == "login":
            return run_login(
                feed_url=args.feed_url,
                chrome_path=chrome_path,
                storage_state_path=Path(args.storage_state).resolve(),
            )
        return run_fetch(
            tag_url=args.tag_url,
            output_dir=Path(args.output_dir).resolve(),
            manifest_path=Path(args.manifest).resolve(),
            storage_state_path=Path(args.storage_state).resolve(),
            chrome_path=chrome_path,
            max_details=args.max_details,
            stats_only=args.stats_only,
        )
    except KeyboardInterrupt:
        print("用户中断。")
        return 130
    except Exception as exc:
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
