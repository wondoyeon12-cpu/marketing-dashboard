import streamlit as st
import streamlit.components.v1 as components
import sys
import requests
import concurrent.futures
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

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

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

def fetch_content(item):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        res = requests.get(item['url'], headers=headers, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['script', 'style']): s.decompose()
        return {"url": item['url'], "title": item.get('title', 'No Title'), "content": soup.get_text()[:4000]}
    except:
        return None

def scrape_contents(items):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
        future_to_item = {executor.submit(fetch_content, item): item for item in items}
        for future in concurrent.futures.as_completed(future_to_item):
            data = future.result()
            if data:
                results.append(data)
    return results

def generate_briefing_with_openai(data):
    client = OpenAI(api_key=OPENAI_API_KEY)
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
    - recommended_keywords: SEO 및 퍼포먼스 광고에 활용 가능한 키워드 정확히 50개. 단순 단어가 아닌 롱테일 키워드 포함.
    - hooking_copy: 10개 중 마지막 2개는 클릭률 극대화를 위해 윤리적 한계를 살짝 밀어붙이는 '초강력 도발형' 카피로 작성. 나머지 8개는 감성·비포애프터·혜택 중심으로 다양하게.
    
    [출력 JSON 구조]
    {{
      "product_category": "카테고리명",
      "target_audience": "심층 타겟층 분석 (4-5문장 이상)",
      "product_features": ["특장점1 (수치/성분 포함)", "특장점2", ...],
      "competitor_analysis": "경쟁사별 포지셔닝 심층 비교 (300자 이상)",
      "recommended_keywords": ["키워드1", "키워드2", ... (정확히 50개)],
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

# ---------------- Sidebar: 시스템 관리 ----------------
with st.sidebar.expander("⚙️ 시스템 관리 (시스템 설정)", expanded=False):
    st.info("앱 설치 후 또는 브라우저 에러 발생 시 한 번만 실행해 주세요.")
    if st.button("🌐 브라우저 엔진 자동 설치 (Playwright)", help="클라우드용 크롬 브라우저를 강제로 설치합니다."):
        with st.spinner("브라우저를 내려받는 중입니다... (약 1~2분 소요)"):
            import subprocess
            try:
                # sys.executable -m playwright install chromium
                res = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True)
                if res.returncode == 0:
                    st.success("✅ 브라우저 엔진 설치 완료!")
                    st.info(res.stdout)
                else:
                    st.error(f"❌ 설치 실패 (Code: {res.returncode})")
                    st.code(res.stderr)
            except Exception as e:
                st.error(f"🚀 설치 중 치명적 오류: {e}")

# ---------------- 메인 UI ----------------
st.title("🐟 코다리 마케팅 대시보드 V1.5")
st.markdown("경쟁사의 랜딩페이지와 광고 전략을 핀셋처럼 뽑아내는 전용 툴킷입니다.")

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
    import importlib
    import google_ads_extractor
    import meta_ads_extractor
    importlib.reload(google_ads_extractor)
    importlib.reload(meta_ads_extractor)
    
    st.info(f"🚀 '{keyword_input}' 스파이 파이프라인 가동!")
    
    with st.status("🔍 엔진별 합동 수색 진행 중...", expanded=True) as status:
        all_res = []
        try:
            st.write("↳ [전 엔진 동시 가동] 구글/네이버 & 메타 Ads 침투 중...")
            
            # 병렬로 엔진 실행
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_google = executor.submit(google_ads_extractor.get_hidden_landing_urls_via_dorking, keyword_input)
                future_meta = executor.submit(meta_ads_extractor.get_meta_ads_landing_urls, keyword_input)
                
                s_google = future_google.result()
                s_meta = future_meta.result()
                
            gn_count = len(s_google)
            meta_count = len(s_meta)
            st.write(f"   ✅ 네이버/구글 엔진: {gn_count}개 발견")
            st.write(f"   ✅ 메타 엔진: {meta_count}개 발견")
            
            all_res = s_google + s_meta
            
            if not all_res:
                status.update(label="❌ 탐지 결과 없음", state="error")
                st.error(f"'{keyword_input}' 키워드로 탐지된 광고 랜딩페이지가 없습니다. (블랙리스트 필터링 또는 검색 결과 없음)")
                st.stop()
            
            # 3. 데이터 분석
            st.write(f"↳ 총 {len(all_res)}개 랜딩 중 상위 7개 심층 분석 중...")
            scraped = scrape_contents(all_res[:7])
            briefing = generate_briefing_with_openai(scraped)
            
            st.session_state.spy_results = {
                "keyword_input": keyword_input, 
                "google": s_google, 
                "meta": s_meta, 
                "all": all_res, 
                "briefing": briefing
            }
            status.update(label="✅ 전 엔진 수색 및 분석 완료!", state="complete")
            st.balloons()
            
        except Exception as e:
            status.update(label="🚨 치명적 오류 발생", state="error")
            st.error(f"실행 중 오류가 발생했습니다: {e}")
            import traceback
            st.code(traceback.format_exc())

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
    st.markdown("### 🔑 실무진 추천 핵심 키워드 (50선)")
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

# Pipeline 3: 스마트 랜딩페이지 캡쳐기 (Dual PC/Mobile)
st.write("---")
st.header("📸 스마트 랜딩페이지 캡쳐기")
st.markdown("PC 버전과 모바일 버전(아이폰 뷰)의 랜딩페이지를 동시에 확인하고 한 번에 캡처하세요.")

if 'smart_pc_img' not in st.session_state: st.session_state.smart_pc_img = None
if 'smart_mob_img' not in st.session_state: st.session_state.smart_mob_img = None

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
        if not domain_name = "captured_site"
        
        pc_out = f"{domain_name}_PC.jpg"
        mob_out = f"{domain_name}_Mobile.jpg"
        
        with st.status("🚀 스마트 캡처 엔진 가동 중...", expanded=True) as status:
            try:
                # 스크립트 위치 절대화
                script_dir = os.path.dirname(os.path.abspath(__file__))
                helper_path = os.path.join(script_dir, "vision_playwright_helper.py")
                
                status.write(f"🖥️ PC 버전 캡처 중... ({pc_out})")
                subprocess.run([sys.executable, helper_path, mobile_preview_url, pc_out, "1280", "1080", "false"], check=True)
                status.write(f"📱 모바일 버전 캡처 중... ({mob_out})")
                subprocess.run([sys.executable, helper_path, mobile_preview_url, mob_out, "375", "812", "true"], check=True)
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

# ===============================
# ★ 6번 파이프라인 (랜딩페이지 공통점 분석기) 영역
# ===============================
st.write("---")
st.header("🔬 랜딩페이지 공통점 분석기 (Pattern Analyzer)")
st.markdown("효율이 검증된 경쟁사 랜딩페이지 **최대 5개**를 업로드하면, AI가 이미지 속 텍스트·구조·흐름·카피 패턴을 전수 분석하여 **공통점만 추출해 데이터화**합니다.")

# 세션 초기화
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
        with col_prev[i]:
            st.image(img_file, caption=f"이미지 {i+1}: {img_file.name}", width=150)

    pattern_button = st.button("🔬 공통점 분석 시작", width="stretch")

    if pattern_button:
        st.session_state.pattern_result = None
        with st.status("🧬 랜딩페이지 DNA 추출 중...", expanded=True) as pat_status:
            try:
                client = OpenAI(api_key=OPENAI_API_KEY)
                all_page_analyses = []  # 각 페이지별 텍스트 분석 결과

                # ── Pass 1: 이미지별 텍스트·구조 전수 추출 ──
                def analyze_image(img_file):
                    img = Image.open(img_file).convert("RGB")
                    w, h = img.size
                    ch = 900
                    overlap = 50
                    num_c = h // ch + (1 if h % ch else 0)

                    # 청크 생성 (최대 10장/이미지)
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
  "section_flow": ["상세한 섹션 흐름. 예: 1. 시선집중 히어로 (초특가 타임세일) -> 2. 통증 공감 (일반인의 비포 이미지) -> 3. 원인 분석 ... (최소 7단계 이상 구체적으로 묘사)"],
  "all_extracted_text": ["이미지에서 읽힌 텍스트 문장 1", "문장 2", ...],
  "keywords": ["핵심 키워드, 효능, 성분명, 타겟층 등 화면에 등장하는 모든 중요/서브 키워드를 최대한 많이 추출 (최소 20개~40개)"],
  "ingredients": ["원재료명, 주성분, 부원료, 첨가물, 특허성분표기 등 패키지 및 설명에 표기된 모든 성분/원료 정보 전부 추출"],
  "numbers_and_stats": ["성분 함량, 기간, 감량 수치, 만족도, 재구매율 등 설득에 쓰인 숫자와 통계를 전부 발췌하여 구체성 있게 기재"],
  "cta_texts": ["모든 구매/문의 유도 버튼과 하단 배너의 정확한 문구 전부 추출"],
  "copy_patterns": ["눈길을 끄는 메인 헤드라인, 극강의 후킹 문장, 비유법 등 텍스트의 실제 사례를 그대로 추출 (최소 7개 이상)"],
  "ui_elements": ["전환율을 높이기 위한 시각적 장치 모두 설명 (예: 최하단 고정 구매버튼, 흔들리는 혜택 안내 배너, 신뢰도를 높이는 뉴스 기사 캡처 등 세밀하게 기재)"],
  "total_sections": 0
}}

주의: 이미지에 실제로 보이는 텍스트만 추출하되, '매우 길고 구체적으로' 담아내야 합니다."""
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
                    return json.loads(p1_res.choices[0].message.content)
                
                st.write(f"↳ 총 {len(pattern_images)}개 화면 동시 병렬 분석 중...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(analyze_image, img_file) for img_file in pattern_images]
                    for future in concurrent.futures.as_completed(futures):
                        all_page_analyses.append(future.result())

                st.write(f"↳ Pass 1 완료 ({len(all_page_analyses)}개 페이지 분석). 공통점 교차 비교 중...")

                # ── Pass 2: GPT-4o 텍스트로 교차 비교 ──
                analyses_str = json.dumps(all_page_analyses, ensure_ascii=False, indent=2)
                p2_prompt = f"""당신은 퍼포먼스 마케팅 데이터 분석 전문가입니다.
아래는 효율이 검증된 {len(all_page_analyses)}개 랜딩페이지를 각각 분석한 결과입니다.

[각 페이지 분석 데이터]
{analyses_str}

[핵심 임무]
위 데이터들을 바탕으로 겉핥기식 요약이 아닌, **실무 마케터가 바로 벤치마킹할 수 있는 수준의 심층적이고 구체적인 인사이트**를 도출하세요.
각 분석 항목은 분석 페이지 수의 데이터를 모두 통합하여 매우 풍부하고 디테일하게(각 항목 최소 5~10개 이상) 작성해야 합니다.
모든 출력은 반드시 한국어로 작성하세요.

[출력 JSON 포맷 — 반드시 아래 형식으로만 리턴]
{{
  "summary": "단순 요약이 아닌, 이 페이지들이 공통적으로 취하고 있는 핵심 설득 전략과 트렌드에 대한 날카로운 마케팅 총평 (최소 5문장 이상 심층 서술)",
  "common_section_flow": [
    "1. [도입] 구체적인 후킹 방식 및 시선 끌기 전략 상세 서술",
    "2. [공감] 타겟 페인포인트 자극 및 공감대 형성 방식 확정",
    "3. [본론] 해결책 제시, 인증 및 시각화 방식",
    "4. [전개] 상세 설명, 리뷰 배치 등의 구체적 흐름 등등... (단순 단어 나열 불가, 아주 구체적인 문장으로 서술)"
  ],
  "common_keywords": [
    {{"keyword": "키워드명", "frequency": 등장한_페이지_수, "context": "단순 빈도를 넘어, 이 키워드가 어떤 '고객 심리'를 자극하기 위해 어떤 문맥과 조합으로 주로 쓰였는지 구체적 서술"}}
  ],
  "common_ingredients": [
    {{"ingredient": "구체적인 원재료/성분명", "frequency": 등장한_페이지_수, "note": "이 성분이 어떤 효능이나 마케팅적 셀링포인트로 어필되고 있는지 상세 서술"}}
  ],
  "common_copy_patterns": [
    {{"pattern": "공통 카피 공식 또는 문장 패턴의 명확한 정의", "example": "각 페이지에서 발췌한 실제 생생한 예시 문장들을 여러 개 포함하여 길게 묘사", "frequency": 등장_페이지_수}}
  ],
  "common_numbers_stats": [
    {{"stat": "공통적으로 쓰인 수치/통계 유형 (예: 기간 대비 효과 보장)", "examples": ["실제 인용구1", "실제 인용구2"], "frequency": 등장_페이지_수}}
  ],
  "common_ui_elements": [
    {{"element": "구체적인 UI 요소명", "frequency": 등장_페이지_수, "note": "이 UI 요소가 전환율(CVR) 상승에 어떻게 기여하는지(마케팅 심리학 및 UX 관점) 상세 서술"}}
  ],
  "common_cta_patterns": ["완전히 동일하지 않더라도 유사한 전략(예: 한정 혜택 강조형, 즉각적 행동 유도형)을 묶어서 실제 문구 위주로 5개 이상 구체적 서술"],
  "insights": ["이 데이터들을 관통하는 '팔리는 랜딩페이지의 숨겨진 공식'이나 실무 적용 팁 (최소 5개 이상의 딥다이브 인사이트)"],
  "recommended_must_haves": ["새로운 벤치마킹 페이지를 기획할 때 무조건 넣어야 할 필수 섹션, 장치, 카피 방향성 (매우 구체적으로 작성)"]
}}"""

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
                pattern_result = json.loads(p2_res.choices[0].message.content)
                pattern_result["_page_analyses"] = all_page_analyses  # 개별 분석 결과도 저장

                st.session_state.pattern_result = pattern_result
                pat_status.update(label=f"🎉 분석 완료! {len(all_page_analyses)}개 페이지의 공통 DNA 추출 성공!", state="complete")

            except Exception as e:
                pat_status.update(label="❌ 분석 실패", state="error")
                st.error(f"오류: {e}")
                import traceback; st.code(traceback.format_exc())

# ── 결과 렌더링 ──
if st.session_state.pattern_result:
    pr = st.session_state.pattern_result

    # 전체 요약
    st.markdown(f"""
    <div style='background-color:#0f172a; color:white; padding:25px 30px; border-radius:14px; margin:20px 0;'>
        <h4 style='margin:0 0 12px 0; color:#38bdf8;'>🧬 공통 마케팅 전략 요약</h4>
        <p style='margin:0; line-height:1.9; font-size:15px;'>{pr.get("summary", "")}</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab_ing, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📐 공통 섹션 흐름", "🔑 공통 키워드", "🧪 핵심 성분/원료", "✍️ 카피 패턴",
        "📊 공통 수치/통계", "🖼️ UI 요소", "💡 핵심 인사이트", "📄 개별 페이지 분석"
    ])

    with tab1:
        st.markdown("### 📐 공통 섹션 흐름 (순서)")
        flow = pr.get("common_section_flow", [])
        for i, step in enumerate(flow):
            color = "#3b82f6" if i == 0 else ("#10b981" if i == len(flow)-1 else "#8b5cf6")
            st.markdown(f"""
            <div style='display:flex; align-items:center; margin-bottom:10px;'>
                <div style='background:{color}; color:white; border-radius:50%; width:32px; height:32px; display:flex; align-items:center; justify-content:center; font-weight:bold; margin-right:14px; flex-shrink:0;'>{i+1}</div>
                <div style='background:white; padding:12px 18px; border-radius:8px; border:1px solid #e2e8f0; font-size:14px; flex:1;'>{step}</div>
            </div>
            """, unsafe_allow_html=True)
        cta_list = pr.get("common_cta_patterns", [])
        if cta_list:
            st.markdown("#### 🎯 공통 CTA 패턴")
            for c in cta_list:
                st.markdown(f"- `{c}`")

    with tab2:
        st.markdown("### 🔑 공통 키워드 (등장 빈도 순)")
        kws = sorted(pr.get("common_keywords", []), key=lambda x: x.get("frequency", 0), reverse=True)
        for kw in kws:
            freq = kw.get("frequency", 0)
            total = len(pr.get("_page_analyses", []))
            pct = int((freq / total) * 100) if total else 0
            bar_color = "#ef4444" if pct == 100 else ("#f97316" if pct >= 60 else "#3b82f6")
            st.markdown(f"""
            <div style='background:white; padding:14px 18px; border-radius:10px; border:1px solid #e2e8f0; margin-bottom:10px;'>
                <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>
                    <span style='font-weight:700; font-size:15px;'>#{kw.get("keyword","")}</span>
                    <span style='background:{bar_color}20; color:{bar_color}; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:bold;'>{freq}/{total}개 페이지</span>
                </div>
                <div style='background:#f1f5f9; border-radius:4px; height:6px; margin-bottom:8px;'>
                    <div style='background:{bar_color}; width:{pct}%; height:6px; border-radius:4px;'></div>
                </div>
                <p style='margin:0; color:#64748b; font-size:13px;'>{kw.get("context","")}</p>
            </div>
            """, unsafe_allow_html=True)

    with tab_ing:
        st.markdown("### 🧪 공통 핵심 성분 및 원재료")
        ing_list = sorted(pr.get("common_ingredients", []), key=lambda x: x.get("frequency", 0), reverse=True)
        if not ing_list:
            st.info("추출된 성분/원재료 정보가 없습니다.")
        for ing in ing_list:
            freq = ing.get("frequency", 0)
            total = len(pr.get("_page_analyses", []))
            st.markdown(f"""
            <div style='background:#f5f3ff; padding:14px 18px; border-radius:10px; border-left:4px solid #8b5cf6; margin-bottom:10px;'>
                <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>
                    <span style='font-weight:700; font-size:15px; color:#5b21b6;'>💊 {ing.get("ingredient","")}</span>
                    <span style='background:#ede9fe; color:#6d28d9; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:bold;'>{freq}/{total}개 페이지</span>
                </div>
                <p style='margin:0; color:#4c1d95; font-size:13px; margin-top:4px;'>{ing.get("note","")}</p>
            </div>
            """, unsafe_allow_html=True)

    with tab3:
        st.markdown("### ✍️ 공통 카피 패턴 & 공식")
        for cp in pr.get("common_copy_patterns", []):
            st.markdown(f"""
            <div style='background:#f0fdf4; padding:16px 20px; border-radius:10px; border-left:4px solid #22c55e; margin-bottom:12px;'>
                <div style='font-weight:700; font-size:14px; color:#15803d; margin-bottom:6px;'>📌 {cp.get("pattern","")}</div>
                <div style='color:#166534; font-size:13px; margin-bottom:4px;'>예시: "{cp.get("example","")}"</div>
                <div style='color:#86efac; font-size:12px;'>{cp.get("frequency",0)}개 페이지에서 발견</div>
            </div>
            """, unsafe_allow_html=True)

    with tab4:
        st.markdown("### 📊 공통 수치/통계 사용 패턴")
        for stat in pr.get("common_numbers_stats", []):
            examples = " / ".join(stat.get("examples", []))
            st.markdown(f"""
            <div style='background:#fefce8; padding:16px 20px; border-radius:10px; border-left:4px solid #eab308; margin-bottom:12px;'>
                <div style='font-weight:700; font-size:14px; color:#854d0e;'>📈 {stat.get("stat","")}</div>
                <div style='color:#713f12; font-size:13px; margin-top:6px;'>예시: {examples}</div>
                <div style='color:#a16207; font-size:12px; margin-top:4px;'>{stat.get("frequency",0)}개 페이지에서 발견</div>
            </div>
            """, unsafe_allow_html=True)

    with tab5:
        st.markdown("### 🖼️ 공통 UI 요소")
        for el in pr.get("common_ui_elements", []):
            freq = el.get("frequency", 0)
            total = len(pr.get("_page_analyses", []))
            st.markdown(f"""
            <div style='background:#f8fafc; padding:14px 18px; border-radius:10px; border:1px solid #e2e8f0; margin-bottom:10px; display:flex; align-items:flex-start;'>
                <span style='font-size:20px; margin-right:14px;'>🧩</span>
                <div>
                    <div style='font-weight:700; font-size:14px;'>{el.get("element","")}</div>
                    <div style='color:#64748b; font-size:13px; margin-top:4px;'>{el.get("note","")}</div>
                    <div style='color:#94a3b8; font-size:12px; margin-top:2px;'>{freq}/{total}개 페이지</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    with tab6:
        st.markdown("### 💡 핵심 인사이트")
        for i, insight in enumerate(pr.get("insights", [])):
            st.markdown(f"""
            <div style='background:linear-gradient(135deg, #667eea15, #764ba215); padding:16px 20px; border-radius:10px; border-left:4px solid #667eea; margin-bottom:12px;'>
                <span style='font-weight:700; color:#4c1d95;'>인사이트 {i+1}.</span> {insight}
            </div>
            """, unsafe_allow_html=True)
        st.markdown("### 🏆 반드시 포함해야 할 필수 요소")
        for must in pr.get("recommended_must_haves", []):
            st.markdown(f"✅ {must}")

    with tab7:
        st.markdown("### 📄 개별 페이지 분석 상세")
        for pa in pr.get("_page_analyses", []):
            with st.expander(f"📄 {pa.get('page_name', '페이지')} (총 {pa.get('total_sections', '?')}개 섹션)"):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("**섹션 흐름:**")
                    for s in pa.get("section_flow", []): st.markdown(f"- {s}")
                    st.markdown("**추출된 키워드:**")
                    st.markdown(" ".join([f"`{k}`" for k in pa.get("keywords", [])]))
                    st.markdown("**성분/원재료:**")
                    for ing in pa.get("ingredients", []): st.markdown(f"- {ing}")
                    st.markdown("**수치/통계:**")
                    for n in pa.get("numbers_and_stats", []): st.markdown(f"- {n}")
                with col_b:
                    st.markdown("**CTA 문구:**")
                    for c in pa.get("cta_texts", []): st.markdown(f"- `{c}`")
                    st.markdown("**카피 패턴:**")
                    for p in pa.get("copy_patterns", []): st.markdown(f"- {p}")
                    st.markdown("**UI 요소:**")
                    for u in pa.get("ui_elements", []): st.markdown(f"- {u}")
                st.markdown("**전체 추출 텍스트:**")
                st.text_area("", value="\n".join(pa.get("all_extracted_text", [])), height=200, key=f"txt_{pa.get('page_name','')}")

    # 전체 JSON 데이터 다운로드
    st.markdown("### 💾 분석 데이터 JSON 다운로드")
    export_data = {k: v for k, v in pr.items() if k != "_page_analyses"}
    export_data["individual_page_analyses"] = pr.get("_page_analyses", [])
    st.download_button(
        label="⬇️ 전체 공통점 분석 데이터 JSON 다운로드",
        data=json.dumps(export_data, ensure_ascii=False, indent=2),
        file_name="landing_pattern_analysis.json",
        mime="application/json",
        width="stretch"
    )

# Footer
st.write("---")
st.caption("Developed with ❤️ by 코다리 개발부장 파이프라인 엔진 V2.0")
