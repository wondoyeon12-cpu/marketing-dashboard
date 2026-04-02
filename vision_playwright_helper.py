import sys
import time
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from PIL import Image

def main():
    if len(sys.argv) < 3:
        print("Usage: python vision_playwright_helper.py <url> <output_filename>")
        sys.exit(1)
        
    url = sys.argv[1]
    output_filename = sys.argv[2]
    try:
        with open("playwright_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.time()}] Started for URL: {url} | Target: {output_filename}\n")
            
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 1080})
            page = context.new_page()
            
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            # [NEW] Detect if the site is just an empty shell embedding a frame or iframe
            frame_url = page.evaluate("""() => {
                const frames = document.querySelectorAll('frame, iframe');
                for (let f of frames) {
                    // If it's the main or only frame taking up the screen, return its src
                    if (frames.length === 1 || f.name === 'mainFrame' || f.name === 'main' || parseInt(f.clientHeight) > 500) {
                        return f.src;
                    }
                }
                return null;
            }""")
            
            if frame_url and frame_url.startswith("http"):
                print(f"Detected wrapper frame/iframe. Navigating to actual content: {frame_url}")
                page.goto(frame_url, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                
            # 1. Scroll down using multiple methods to trigger lazy loading
            for _ in range(15):
                page.mouse.wheel(0, 2000)
                page.keyboard.press("PageDown")
                page.wait_for_timeout(300)

            # 2. Scroll back to top
            page.evaluate("window.scrollTo(0, 0)")
            page.keyboard.press("Home")
            page.wait_for_timeout(1000)
            
            # Wait for any last-minute rendering
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except:
                pass 
                
            # 3. Change fixed/sticky elements to absolute so they don't break viewport expansion
            # Also reset any harmful max-height or overflow hidden on body/html
            page.evaluate("""() => {
                document.body.style.overflow = 'visible';
                document.documentElement.style.overflow = 'visible';
                document.body.style.height = 'auto';
                document.documentElement.style.height = 'auto';
                
                const elements = document.querySelectorAll('*');
                for (const el of elements) {
                    const style = window.getComputedStyle(el);
                    if (style.position === 'fixed' || style.position === 'sticky') {
                        el.style.position = 'absolute';
                    }
                }
            }""")
            
            page.wait_for_timeout(1000)
            
            # 4. Find the absolute maximum scroll height in the page
            # 4. Find the absolute maximum scroll container and assign a unique ID
            target_id = page.evaluate("""() => {
                let maxScroll = 0;
                let targetEl = document.body;
                document.querySelectorAll('body, div, main, section, article, form').forEach((el) => {
                    if (el.scrollHeight > maxScroll && el.scrollHeight > 1500) {
                        maxScroll = el.scrollHeight;
                        targetEl = el;
                    }
                });
                
                // Assign a unique ID so playwright can find exactly this element
                const uniqueId = 'kodari-capture-target-' + Math.random().toString(36).substr(2, 9);
                targetEl.id = uniqueId;
                return uniqueId;
            }""")
            
            # 5. Final scroll to top before capturing ensuring we start from the top
            page.evaluate(f"document.getElementById('{target_id}').scrollTop = 0")
            page.wait_for_timeout(1000)
            
            # 6. Take screenshot using Playwright's locator to capture only the true container
            try:
                page.locator(f"#{target_id}").screenshot(path=output_filename, type='jpeg', quality=80)
            except Exception as e:
                print(f"Fallback to full_page screenshot due to: {e}")
                page.screenshot(path=output_filename, full_page=True, type='jpeg', quality=80)
            browser.close()
            
        # 통이미지 원본(full screenshot)을 그대로 사용하기 위해 분할 로직을 제거함
        print(f"SUCCESS 1")
        
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
