import pdfplumber
import docx
import spacy
import os
from sentence_transformers import SentenceTransformer, util

# Suppress Hugging Face symlink warning
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Load NLP models globally with error handling
try:
    nlp = spacy.load("en_core_web_sm")
except Exception:
    nlp = None

try:
    similarity_model = SentenceTransformer('all-MiniLM-L6-v2')
except Exception:
    similarity_model = None

def extract_text(file_path: str):
    """Extracts raw text from a PDF or DOCX file path."""
    text = ""
    if not os.path.exists(file_path):
        return "Error: File path does not exist."
    try:
        if file_path.endswith('.pdf'):
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
        elif file_path.endswith('.docx'):
            doc = docx.Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])
        return text.strip() if text else "Error: No text could be extracted."
    except Exception as e:
        return f"Error reading file: {str(e)}"

def extract_keywords(text: str):
    """Extracts noun phrases and proper nouns (skills/technologies) from text."""
    if not nlp:
        return []
    doc = nlp(text.lower()[:100000]) # Cap text length for safety
    keywords = set([token.text for token in doc if token.pos_ in ['NOUN', 'PROPN'] and not token.is_stop and len(token.text) > 1])
    return list(keywords)

def calculate_match_score(resume_text: str, jd_text: str):
    """Calculates a cosine similarity score (0-100) between resume and JD."""
    if not similarity_model or not resume_text or not jd_text:
        return 0.0
    try:
        embeddings = similarity_model.encode([resume_text, jd_text])
        score = util.cos_sim(embeddings[0], embeddings[1])[0][0].item()
        return round(float(score) * 100, 2)
    except Exception:
        return 0.0

def identify_gaps(resume_text: str, jd_text: str):
    """Identifies keywords present in JD but missing in Resume."""
    if not nlp:
        return []
    try:
        resume_doc = nlp(resume_text.lower()[:50000])
        jd_doc = nlp(jd_text.lower()[:50000])
        resume_tokens = set([token.lemma_ for token in resume_doc if token.pos_ in ['NOUN', 'PROPN'] and not token.is_stop])
        jd_tokens = set([token.lemma_ for token in jd_doc if token.pos_ in ['NOUN', 'PROPN'] and not token.is_stop])
        return list(jd_tokens - resume_tokens)
    except Exception:
        return []