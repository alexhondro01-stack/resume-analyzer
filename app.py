import streamlit as st
import os
import tempfile
import re
import requests
import json
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from io import BytesIO
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from agents import ResumeCrew
from fpdf import FPDF
from tools import extract_text
from dotenv import load_dotenv

# --- ROBUST CONFIGURATION LOADING ---
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True) 
else:
    load_dotenv(override=True)

st.set_page_config(page_title="AI Resume Matcher", layout="wide", page_icon="🚀")

# Initialize session state
if 'step' not in st.session_state: st.session_state.step = 1
if 'provider' not in st.session_state: st.session_state.provider = "OpenAI"
if 'jd_text' not in st.session_state: st.session_state.jd_text = ""
if 'selected_template' not in st.session_state: st.session_state.selected_template = "Modern"
if 'analysis_result' not in st.session_state: st.session_state.analysis_result = None
if 'optimized_result' not in st.session_state: st.session_state.optimized_result = None
if 'selected_improvements' not in st.session_state: st.session_state.selected_improvements = []

# --- TEMPLATES ---
TEMPLATES = {
    "Executive": {"font": "Times New Roman", "align": "CENTER", "color": (0, 0, 0)},
    "Modern": {"font": "Arial", "align": "LEFT", "color": (41, 128, 185)},
    "ATS-Friendly": {"font": "Courier", "align": "LEFT", "color": (0, 0, 0)}
}

# --- HELPERS ---
def get_api_key(provider_name):
    env_var = "OPENAI_API_KEY" if provider_name == "OpenAI" else "GOOGLE_API_KEY"
    key = os.environ.get(env_var, os.getenv(env_var, ""))
    return key.strip().strip("'").strip('"')

def extract_score(text):
    m = re.search(r"(\d{1,3})\s*/\s*100", str(text))
    if not m: 
        m = re.search(r"(?:Score|Match|Likelihood):\s*(\d{1,3})", str(text), re.IGNORECASE)
    return int(m.group(1)) if m else 0

def clean_for_latin1(text):
    if not text: return ""
    chars = {
        '\u2013': '-', '\u2014': '-', '\u2018': "'", '\u2019': "'", 
        '\u201c': '"', '\u201d': '"', '\u2022': '*', '\u2026': '...',
        '\u00a0': ' ', '\ufb01': 'fi', '\ufb02': 'fl'
    }
    for k, v in chars.items(): text = text.replace(k, v)
    return text.encode('latin-1', 'ignore').decode('latin-1')

def create_pdf(text, template_name):
    style = TEMPLATES[template_name]
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    safe_text = clean_for_latin1(text)
    # Clean out the log for the actual document
    clean_text = safe_text.split("TRANSFORMATION LOG")[0].replace("REVISED RESUME", "").strip()
    lines = clean_text.split('\n')
    pdf.set_font("Helvetica", 'B', 16)
    align = 'C' if style['align'] == "CENTER" else 'L'
    if lines:
        pdf.set_text_color(*style['color'])
        pdf.cell(0, 10, lines[0].strip(), ln=True, align=align)
        pdf.ln(5)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=11)
    for line in lines[1:]:
        if not line.strip(): 
            pdf.ln(2)
            continue
        if len(line) < 50 and (line.isupper() or line.endswith(':')):
            pdf.set_font("Helvetica", 'B', 12)
            pdf.set_text_color(*style['color'])
            pdf.cell(0, 10, line.strip(), ln=True)
            pdf.set_font("Helvetica", size=11)
            pdf.set_text_color(0, 0, 0)
        else:
            pdf.multi_cell(0, 6, line.strip())
    return pdf.output(dest='S').encode('latin-1')

def create_templated_docx(text, template_name):
    style = TEMPLATES[template_name]
    doc = Document()
    # Clean out the log for the actual document
    clean_text = text.split("TRANSFORMATION LOG")[0].replace("REVISED RESUME", "").strip()
    lines = clean_text.split('\n')
    if lines:
        h = doc.add_heading(lines[0].strip(), level=0)
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER if style['align'] == "CENTER" else WD_ALIGN_PARAGRAPH.LEFT
        h.runs[0].font.name = style['font']
        h.runs[0].font.color.rgb = RGBColor(*style['color'])
    for line in lines[1:]:
        if line.strip():
            if len(line) < 50 and (line.isupper() or line.endswith(':')):
                p = doc.add_heading(line.strip(), level=1)
                p.runs[0].font.name = style['font']
                p.runs[0].font.color.rgb = RGBColor(*style['color'])
            else:
                p = doc.add_paragraph(line.strip())
                p.runs[0].font.name = style['font']
    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()

def fetch_jd(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers, timeout=12)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "button"]):
            element.extract()
        content_selectors = ["article", "main", ".job-description", ".show-more-less-html__markup", "#jobDescriptionText", "[class*='jobDescription']", ".description__text", ".careers-job-description"]
        main_content = None
        for selector in content_selectors:
            found = soup.select_one(selector)
            if found:
                main_content = found
                break
        target = main_content if main_content else soup.body
        relevant_text = []
        priority_keywords = ["responsibility", "requirement", "qualification", "skill", "experience", "bonus", "stack", "technology", "about the role"]
        noise_keywords = ["equal opportunity", "inclusive", "cookie", "copyright", "all rights reserved", "privacy policy", "terms of service", "follow us"]
        if target:
            for block in target.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'div']):
                text = block.get_text(strip=True)
                if len(text) < 15: continue 
                if any(noise in text.lower() for noise in noise_keywords): continue
                is_priority = any(pw in text.lower() for pw in priority_keywords)
                if is_priority or block.name == 'li' or len(text) > 40:
                    clean_block = re.sub(r'\s+', ' ', text)
                    relevant_text.append(clean_block)
        final_lines = []
        for line in relevant_text:
            if not final_lines or line[:30] != final_lines[-1][:30]:
                final_lines.append(line)
        return "\n\n".join(final_lines)[:8000]
    except Exception as e:
        return f"Scraping Error: {str(e)}. Please copy/paste the JD text manually for best results."

def parse_feedback(text):
    sections = {"requirements": {"high": [], "medium": [], "low": []}, "qualifications": {"high": [], "medium": [], "low": []}}
    current_section = "requirements"
    prio = "medium"
    for line in str(text).split('\n'):
        l = line.lower()
        if "qualification" in l or "experience" in l: current_section = "qualifications"
        elif "requirement" in l or "skill" in l: current_section = "requirements"
        if "[high]" in l or "critical" in l: prio = "high"
        elif "[low]" in l: prio = "low"
        elif "[medium]" in l or "important" in l: prio = "medium"
        if line.strip().startswith(('-', '*', '•', '1.')):
            item = line.strip().lstrip('- *•1.2.3.').replace('[HIGH]', '').replace('[MEDIUM]', '').replace('[LOW]', '').strip()
            if len(item) > 3:
                sections[current_section][prio].append(item)
    return sections

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Settings")
    st.session_state.provider = st.selectbox("LLM Provider", ["OpenAI", "Gemini"], index=0 if st.session_state.provider == "OpenAI" else 1)
    
    o_key = get_api_key("OpenAI")
    g_key = get_api_key("Gemini")
    
    st.caption(f"OpenAI: {'✅' if o_key else '❌'} | Gemini: {'✅' if g_key else '❌'}")
    
    with st.expander("🔑 Manual Key Overwrite"):
        key_input = st.text_input("Enter API Key", type="password")
        if st.button("Apply Key"):
            env_var = "OPENAI_API_KEY" if st.session_state.provider == "OpenAI" else "GOOGLE_API_KEY"
            os.environ[env_var] = key_input.strip()
            st.rerun()

    st.divider()
    if st.button("🗑️ Reset All"):
        st.session_state.clear()
        st.rerun()

# --- STEPPER ---
s1, s2, s3 = st.columns(3)
with s1: st.markdown(f"**{'🔵' if st.session_state.step==1 else '✅'} 1. Setup**")
with s2: st.markdown(f"**{'🔵' if st.session_state.step==2 else '✅' if st.session_state.step>2 else '⚪'} 2. Analysis**")
with s3: st.markdown(f"**{'🔵' if st.session_state.step==3 else '⚪'} 3. Final Result**")
st.divider()

# --- STEP 1: SETUP ---
if st.session_state.step == 1:
    st.subheader("📄 Your Resume")
    up = st.file_uploader("Upload Resume (PDF/DOCX)", type=["pdf", "docx"])
    if up: 
        st.session_state.original_filename = up.name

    st.divider()

    st.subheader("💼 Job Posting :orange[(BETA)]")
    st.caption("⚠️ URL fetching is currently in beta. It works best with LinkedIn, Indeed, and Greenhouse links.")
    
    url = st.text_input("Job URL")
    if st.button("Fetch Relevant Content (Beta)") and url:
        with st.spinner("Analyzing web content and filtering noise..."): 
            st.session_state.jd_text = fetch_jd(url)
    
    st.session_state.jd_text = st.text_area(
        "Job Description Content", 
        value=st.session_state.jd_text, 
        height=250, 
        help="Paste the description here or use the Beta fetcher above."
    )

    st.divider()

    if st.button("Generate Match Report →", type="primary", use_container_width=True):
        current_key = get_api_key(st.session_state.provider)
        if up and len(st.session_state.jd_text) > 50 and current_key:
            with st.spinner("Analyzing your profile against the job..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{up.name.split('.')[-1]}") as t:
                    t.write(up.getvalue()); st.session_state.resume_path = t.name
                st.session_state.original_text = extract_text(st.session_state.resume_path)
                crew = ResumeCrew(st.session_state.resume_path, st.session_state.jd_text, st.session_state.provider)
                st.session_state.analysis_result = str(crew.analyze())
                st.session_state.step = 2; st.rerun()
        else:
            if not current_key:
                st.error(f"Please configure your API key for {st.session_state.provider} in the sidebar or .env file.")
            elif not up:
                st.error("Please upload your resume to continue.")
            elif len(st.session_state.jd_text) <= 50:
                st.error("Please provide a more detailed job description.")

# --- STEP 2: ANALYSIS ---
elif st.session_state.step == 2:
    score = extract_score(st.session_state.analysis_result)
    sc_col, info_col = st.columns([1, 2])
    color = "#ef4444" if score < 50 else "#f97316" if score < 75 else "#22c55e"
    with sc_col:
        st.markdown(f"""
        <div style='background:{color}; color:white; padding:30px; border-radius:15px; text-align:center;'>
            <p style='margin-bottom:0; font-size:14px; opacity:0.9;'>MATCH SCORE</p>
            <h1 style='margin-top:0; font-size:64px;'>{score}%</h1>
        </div>
        """, unsafe_allow_html=True)
    with info_col:
        st.markdown("### 🎯 Your Optimization Roadmap")
        st.write("Focus on the **Critical Gaps** first to improve your chances with ATS filters.")
        st.progress(score/100)

    st.divider()
    feedback = parse_feedback(st.session_state.analysis_result)
    selected_items = []

    def render_priority_group(category_name, data):
        st.markdown(f"#### {category_name}")
        if data["high"]:
            st.markdown("**🔴 Critical Gaps (Recommended)**")
            for i, item in enumerate(data["high"]):
                if st.checkbox(item, value=True, key=f"{category_name}_high_{i}"):
                    selected_items.append(item)
        if data["medium"]:
            with st.expander(f"🟡 Secondary Improvements ({len(data['medium'])} items)"):
                for i, item in enumerate(data["medium"]):
                    if st.checkbox(item, value=True, key=f"{category_name}_med_{i}"):
                        selected_items.append(item)
        if data["low"]:
            with st.expander(f"🔵 Minor Enhancements ({len(data['low'])} items)"):
                for i, item in enumerate(data["low"]):
                    if st.checkbox(item, value=False, key=f"{category_name}_low_{i}"):
                        selected_items.append(item)

    col_req, col_qual = st.columns(2)
    with col_req: render_priority_group("🛠️ Skills & Keywords", feedback["requirements"])
    with col_qual: render_priority_group("🎓 Qualification Gaps", feedback["qualifications"])

    st.divider()
    btn_col1, btn_col2 = st.columns([1, 3])
    with btn_col1:
        if st.button("← Go Back"): st.session_state.step = 1; st.rerun()
    with btn_col2:
        if st.button("Apply Selected Improvements & Rewrite ✨", type="primary", use_container_width=True):
            if not selected_items:
                st.warning("Please select at least one improvement to apply.")
            else:
                st.session_state.selected_improvements = selected_items
                with st.spinner("Rewriting your resume..."):
                    crew = ResumeCrew(st.session_state.resume_path, st.session_state.jd_text, st.session_state.provider)
                    st.session_state.optimized_result = str(crew.optimize(", ".join(selected_items)))
                    st.session_state.step = 3; st.rerun()

# --- STEP 3: RESULTS (FOCUSED) ---
elif st.session_state.step == 3:
    st.subheader("✨ Your Optimized Resume")
    
    # Template Selection
    t_cols = st.columns(3)
    for i, t_name in enumerate(TEMPLATES.keys()):
        if t_cols[i].button(t_name, use_container_width=True, type="primary" if st.session_state.selected_template == t_name else "secondary"):
            st.session_state.selected_template = t_name; st.rerun()
    st.divider()

    # Data Splitting: Separate Resume from the AI Log
    full_text = st.session_state.optimized_result
    if "TRANSFORMATION LOG" in full_text:
        resume_part, log_part = full_text.split("TRANSFORMATION LOG")
    else:
        resume_part = full_text
        log_part = "AI summary not generated. Refer to selected improvements below."

    # Main Display
    st.markdown("### 📄 Resume Content")
    st.session_state.optimized_result = st.text_area(
        "Final Polish (Editable)", 
        value=resume_part.replace("REVISED RESUME", "").strip(), 
        height=600
    )

    st.markdown("### 🛠️ Changes & Transformations")
    with st.expander("View Detailed Transformation Log", expanded=True):
        st.write(log_part.strip())
        
        st.markdown("**Improvements Requested:**")
        cols = st.columns(len(st.session_state.selected_improvements) // 3 + 1)
        for idx, imp in enumerate(st.session_state.selected_improvements):
            cols[idx % len(cols)].markdown(f"✅ {imp}")

    st.divider()
    
    # Final Actions
    down_col1, down_col2, refresh_col = st.columns([1, 1, 2])
    with down_col1:
        docx_data = create_templated_docx(st.session_state.optimized_result, st.session_state.selected_template)
        st.download_button("📥 Word (.docx)", docx_data, file_name=f"Optimized_Resume.docx", use_container_width=True)
    with down_col2:
        try:
            pdf_data = create_pdf(st.session_state.optimized_result, st.session_state.selected_template)
            st.download_button("📥 PDF (.pdf)", pdf_data, file_name="Optimized_Resume.pdf", mime="application/pdf", use_container_width=True)
        except Exception as e:
            st.error("PDF Error")
    with refresh_col:
        if st.button("Start New Analysis", use_container_width=True): 
            st.session_state.step = 1; st.rerun()