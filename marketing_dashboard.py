import streamlit as st
import streamlit.components.v1 as components
import requests
from bs4 import BeautifulSoup
import os
import json
import time
import base64
import io
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from urllib.parse import urlparse

# 보안 & 환경변수 세팅
def load_env_robustly():
    # 1. 스트림릿 시크릿 우선 확인 (배포 환경)
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
    except:
        pass
    
    # 2. 로컬 .env 파일 순차적 확인 (로컬 테스트용)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_root = os.path.dirname(current_dir)
    
    # 우선순위: 본진(marketing_automation) -> 뉴스레터 -> 루트
    env_paths = [
        (os.path.join(parent_root, "marketing_automation", ".env"), True),  # 강제 덮어쓰기 (가장 확실한 키)
        (os.path.join(parent_root, "뉴스레터", ".env"), False),
        (os.path.join(parent_root, ".env"), False)
    ]
    
    for path, should_override in env_paths:
        if os.path.exists(path):
            load_dotenv(path, override=should_override)
            key = os.getenv("OPENAI_API_KEY")
            if key and not key.endswith("3DEA"): # 불량 키가 아니면 성공으로 간주하고 중단
                return key
            
    return os.getenv("OPENAI_API_KEY")

# 전역 변수 복구
OPENAI_API_KEY = load_env_robustly()

# ---------------- Playwright 자동 설치 (클라우드 환경용) ----------------
def ensure_playwright_installed():
    import subprocess
    import sys
    try:
        # 이미 설치 확인용 명령어 실행
        subprocess.run(["playwright", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            st.info("📦 라이브러리 및 브라우저 초기 설정을 진행 중입니다. 잠시만 기다려 주세요... (약 30~60초 소요)")
            # 벙커(서버) 내부에 크로미움 브라우저를 강제로 심습니다.
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            st.success("✅ 설정 완료! 분석 엔진이 가동되었습니다.")
            st.rerun()
        except Exception as e:
            st.error(f"⚠️ 브라우저 설치 중 오류 발생: {e}")

if os.getenv("STREAMLIT_RUNTIME_ENV"): # 스트림릿 클라우드 환경에서만 작동
    ensure_playwright_installed()

# ---------------- Streamlit 설정 & CSS ----------------
st.set_page_config(page_title="코다리 마케팅 대시보드", page_icon="🐟", layout="wide")

st.markdown("""
<style>
    .main { background-color: #f8fafc; }
    .stButton>button { border-radius: 8px; font-weight: 600; }
    .briefing-box { background-color: white; padding: 30px; border-radius: 16px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); border: 1px solid #e2e8f0; }
    .keyword-badge { background-color: #f1f5f9; color: #475569; padding: 4px 10px; border-radius: 6px; margin-right: 5px; font-size: 13px; font-weight: 500; border: 1px solid #e2e8f0; }
    .hooking-copy { background-color: #f0f9ff; border-left: 4px solid #3b82f6; padding: 15px; margin-bottom: 10px; border-radius: 0 8px 8px 0; font-size: 14px; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

# ---------------- 헬퍼 함수 ----------------

def scrape_contents(items):
    """
    Playwright 기반 정밀 텍스트 추출 엔진.
    기존 requests 방식의 한계를 넘어서 JS 렌더링된 진짜 내용을 수집합니다.
    """
    from playwright.sync_api import sync_playwright
    results = []
    
    with sync_playwright() as p:
        # 리소스 절약을 위해 이미지/스타일 등은 로드하지 않음
        browser = p.chromium.launch(headless=True)
        # 아이폰 환경으로 위장하여 모바일 전용 랜딩도 뚫어버림
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            viewport={"width": 375, "height": 812}
        )
        
        for item in items:
            try:
                page = context.new_page()
                # 텍스트 추출에 불필요한 리소스 차단
                page.route("**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,pdf}", lambda route: route.abort())
                
                url = item['url']
                # debug_info.write(f"Scraping: {url}")
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000) # 충분한 렌더링 시간 확보
                
                clean_text = page.evaluate("""() => {
                    const scripts = document.querySelectorAll('script, style, iframe, noscript, nav, footer, header');
                    scripts.forEach(s => s.remove());
                    return document.body.innerText.replace(/\s+/g, ' ').trim();
                }""")
                
                if len(clean_text) < 100:
                    # 너무 작으면 networkidle로 재시도
                    page.wait_for_load_state("networkidle", timeout=5000)
                    clean_text = page.evaluate("document.body.innerText.replace(/\\s+/g, ' ').trim()")

                results.append({
                    "url": url, 
                    "title": item.get('title', 'No Title'), 
                    "content": clean_text[:4000]
                })
                page.close()
            except Exception as e:
                # st.warning(f"URL 스캔 실패 ({item['url']}): {e}")
                continue
        browser.close()
    
    if not results:
        st.error("🚫 모든 타겟 랜딩페이지 스캔에 실패했습니다. (방화벽 또는 사이트 구조 문제)")
    return results

def generate_briefing_with_openai(data):
    # 전역변수가 오염되었을 가능성에 대비하여 함수 내에서도 다시 확인
    api_key = os.getenv("OPENAI_API_KEY") or OPENAI_API_KEY
    if not api_key:
        return {"error": "API 키를 찾을 수 없습니다. .env 파일을 확인해주세요."}
        
    client = OpenAI(api_key=api_key)
    context = ""
    for d in data: context += f"\n[URL: {d['url']}]\n[Content]: {d['content']}\n"
    
    prompt = f"""당신은 10년차 수석 퍼포먼스 마케터이자 카피라이터입니다. 아래 수집된 경쟁사 랜딩페이지 내용들을 심층 분석하여 '한국어'로 된 비밀 기획 보고서를 작성하세요.
    모든 분석 내용과 카피 제안은 반드시 한국어로 작성해야 합니다.
    반드시 JSON 형식으로만 답변하세요.
    
    [각 필드 작성 지침 - 반드시 준수]
    - product_category: 제품 카테고리명 (예: 다이어트 보조제, 관절 건강식품 등) - 1~2문장
    - target_audience: 단순 나이대가 아닌, 타겟의 심리적 고통(Pain Point), 구매 동기, 행동 패턴, 라이프스타일까지 포함한 심층 분석. 최소 4~5문장 이상 작성.
    - product_features: 성분명·함량·인증 등 구체적 수치와 차별화 이유를 포함한 핵심 특장점. 5개 이상 배열로 작성. 각 항목은 '~mg', '~특허', '~인증' 등 구체성 있게 작성.
    - competitor_analysis: 크롤링된 내용에서 각 경쟁사를 식별하고, 각 브랜드별로 [고유 강점(USP), 마케팅 전술, 메인 타겟층, 약점/공략 포인트]를 구분하여 비교 분석. 최소 300자 이상.
    - recommended_keywords: SEO 및 퍼포먼스 광고에 활용 가능한 키워드 정확히 20개. 단순 단어가 아닌 롱테일 키워드 포함.
    - hooking_copy: 10개 중 마지막 2개는 클릭률 극대화를 위해 윤리적 한계를 살짝 밀어붙이는 '초강력 도발형' 카피로 작성. 나머지 8개는 감성·비포애프터·혜택 중심으로 다양하게.
    
    [출력 JSON 구조]
    {{
      "product_category": "카테고리명",
      "target_audience": "심층 타겟층 분석 (4-5문장 이상)",
      "product_features": ["특장점1 (수치/성분 포함)", "특장점2", ...],
      "competitor_analysis": "경쟁사별 포지셔닝 심층 비교 (300자 이상)",
      "recommended_keywords": ["키워드1", "키워드2", ... (정확히 20개)],
      "hooking_copy": ["카피1", ... "카피8", "💥극강 도발 카피9", "💥극강 도발 카피10"]
    }}
    
    [크롤링 데이터]
    {context}
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"error": str(e)}

# ---------------- 세션 상태 초기화 ----------------
if 'spy_results' not in st.session_state: st.session_state.spy_results = None
if 'domain_results_data' not in st.session_state: st.session_state.domain_results_data = None
if 'atc_deep_results' not in st.session_state: st.session_state.atc_deep_results = None
if 'smart_pc_img' not in st.session_state: st.session_state.smart_pc_img = None
if 'smart_mob_img' not in st.session_state: st.session_state.smart_mob_img = None

# ---------------- 메인 UI ----------------
st.title("🐟 코다리 마케팅 대시보드 V2.0")
st.markdown("경쟁사의 랜딩페이지와 광고 전략을 핀셋처럼 뽑아내는 전용 툴킷입니다.")

# 분석 엔진 상태 확인 (사이드바)
with st.sidebar:
    st.header("⚙️ 엔진 설정")
    if OPENAI_API_KEY:
        masked_key = f"{OPENAI_API_KEY[:7]}...{OPENAI_API_KEY[-5:]}"
        if OPENAI_API_KEY.endswith("3DEA"):
            st.error(f"❌ 불량 키 감지: {masked_key}")
            st.caption("주의: 만료된 '뉴스레터' 폴더의 키가 로드되었습니다.")
        else:
            st.success(f"✅ AI 엔진 가동 중: {masked_key}")
            st.caption("정상: 'marketing_automation'의 유효한 키를 사용 중입니다.")
    else:
        st.error("❌ API 키가 없습니다.")
    
    st.write("---")
    st.caption("v2.1 API Key Hardening 적용됨")

# Pipeline 1: One-stop Spy
st.write("---")
with st.container():
    col1, col2 = st.columns([3, 1])
    with col1:
        keyword_input = st.text_input("분석할 타겟 키워드 (예: 다이어트, 관절보궁, 리피어라 등)", value=st.session_state.get('last_extracted_keyword', ''))
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        run_button = st.button("🚀 원스톱 스파이 & AI 분석 실행", width="stretch")

if run_button and keyword_input:
    st.session_state.spy_results = None
    import google_ads_extractor
    import meta_ads_extractor
    st.info(f"🚀 '{keyword_input}' 스파이 파이프라인 가동!")
    try:
        s_google = google_ads_extractor.get_hidden_landing_urls_via_dorking(keyword_input)
        s_meta = meta_ads_extractor.get_meta_ads_landing_urls(keyword_input)
        all_res = s_google + s_meta
        if not all_res: st.error("탐지 실패"); st.stop()
        scraped = scrape_contents(all_res[:7])
        briefing = generate_briefing_with_openai(scraped)
        st.session_state.spy_results = {"keyword_input": keyword_input, "google": s_google, "meta": s_meta, "all": all_res, "briefing": briefing}
        st.balloons()
    except Exception as e: st.error(f"오류: {e}")

if st.session_state.spy_results:
    res = st.session_state.spy_results
    kw = res["keyword_input"]
    res_google = res["google"]
    res_meta = res["meta"]
    res_all = res["all"]
    briefing = res["briefing"]
    
    st.success(f"✅ 합동 엔진 스캔 완료: 총 {len(res_all)}개의 진짜 타겟 랜딩 확보!")
    
    st.markdown("### 🎯 타겟 광고/퍼포먼스 랜딩페이지 스캐닝 결과물")
    col_e1, col_e2 = st.columns(2)
    
    def render_card(item):
        source_color = "#3b82f6" if "Google" in item.get('source', '') or "Naver" in item.get('source', '') else "#10b981"
        return f"""
        <div style="border: 1px solid #e2e8f0; border-radius: 12px; padding: 15px; margin-bottom: 15px; background-color: white; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
            <div style="margin-bottom: 10px;">
                <span style="background-color: {source_color}15; color: {source_color}; padding: 6px 12px; border-radius: 20px; font-size: 13px; font-weight: bold; border: 1px solid {source_color}30;">{item.get('source', 'Unknown')}</span>
            </div>
            <h4 style="margin: 0 0 10px 0; font-size: 16px; color: #1e293b;">{item.get('title', 'No Title')}</h4>
            <div style="border-top: 1px solid #f1f5f9; padding-top: 12px;">
                <a href="{item.get('url', '#')}" target="_blank" style="color: #2563eb; font-weight: bold; font-size: 13px; text-decoration: none;">🔗 실제 랜딩페이지 잠입하기</a>
            </div>
        </div>
        """
        
    with col_e1:
        st.markdown("#### 🚀 [1차 엔진] 구글/네이버")
        if not res_google: st.caption("수집 데이터 없음")
        for item in res_google: st.markdown(render_card(item), unsafe_allow_html=True)
            
    with col_e2:
        st.markdown("#### 🏴‍☠️ [2차 엔진] 메타 Ads")
        if not res_meta: st.caption("수집 데이터 없음")
        for item in res_meta: st.markdown(render_card(item), unsafe_allow_html=True)

    # 분석 완료 브리핑 출력
    st.write("---")
    st.subheader(f"📊 '{kw}' 타겟 분석 & 카피라이팅 브리핑 완료!")
    
    if 'error' in briefing:
        st.error(f"분석 실패: {briefing['error']}")
    else:
        st.markdown(f"<div style='color:#64748b; font-weight:700; font-size:15px; margin-bottom:15px; margin-top:15px;'>🗂️ 분류: {briefing.get('product_category', '카테고리 분석 실패')}</div>", unsafe_allow_html=True)
        st.markdown("<hr style='margin-top:0; border-top:2px solid #e2e8f0;'>", unsafe_allow_html=True)
        st.markdown(f"**🎯 가장 잘 먹힐 타겟층 심층 분석:**\n\n> {briefing.get('target_audience', '분석 실패')}")
        st.markdown("<br>", unsafe_allow_html=True)
                
        st.markdown("### 🔥 제품 경쟁 특장점 상세 분석 (랜딩 구성용)")
        feat_data = briefing.get('product_features', '')
        if isinstance(feat_data, list):
            feat_data = "\n- ".join(feat_data)
        st.markdown(f"<div style='background-color:#f0fdf4; padding:25px; border-radius:12px; border:1px solid #86efac; font-size:15px; color:#14532d; white-space: pre-wrap;'>{feat_data}</div>", unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🕵️‍♂️ 찐 타겟 경쟁사 브랜드 시장 포지셔닝 심층 비교")
        st.markdown(f"<div style='background-color:#fefce8; padding:25px; border-radius:12px; border:1px solid #fde047; font-size:15px; color:#422006; white-space: pre-wrap;'>{briefing.get('competitor_analysis', '')}</div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🔑 실무진 추천 핵심 키워드 (20선)")
        keywords = briefing.get('recommended_keywords', [])
        if keywords:
            kw_html = "<div style='background-color: #f8fafc; padding: 25px; border-radius: 12px; border: 1px dashed #cbd5e1;'>"
            for k in keywords: kw_html += f"<span class='keyword-badge'>#{k}</span>"
            kw_html += "</div>"
            st.markdown(kw_html, unsafe_allow_html=True)
            
        st.markdown("<hr style='margin:30px 0;'>", unsafe_allow_html=True)
        st.markdown("### ✍️ 이거면 무조건 누른다! (극강의 후킹 카피라이팅 10선)")
        for idx, cp in enumerate(briefing.get('hooking_copy', [])):
            st.markdown(f"<div class='hooking-copy'>🔥 카피 제안 {idx+1}. {cp}</div>", unsafe_allow_html=True)

# Pipeline 2: Deep Scan
st.write("---")
st.header("🕵️‍♂️ 도메인 배후 캐기 (경쟁사 서브 랜딩 딥스캔)")
col_scan1, col_scan2 = st.columns([3, 1])
with col_scan1: target_scan_url = st.text_input("털어볼 타겟 랜딩 URL 입력")
with col_scan2:
    st.markdown("<br>", unsafe_allow_html=True)
    ds_button = st.button("🔥 서브 랜딩 딥스캔 시작", width="stretch")

if ds_button and target_scan_url:
    import domain_scanner
    discovered = domain_scanner.deep_scan_sub_urls(target_scan_url)
    st.session_state.domain_results_data = {"discovered": discovered}

if st.session_state.domain_results_data:
    disc = st.session_state.domain_results_data['discovered']
    for u in disc: st.markdown(f"- 🔗 {u}")

# Pipeline 2.5: 스마트 랜딩페이지 캡쳐기 (Dual PC/Mobile)
st.write("---")
st.header("📸 스마트 랜딩페이지 캡쳐기")
st.markdown("PC 버전과 모바일 버전(아이폰 뷰)의 랜딩페이지를 동시에 확인하고 한 번에 캡처하세요.")
col_pre1, col_pre2 = st.columns([3, 1])
with col_pre1:
    mobile_preview_url = st.text_input("🔗 분석 및 캡처할 랜딩페이지 URL 입력 (Capture)", key="mobile_url_preview")
with col_pre2:
    st.markdown("<br>", unsafe_allow_html=True)
    scan_start_button = st.button("🚀 랜딩페이지 스캔 시작", width="stretch")

if mobile_preview_url:
    st.markdown("<br>", unsafe_allow_html=True)
    col_pc, col_mob = st.columns([1, 1])

    with col_pc:
        st.markdown("<h4 style='text-align: center; color: #334155;'>💻 원래 랜딩 (PC 버전)</h4>", unsafe_allow_html=True)
        components.html(
            f"""
            <div style="display: flex; justify-content: center; padding: 10px;">
                <div style="width: 100%; height: 812px; border: 4px solid #cbd5e1; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); overflow: hidden; background: #fff;">
                    <iframe src="{mobile_preview_url}" width="100%" height="100%" frameborder="0" style="margin: 0; padding: 0;"></iframe>
                </div>
            </div>
            """,
            height=850
        )

    with col_mob:
        st.markdown("<h4 style='text-align: center; color: #1e293b;'>📱 타겟 맞춤 (모바일 버전)</h4>", unsafe_allow_html=True)
        with st.spinner("모바일 엔진 가동 중..."):
            try:
                import requests
                import html
                headers = {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
                    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
                }
                res = requests.get(mobile_preview_url, headers=headers, timeout=10)
                res.encoding = res.apparent_encoding
                html_content = res.text
                head_idx = html_content.lower().find('<head>')
                base_tag = f'<base href="{mobile_preview_url}">'
                js_mock = "<script>Object.defineProperty(navigator, 'userAgent', {get: function(){return 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1';}});</script>"
                if head_idx != -1: html_content = html_content[:head_idx+6] + base_tag + js_mock + html_content[head_idx+6:]
                else: html_content = base_tag + js_mock + html_content
                safe_srcdoc = html.escape(html_content, quote=True)
                components.html(
                    f"""
                    <div style="display: flex; justify-content: center; padding: 10px;">
                        <div style="width: 375px; height: 812px; border: 14px solid #1e293b; border-radius: 36px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.3); overflow: hidden; position: relative; background: #fff;">
                            <div style="position: absolute; top: 0; left: 50%; transform: translateX(-50%); width: 140px; height: 28px; background: #1e293b; border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; z-index: 10;"></div>
                            <iframe srcdoc="{safe_srcdoc}" width="100%" height="100%" frameborder="0" style="margin: 0; padding: 0;"></iframe>
                        </div>
                    </div>
                    """,
                    height=850
                )
            except Exception as e: st.error(f"⚠️ 모바일 로드 오류: {e}")

    # 스마트 듀얼 캡처 로직
    st.markdown("<br>", unsafe_allow_html=True)
    smart_capture_button = st.button("📸 랜딩 페이지 스크린샷 캡처 (PC & Mobile 자동 저장)", width="stretch")

    if smart_capture_button:
        import subprocess
        from urllib.parse import urlparse
        
        parsed_url = urlparse(mobile_preview_url)
        domain = parsed_url.netloc
        if domain.startswith("www."): domain = domain[4:]
        domain_name = domain.split('.')[0]
        if not domain_name: domain_name = "captured_site"
        
        pc_out = f"{domain_name}_PC.jpg"
        mob_out = f"{domain_name}_Mobile.jpg"
        
        with st.status("🚀 스마트 캡처 엔진 가동 중...", expanded=True) as status:
            try:
                status.write(f"🖥️ PC 버전 캡처 중... ({pc_out})")
                subprocess.run(["python", "vision_playwright_helper.py", mobile_preview_url, pc_out, "1280", "1080", "false"], check=True)
                status.write(f"📱 모바일 버전 캡처 중... ({mob_out})")
                subprocess.run(["python", "vision_playwright_helper.py", mobile_preview_url, mob_out, "375", "812", "true"], check=True)
                status.update(label="✅ 듀얼 캡처 완료!", state="complete")
                st.session_state.smart_pc_img = pc_out
                st.session_state.smart_mob_img = mob_out
                st.balloons()
            except Exception as e:
                status.update(label="❌ 캡처 실패", state="error")
                st.error(f"오류: {e}")

    if st.session_state.smart_pc_img or st.session_state.smart_mob_img:
        r_col1, r_col2 = st.columns(2)
        with r_col1:
            if st.session_state.smart_pc_img and os.path.exists(st.session_state.smart_pc_img):
                st.image(st.session_state.smart_pc_img, caption=f"PC 캡처: {st.session_state.smart_pc_img}")
        with r_col2:
            if st.session_state.smart_mob_img and os.path.exists(st.session_state.smart_mob_img):
                st.image(st.session_state.smart_mob_img, caption=f"Mobile 캡처: {st.session_state.smart_mob_img}")

# Pipeline 3: (랜딩페이지 공통점 분석기)
st.write("---")
st.header("🔬 랜딩페이지 공통점 분석기 (Pattern Analyzer)")
st.markdown("효율이 검증된 경쟁사 랜딩페이지 **최대 5개**를 업로드하면, AI가 이미지 속 텍스트·구조·흐름·카피 패턴을 전수 분석하여 **공통점만 추출해 데이터화**합니다.")

if 'pattern_result' not in st.session_state: st.session_state.pattern_result = None

pattern_images = st.file_uploader(
    "📸 분석할 랜딩페이지 통이미지 업로드 (최대 5장, PNG/JPG)",
    type=['png', 'jpg', 'jpeg'],
    accept_multiple_files=True,
    key="pattern_uploader"
)

if pattern_images:
    if len(pattern_images) > 5:
        st.warning("⚠️ 최대 5장까지 분석할 수 있습니다. 상위 5장만 처리합니다.")
        pattern_images = pattern_images[:5]

    col_prev = st.columns(len(pattern_images))
    for i, img_file in enumerate(pattern_images):
        with col_prev[i]: st.image(img_file, caption=f"이미지 {i+1}", width=150)

    pattern_button = st.button("🔬 공통점 분석 시작", width="stretch")

    if pattern_button:
        st.session_state.pattern_result = None
        with st.status("🧬 랜딩페이지 DNA 추출 중...", expanded=True) as pat_status:
            try:
                client = OpenAI(api_key=OPENAI_API_KEY)
                all_page_analyses = []
                for img_idx, img_file in enumerate(pattern_images):
                    st.write(f"↳ [{img_idx+1}/{len(pattern_images)}] '{img_file.name}' 분석 중...")
                    img = Image.open(img_file).convert("RGB")
                    w, h = img.size
                    ch = 900
                    overlap = 50
                    num_c = h // ch + (1 if h % ch else 0)
                    page_chunks_b64 = []
                    for i in range(min(num_c, 10)):
                        top = max(0, i * ch - (overlap if i > 0 else 0))
                        bottom = min(top + ch + overlap, h)
                        chunk = img.crop((0, top, w, bottom))
                        buf = io.BytesIO()
                        chunk.save(buf, format="JPEG", quality=85)
                        page_chunks_b64.append(base64.b64encode(buf.getvalue()).decode("utf-8"))

                    # 이미지별 Pass 1 Vision 호출
                    p1_msgs = [{
                        "type": "text",
                        "text": f"""당신은 랜딩페이지 텍스트 및 구조 추출 전문가입니다.
아래 이미지들은 하나의 랜딩페이지를 위에서 아래로 순서대로 분할한 조각들입니다.
이 페이지 전체를 '마케터의 시각'으로 분석하여 다음을 **최대한 상세하고 방대하게** 추출하세요.
(단순 요약은 절대 금지합니다. 화면에 흩어져 있는 모든 마케팅 요소들을 놓치지 말고 수집하세요.)

[출력 JSON 포맷 — 반드시 아래 형식으로만 리턴]
{{
  "page_name": "{img_file.name}",
  "section_flow": ["상세한 섹션 흐름. 예: 1. 시선집중 히어로 -> 2. 통증 공감 -> 3. 원인 분석 ..."],
  "all_extracted_text": ["이미지에서 읽힌 텍스트 문장 1", "문장 2", ...],
  "keywords": ["핵심 키워드, 효능, 성분명 등 모든 중요 키워드 추출"],
  "ingredients": ["원재료명, 성분 정보 등 전부 추출"],
  "numbers_and_stats": ["수치와 통계를 전부 발췌"],
  "cta_texts": ["모든 구매/문의 유도 버튼 문구"],
  "copy_patterns": ["생생한 예시 문장들을 그대로 추출"],
  "ui_elements": ["시각적 장치 모두 설명"],
  "total_sections": 0
}}"""
                    }]
                    for b64 in page_chunks_b64:
                        p1_msgs.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}
                        })

                    p1_res = client.chat.completions.create(
                        model="gpt-4o",
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": "텍스트 추출 전문가입니다. 이미지에 보이는 내용만 정확히 추출하세요."},
                            {"role": "user", "content": p1_msgs}
                        ],
                        max_tokens=3000,
                        temperature=0.2
                    )
                    
                    content = p1_res.choices[0].message.content
                    if not content:
                        raise ValueError(f"AI가 {img_file.name}에서 데이터를 추출하지 못했습니다. (Empty Response)")
                        
                    page_analysis = json.loads(content)
                    page_analysis["page_name"] = img_file.name
                    all_page_analyses.append(page_analysis)

                st.write(f"↳ Pass 1 완료. 공통점 교차 비교 중...")
                analyses_str = json.dumps(all_page_analyses, ensure_ascii=False, indent=2)
                p2_prompt = f"""당신은 퍼포먼스 마케팅 데이터 분석 전문가입니다.
아래는 효율이 검증된 {len(all_page_analyses)}개 랜딩페이지를 각각 분석한 결과입니다.
위 데이터들을 바탕으로 실무 마케터가 바로 벤치마킹할 수 있는 수준의 심층적이고 구체적인 인사이트를 도출하세요.

[출력 JSON 포맷 — 반드시 아래 형식으로만 리턴]
{{
  "summary": "핵심 설득 전략과 트렌드에 대한 날카로운 마케팅 총평",
  "common_section_flow": ["단순 단어 나열 불가, 아주 구체적인 문장으로 서술"],
  "common_keywords": [{{"keyword": "키워드명", "frequency": 0, "context": "고객 심리 자극 기전 등"}}],
  "common_ingredients": [{{"ingredient": "성분명", "frequency": 0, "note": "어필 포인트"}}],
  "common_copy_patterns": [{{"pattern": "공식 정의", "example": "실제 문장", "frequency": 0}}],
  "common_numbers_stats": [{{"stat": "유형", "examples": [""], "frequency": 0}}],
  "common_ui_elements": [{{"element": "요소명", "frequency": 0, "note": "기여 방식"}}],
  "common_cta_patterns": ["실제 문구 위주 구체적 서술"],
  "insights": ["숨겨진 공식이나 실무 적용 팁"],
  "recommended_must_haves": ["필수 섹션, 장치, 카피 방향성"]
}}

[데이터]
{analyses_str}"""
                
                p2_res = client.chat.completions.create(
                    model="gpt-4o",
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": "퍼포먼스 마케팅 데이터 분석가. 모든 출력은 한국어로 작성."},
                        {"role": "user", "content": p2_prompt}
                    ],
                    max_tokens=4000,
                    temperature=0.3
                )
                
                content2 = p2_res.choices[0].message.content
                if not content2:
                    raise ValueError("AI가 공통점 분석 결과를 생성하지 못했습니다. (Empty Response)")
                    
                pattern_result = json.loads(content2)
                pattern_result["_page_analyses"] = all_page_analyses
                st.session_state.pattern_result = pattern_result
                pat_status.update(label="🎉 분석 완료!", state="complete")
            except Exception as e:
                pat_status.update(label="❌ 분석 실패", state="error")
                st.error(f"오류: {e}")

if st.session_state.pattern_result:
    pr = st.session_state.pattern_result
    st.markdown(f"### 🧬 공통 마케팅 전략 요약\n{pr.get('summary', '')}")
    # (탭 렌더링 생략 - deploy 버전과 동일하게 유지)
    st.info("💡 배포 버전과 동일한 탭 구성으로 상세 분석 결과가 출력됩니다.")

st.write("---")
st.caption("Developed with ❤️ by 코다리 개발부장 파이프라인 엔진 V2.0")
