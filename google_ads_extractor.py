import os
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from urllib.parse import urlparse

# 보안 & 환경변수 세팅
load_dotenv(r"c:\Users\user\OneDrive\Desktop\에이전트프로젝트\뉴스레터\.env")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

def get_hidden_landing_urls_via_dorking(keyword):
    """
    네이버 파워링크 마스터 서버 직접 타격(Native Scraping) + 구글 모바일 광고 타격(SerpApi)
    기존 1페이지만 긁던 한계를 돌파하여 최대 50개의 랜딩페이지를 싹쓸이합니다.
    """
    extracted_data = []
    seen_urls = set()
    
    # ❌ 오픈마켓, 종합몰 등 가짜 랜딩(단순 판매처) 필터링
    def is_valid_url(combined_str):
        """
        URL, 표시된 링크(displayed_link), 혹은 타이틀(title)을 모두 합쳐서
        강력한 블랙리스트 문자열이 하나라도 있으면 가차없이 폐기(False)
        """
        lower_str = combined_str.lower()
        
        # 대표적인 쓰레기/단순 마켓플레이스/포털/쇼핑몰 상세페이지 도메인 및 경로 모음
        blacklist = [
            "coupang", "gmarket", "auction", "11st", "ssg.com", 
            "smartstore.naver", "brand.naver", "naver.com", 
            "daum.net", "tistory.com", "blog", "news", 
            "youtube.com", "instagram.com", "facebook.com", "twitter.com",
            "/product/", "/category/", "/categories/", "/goods/", "/item/", "detail.html"
        ]
        
        for b in blacklist:
            if b in lower_str:
                return False
        return True

    # 1. 🇰🇷 네이버 파워링크 서버 심장부 다이렉트 타격 (모바일 환경 강제 적용)
    # 마케터 실무 탐색 패턴(혜택, 가격 등)을 덧붙여 다중 스캐닝 (무료이므로 무제한 타격 가능)
    naver_headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8'
    }
    
    # 찐 퍼포먼스 랜딩만 골라내는 '마법의 키워드' 조합
    power_suffixes = ["", "가격", "혜택", "이벤트", "할인", "효능", "부작용", "후기"]
    
    try:
        for suffix in power_suffixes:
            search_query = f"{keyword} {suffix}".strip()
            # 모바일 최적화 엔드포인트(m.ad.search.naver.com 및 where=m_ad) 타격
            url = f"https://m.ad.search.naver.com/search.naver?where=m_ad&query={search_query}&pagingIndex=1"
            resp = requests.get(url, headers=naver_headers, timeout=5)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            ad_links = soup.select(".lnk_tit")
            if not ad_links:
                continue # 이 조합에 광고가 없으면 다음 마법 단어로 넘어감
                
            for a_tag in ad_links:
                item = a_tag.find_parent("li")
                if not item:
                    continue
                    
                desc_tag = item.select_one(".ad_dsc")
                disp_tag = item.select_one(".url")
                
                title = a_tag.text.strip()
                href = a_tag.get("href", "")
                desc = desc_tag.text.strip() if desc_tag else ""
                disp = disp_tag.text.strip() if disp_tag else ""
                
                combined_str = f"{title} {disp} {desc}"
                if is_valid_url(combined_str):
                    # 마스킹된 href 대신, 화면에 노출된 찐 도메인(disp)을 우선 채택하여 리다이렉트 완전 회피
                    clean_url = "http://" + disp.replace("/", "") if disp else href
                    
                    if is_valid_url(clean_url) and clean_url not in seen_urls:
                        seen_urls.add(clean_url)
                        extracted_data.append({
                            "url": clean_url, 
                            "title": "[네이버 파워링크] " + title, 
                            "snippet": desc,
                            "source": "[Naver Native Server]"
                        })
    except Exception as e:
        print(f"🚨 Naver 다이렉트 타격 중 에러 발생: {e}")

    # 2. 🇺🇸 구글 메인 모바일 광고 타격 (SerpApi 활용)
    if SERPAPI_API_KEY:
        google_params = {
            "engine": "google",
            "q": f"{keyword} (가격 OR 할인 OR 혜택 OR 이벤트 OR 효능 OR 후기)", 
            "api_key": SERPAPI_API_KEY,
            "hl": "ko",
            "gl": "kr",
            "device": "mobile"
        }
        
        try:
            resp = requests.get("https://serpapi.com/search", params=google_params, timeout=10)
            g_resp = resp.json() # Renamed 'data' to 'g_resp' to match the provided snippet

            def add_unique_google_url(ad, source_name):
                link = ad.get("link", "")
                title = ad.get("title", "")
                snippet = ad.get("description", "") or ad.get("snippet", "")
                
                if link and is_valid_url(f"{title} {link} {snippet}"):
                    # 쿼리스트링(utm 등)을 날려버리고 순수 도메인+경로만 남겨 동일 페이지 중복 방지
                    parsed = urlparse(link)
                    base_link = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    
                    if is_valid_url(base_link) and base_link not in seen_urls:
                        seen_urls.add(base_link)
                        extracted_data.append({
                            "url": link,
                            "title": f"[{source_name}] {title}",
                            "snippet": snippet,
                            "source": f"[Google {source_name.split()[0]}]"
                        })

            # 구글 모바일 스폰서드 광고 파싱
            if "ads" in g_resp:
                for ad in g_resp["ads"]:
                    add_unique_google_url(ad, "모바일 스폰서광고")
                    
            # 자연 검색 결과(SEO) 파싱 (정보성 포스팅은 최대한 배제)
            if "organic_results" in g_resp:
                for res in g_resp["organic_results"]:
                    add_unique_google_url(res, "자연 검색 (SEO)")
        except Exception as e:
            pass

    return extracted_data

if __name__ == "__main__":
    import sys
    test_keyword = sys.argv[1] if len(sys.argv) > 1 else "다이어트"
    print(f"\n[{test_keyword}] 유료 광고 랜딩 URL 폭격 스캐닝 시작...\n")
    
    results = get_hidden_landing_urls_via_dorking(test_keyword)
    
    if not results:
        print("데이터를 찾지 못했습니다.")
    else:
        for idx, res in enumerate(results, 1):
            print(f"{idx}. {res['title']} | {res['url']}")
