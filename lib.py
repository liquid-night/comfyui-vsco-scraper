import json
import os
import platform
import random
import string
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import torch
from PIL import Image

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

    print("[VSCO] playwright not installed. Run: pip install playwright && playwright install chromium")


def _find_chrome():
    system = platform.system()

    if system == "Windows":
        for p in [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]:
            if Path(p).exists():
                return p
    elif system == "Darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    else:
        for p in ["/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium"]:
            if Path(p).exists():
                return p

    return "google-chrome"


CHROME_EXE = os.environ.get("CHROME_EXE") or _find_chrome()
CHROME_PROFILE = str(Path(tempfile.gettempdir()) / "chrome-debug-vsco")
CHROME_PORT = int(os.environ.get("CHROME_PORT", 9222))
SESSION_FLAG = Path(CHROME_PROFILE) / "vsco_session_ok"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _unique_path(path):
    if not path.exists():
        return path

    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))

    return path.with_name(f"{path.stem}_{suffix}{path.suffix}")


def _is_downloaded(output_dir, media_id):
    return bool(list(output_dir.glob(f"{media_id}.*")))


def _get_page(browser):
    context = browser.contexts[0] if browser.contexts else browser.new_context()

    return context.pages[0] if context.pages else context.new_page()


def _close_chrome():
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["pkill", "-f", f"--remote-debugging-port={CHROME_PORT}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_chrome():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{CHROME_PORT}/json", timeout=1)
        return
    except Exception:
        pass

    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["pkill", "-f", "chrome"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

    for lock in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        try:
            (Path(CHROME_PROFILE) / lock).unlink(missing_ok=True)
        except Exception:
            pass

    args = [
        CHROME_EXE,
        f"--remote-debugging-port={CHROME_PORT}",
        f"--user-data-dir={CHROME_PROFILE}",
        "--log-level=3",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1280,900",
    ]

    if platform.system() == "Linux":
        args += ["--no-sandbox", "--disable-dbus", "--use-gl=swiftshader"]

    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("Launching Chrome", end="", flush=True)

    for _ in range(40):
        time.sleep(0.5)

        print(".", end="", flush=True)

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{CHROME_PORT}/json", timeout=1)

            print(" ready.")

            return
        except Exception:
            pass

    print()

    raise RuntimeError("Chrome didn't start — check CHROME_EXE or set it via the CHROME_EXE env variable.")


def collect_all_media(page, username, max_images=0):
    media_items = []
    seen_ids = set()
    captured = []

    def on_response(response):
        url = response.url

        if ("im.vsco.co" in url or "img.vsco.co" in url) and response.ok:
            captured.append(response)

            return

        if "vsco.co/api" not in url or "medias" not in url:
            return

        try:
            data = json.loads(response.text().replace('":undefined', '":null'))
        except Exception:
            return

        for item in data.get("media", []):
            media_type = item.get("type", "image")
            media = item.get("image") if media_type != "video" else item.get("video")

            if not media:
                continue

            item_id = media.get("_id") or media.get("id")

            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                media["_type"] = media_type
                media_items.append(media)

    page.on("response", on_response)

    if SESSION_FLAG.exists():
        page.goto(f"https://vsco.co/{username}/gallery", wait_until="domcontentloaded", timeout=60000)

        print("Waiting for gallery", end="", flush=True)

        for _ in range(40):
            if media_items:
                break
            page.wait_for_timeout(500)

            print(".", end="", flush=True)

        print()

        if not media_items:
            SESSION_FLAG.unlink(missing_ok=True)

            print("Session expired, falling back to manual navigation.")

    if not media_items:
        print()
        print(f"Open Chrome and navigate to https://vsco.co/{username}/gallery")
        print("Scroll until photos appear, then come back here.")
        print()
        print("Waiting", end="", flush=True)

        for _ in range(300):
            if media_items:
                break

            page.wait_for_timeout(500)

            print(".", end="", flush=True)

        print()

        if media_items:
            print("Waiting for page to settle...", end="", flush=True)

            page.wait_for_timeout(5000)

            print(" done.")

        if not media_items:
            return [], {}

    SESSION_FLAG.touch()

    try:
        btn = page.locator("grain-button:has-text('Load more')").first

        if btn.is_visible(timeout=3000):
            btn.click()
            page.wait_for_timeout(2000)
    except Exception:
        pass

    prev_count = -1
    stall = 0

    while stall < 5:
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(1500)

        if len(media_items) == prev_count:
            stall += 1
        else:
            stall = 0

        prev_count = len(media_items)

        print(f"\r{len(media_items)} items found...", end="", flush=True)

        if max_images > 0 and len(media_items) >= max_images:
            break

    print()

    prefetched = {}

    for resp in captured:
        try:
            body = resp.body()

            if not body:
                continue

            parts = urlparse(resp.url).path.strip("/").split("/")

            if len(parts) >= 2:
                prefetched[parts[-2]] = (body, parts[-1].split("?")[0])
        except Exception:
            pass

    return media_items, prefetched


def fetch_post(media_id, output_dir, page, username):
    responses = []

    def on_resp(response):
        if ("im.vsco.co" in response.url or "img.vsco.co" in response.url) and response.ok:
            responses.append(response)

    page.on("response", on_resp)

    try:
        page.goto(f"https://vsco.co/{username}/media/{media_id}", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        for resp in responses:
            try:
                body = resp.body()

                if not body:
                    continue

                ext = Path(urlparse(resp.url).path).suffix or ".jpg"
                _unique_path(output_dir / f"{media_id}{ext}").write_bytes(body)

                return True
            except Exception:
                pass
    except Exception as exc:
        print(f"\nwarn {media_id}: {exc}")
    finally:
        page.remove_listener("response", on_resp)

    return False


def download_item(item, output_dir, prefetched, page, username, videos):
    is_video = item.get("_type") == "video" or item.get("is_video", False)
    media_id = str(item.get("_id") or item.get("id") or "unknown")

    if is_video:
        if not videos or _is_downloaded(output_dir, media_id):
            return "skipped"

        return "ok" if fetch_post(media_id, output_dir, page, username) else "failed"

    if _is_downloaded(output_dir, media_id):
        return "skipped"

    if media_id in prefetched:
        body, filename = prefetched[media_id]
        ext = Path(filename).suffix or ".jpg"

        _unique_path(output_dir / f"{media_id}{ext}").write_bytes(body)

        return "ok"

    return "ok" if fetch_post(media_id, output_dir, page, username) else "failed"


def run_playwright(username, out, include_videos, max_images=0, on_progress=None):
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CHROME_PORT}")
        page = _get_page(browser)
        media_items, prefetched = collect_all_media(page, username, max_images)

        if not media_items:
            raise ValueError(f"No media found for '{username}'.")

        if max_images > 0:
            media_items = media_items[:max_images]

        total = len(media_items)

        print(f"{total} items found, {len(prefetched)} prefetched. Downloading...")

        failed = []
        completed = downloaded = skipped = 0

        for item in media_items:
            result = download_item(item, out, prefetched, page, username, include_videos)
            completed += 1

            if result == "ok":
                downloaded += 1
            elif result == "skipped":
                skipped += 1
            else:
                failed.append(item)

            if on_progress:
                on_progress(completed, total)

        for attempt in range(1, 4):
            if not failed:
                break

            print(f"Retrying {len(failed)} failed items (attempt {attempt}/3)...")

            still_failed = []

            for item in failed:
                result = download_item(item, out, prefetched, page, username, include_videos)
                
                if result == "ok":
                    downloaded += 1
                else:
                    still_failed.append(item)

            failed = still_failed

    print(f"Done. {downloaded} downloaded, {skipped} skipped, {len(failed)} failed.")

    _close_chrome()


def load_image_tensor(path):
    img = Image.open(path).convert("RGB")

    return torch.from_numpy(np.array(img, dtype=np.float32) / 255.0)
