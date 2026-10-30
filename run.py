"""PyInstaller entry point for the independent assistant."""

import sys

from boleme_live_control.app import main


if __name__ == "__main__":
    if "--smoke-browser" in sys.argv:
        try:
            from playwright.sync_api import sync_playwright
            from boleme_live_control.browser_runtime import prepare_browser_runtime

            prepare_browser_runtime()
            with sync_playwright() as playwright:
                for channel in ("msedge", "chrome", None):
                    try:
                        options = {"channel": channel} if channel else {}
                        browser = playwright.chromium.launch(headless=True, **options)
                        try:
                            browser.new_page().goto("about:blank")
                        finally:
                            browser.close()
                        break
                    except Exception:
                        continue
                else:
                    sys.exit(1)
        except Exception:
            sys.exit(1)
    else:
        main()
