import os
import sys
import time
import asyncio
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

# 윈도우 Streamlit의 스레드 환경에서 Playwright/asyncio 서브프로세스 에러를 방지하기 위한 필수 설정
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

def get_meta_ads_landing_urls(keyword):
    """
    페이스북/인스타그램 광고 라이브러리를 가상 브라우저(Playwright)로 띄워
    현재 집행 중인 경쟁사 광고들의 외부 랜딩페이지 URL을 긁어오는 2차 엔진입니다.
    """
    extracted = []
    urls = set()
    seen_bases = set()
    
    # 제외할 쓸데없는 앱스토어 링크, 메타 자체 링크 및 자사몰 도메인 잡음 필터링
    # 추가로 일반 쇼핑몰 구매페이지(PDP)를 배제하기 위해 /product/, /category/ 등 추가
    blacklist = [
        "itunes.apple.com", "play.google.com", "instagram.com", "whatsapp.com", 
        "facebook.com", "fb.com", "smartstore.naver.com", "coupang.com", 
        "metastatus.com", "meta.com", "messenger.com", "about.meta.com",
        "/product/", "/category/", "/categories/", "/goods/", "/item/", "detail.html"
    ]
    
    def is_valid_url(link):
        lower_link = link.lower()
        if not lower_link.startswith("http"):
            return False
        for b in blacklist:
            if b in lower_link:
                return False
        return True

    with sync_playwright() as p:
        browser = None
        try:
            headless_mode = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
            browser = p.chromium.launch(headless=headless_mode, args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ko-KR",
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()
            
            suffixes = ["", "가격", "혜택", "단독", "할인", "이벤트"]
            for suffix in suffixes:
                search_query = f"{keyword} {suffix}".strip()
                url = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=KR&q={search_query}&search_type=keyword_unordered&media_type=all"
                
                try:
                    page.goto(url, timeout=30000)
                except Exception as e:
                    print(f"[{search_query}] 페이지 로드 실패: {e}")
                    continue
                
                # 메타 광고는 자바스크립트 렌더링이 느리므로 충분히 대기
                page.wait_for_timeout(4000)
                
                # 무한 스크롤 탑재 (Lazy Loading 대응)
                for _ in range(3):
                    page.mouse.wheel(0, 5000)
                    page.wait_for_timeout(1500)
                    
                # 카드 내 외부 링크 전부 적출 (진짜 랜딩페이지들)
                links = page.locator("a[href]").all()
                for link in links:
                    try:
                        href = link.get_attribute("href")
                        if not href:
                            continue
                            
                        real_url = ""
                        if "/l.php?u=" in href:
                            parsed = parse_qs(urlparse(href).query)
                            if "u" in parsed:
                                real_url = parsed["u"][0]
                        # 페이스북 관련 링크가 아닌 진짜 외부 도메인이면 수집
                        elif href.startswith("http") and "facebook.com" not in href and "instagram.com" not in href:
                            real_url = href
                            
                        if real_url and is_valid_url(real_url):
                            # utm 파라미터나 추적 코드를 날리고 도메인+주소로만 중복 체킹
                            parsed = urlparse(real_url)
                            base_url = f"{parsed.netloc}{parsed.path}"
                            if base_url not in seen_bases:
                                seen_bases.add(base_url)
                                urls.add(real_url)
                    except Exception:
                        continue
                        
        except Exception as e:
            print(f"Meta 스크래핑 에러: {e}")
        finally:
            if browser:
                browser.close()
            
    # 결과를 대시보드 호환 형식으로 변환
    for u in urls:
        extracted.append({
            "url": u,
            "title": "[Meta/인스타 광고 직접 랜딩]",
            "snippet": "페이스북/인스타그램 광고 카드에서 직접 추출된 아웃링크 페이지입니다.",
            "source": "[Meta Ads Library 스파이]"
        })
        
    return extracted

if __name__ == "__main__":
    kw = sys.argv[1] if len(sys.argv) > 1 else "다이어트"
    res = get_meta_ads_landing_urls(kw)
    for idx, r in enumerate(res, 1):
        print(f"{idx}. {r['url']}")
