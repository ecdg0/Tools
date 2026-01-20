#!/usr/bin/env python3

"""
classify_papers.py
──────────────────

Usage:
    python classify_papers.py "/absolute/or/relative/path/*.pdf"

Requires:
    pip install pdfplumber google-genai pandas openpyxl python-dotenv tqdm tenacity
"""

import glob
import sys
import re
import os
import shutil
import json
import pathlib
import warnings
import time

import pdfplumber
import pandas as pd

#Correctly import the GenAI SDK and types
from google import genai
from google.genai.types import HttpOptions, GenerationConfig # HttpOptions might not be strictly needed for public API, but keep for now if other use cases exist

from tqdm import tqdm
from tenacity import retry, wait_random_exponential, stop_after_attempt
from dotenv import load_dotenv

# -------- CLI & paths ----------------------------------------------------

if len(sys.argv) != 2:
    print("Usage: python classify_papers.py \"<path_to_pdfs>/*.pdf\"")
    sys.exit(1)

PDF_GLOB = sys.argv[1]        # "D:/MyPapers/*.pdf"
BASE_DIR  = pathlib.Path(__file__).parent   # where script lives

DEST = {
    "Model-Based": BASE_DIR / "model_based",
    "Data-Driven": BASE_DIR / "data_driven",
    "Hybrid":      BASE_DIR / "hybrid",
    "Unclear":     BASE_DIR / "unclear",
}
for p in DEST.values():
    p.mkdir(exist_ok=True)

LOG_PATH = BASE_DIR / "log.xlsx"

# nsure we load the .env from this exact folder:
dotenv_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=dotenv_path)

# ----------- Verify API key loading -----------
api_key = os.getenv("GEMINI_API_KEY")
if api_key is None:
    print("ERROR: GEMINI_API_KEY was not found. Make sure you have a .env file with that variable")
    print("Get your API key from: https://aistudio.google.com/app/apikey")
    sys.exit(1)
else:
    print(f"GEMINI_API_KEY loaded successfully: {api_key[:8]}…")

# -------- 1.  Initialize the Gen AI client ------------------------------------

# Initialize the GenAI client to use the public Gemini API with your API key
client = genai.Client(
    api_key=api_key,
   
)

# -------- 2.  PDF → text (improved extraction) -------------------------------

def find_references_section(text: str) -> int:
    """
    Find the position of the references section in the text.
    Returns the position or -1 if not found.
    """
    ref_patterns = [
        r"(?i)\n\s*(?:\d+\.?|[IVX]+\.?)?\s*references?\s*[:\-]?\s*\n",
        r"(?i)\n\s*bibliography\s*[:\-]?\s*\n",
        r"(?i)\n\s*cited\s+references?\s*[:\-]?\s*\n",
        r"(?i)\n\s*literature\s+cited\s*[:\-]?\s*\n",
        r"(?i)\n\s*works?\s+cited\s*[:\-]?\s*\n"
    ]
    
    for pattern in ref_patterns:
        match = re.search(pattern, text)
        if match:
            return match.start()
    
    return -1

def extract_text_before_references(text: str, chars_to_extract: int = 500) -> str:
    """
    Extract specified number of characters before the references section.
    """
    ref_pos = find_references_section(text)
    if ref_pos == -1:
        # If no references found, take from the end
        return text[-chars_to_extract:] if len(text) > chars_to_extract else text
    
    start_pos = max(0, ref_pos - chars_to_extract)
    return text[start_pos:ref_pos].strip()

def extract_sections(pdf_path: str) -> str:
    """
    Opens the PDF, extracts text from the first 4 pages and last 2 pages,
    then uses regex to pull out Abstract, Introduction, Conclusions.
    If conclusions are empty/short, extract 500 chars before references.
    If none of those match, fallback to first 50 lines + last 30 lines.
    Finally truncate to 30 000 characters (fits within Gemini's context window).
    """
    text_parts = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                first_pages = pdf.pages[:4]
                last_pages = pdf.pages[-2:] if len(pdf.pages) > 6 else []
                for page in first_pages + last_pages:
                    page_txt = page.extract_text() or ""
                    text_parts.append(page_txt)
        except Exception as e:
            print(f"Warning: Could not extract text from {pdf_path}: {e}")
            return "Could not extract text from PDF"

    full_text = "\n".join(text_parts)

    # Patterns for Abstract, Introduction, Conclusions
    abstract = ""
    introduction = ""
    conclusions = ""

    abstract_patterns = [
        r"(?is)(?:\d+\.?|[IVX]+\.)?\s*abstract\s*[:\-\.]?\s*(.*?)(?=\n\s*(?:keywords|index\s*terms|introduction|1\.\s*introduction|i\.\s*introduction|chapter\s+\d+|section\s+\d+|background|problem\s*statement|motivation|author\s+details|acknowledgements?|references|\n{3,})|\Z)",
        r"(?is)(?:\d+\.?|[IVX]+\.)?\s*summary\s*[:\-\.]?\s*(.*?)(?=\n\s*(?:keywords|index\s*terms|introduction|1\.\s*introduction|i\.\s*introduction|chapter\s+\d+|section\s+\d+|background|problem\s*statement|motivation|author\s+details|acknowledgements?|references|\n{3,})|\Z)",
        r"(?is)abstract\s*[:\-\.]?\s*(.*?)(?=\n{2,}|\n\s*(?:[A-Z][A-Z\s]+(?:\s*[:\.\-]?\s*\n)?(?:[A-Z][a-z]+)*)|\Z)",
    ]

    for pat in abstract_patterns:
        m = re.search(pat, full_text)
        if m and len(m.group(1).strip()) > 50:
            abstract = m.group(1).strip()
            break

    intro_patterns = [
        r"(?is)(?:\d+\.?|[IVX]+\.)?\s*(?:introduction|background|preliminary|problem\s*statement|motivation)\s*[:\-\.]?\s*(.*?)(?=\n\s*(?:2\.|ii\.|method(?:ology)?|approach(?:es)?|related\s*work|literature\s*review|proposed\s*method|experiment(?:al\s+setup)?|results|discussion|conclusions?|chapter\s+\d+|section\s+\d+|references|acknowledgements?|\Z))",
        r"(?is)(?:introduction|background|preliminary)\s*[:\-\.]?\s*(.*?)(?=\n{2,}|\n\s*[A-Z][a-z]*\s*:\s*|\Z)",
        r"(?is)(?:[IVX]+\.)?\s*(?:INTRODUCTION)\s*(.*?)(?=\n\s*\d+\.\s*|\n{2,}|\n\s*[A-Z][a-z]*\s*:\s*|\Z)",
    ]
    
    for pat in intro_patterns:
        m = re.search(pat, full_text)
        if m and len(m.group(1).strip()) > 50:
            introduction = m.group(1).strip()
            break

    conclusion_patterns = [
        r"(?is)(?:\d+\.?|[IVX]+\.)?\s*(?:conclusions?|concluding\s+remarks?|summary\s+and\s+conclusions?|future\s*work|discussions?\s*and\s+conclusions?|final\s+remarks?|closing\s+remarks?)\s*[:\-]?(?:\s*\n+\s*[A-Z]*)?(.*?)(?=\n\s*(?:acknowledgements?|references|appendix|appendices|author\s+contributions?|competing\s+interests?|data\s+availability|supplementary\s+material|glossary|abstract|introduction|methodology|methods|results|discussion|acknowledgments|chapter\s+\d+|section\s+\d+|\d+\.?|[IVX]+\.)|\n\s*(?:•|\*|\-)\s+[A-Z0-9]|\n[A-Z]|\Z)",
        r"(?is)(?:\d+\.?|[IVX]+\.)?\s*(?:conclusions?|concluding\s+remarks?|summary\s+and\s+conclusions?|future\s*work|discussions?\s*and\s+conclusions?|final\s+remarks?)\s*[:\-]?(?:\s*\n+\s*[A-Z]*)?(.*?)(?=\n{3,}|\n\s*(?:REFERENCES|APPENDIX|ACKNOWLEDGMENTS|BIBLIOGRAPHY|INDEX|LIST\s+OF\s+FIGURES|LIST\s+OF\s+TABLES|ABOUT\s+THE\s+AUTHORS?|AUTHORS?|FIGURE\s+\d+|TABLE\s+\d+|\s*[A-Z][a-z]*\s*\:\s*.*|\s*(?:\d+\)|\d+\.|\*|\-)\s[A-Z0-9])|\Z)",
        r"(?is)(?:future\s*work|future\s*prospects|future\s*research)\s*[:\-]?(?:\s*\n+\s*[A-Z]*)?(.*?)(?=\n\s*(?:acknowledgements?|references|appendix|appendices|\Z))",
    ]

    for pat in conclusion_patterns:
        m = re.search(pat, full_text)
        if m and len(m.group(1).strip()) > 30:
            conclusions = m.group(1).strip()
            break

    # NEW: If conclusions are empty or very short, extract text before references
    if len(conclusions) < 50:
        print(f"WARNING: Conclusions section is short ({len(conclusions)} chars), extracting text before references...")
        conclusions = extract_text_before_references(full_text, 500)
        print(f"CORRECT: Extracted {len(conclusions)} chars before references section")

    if not abstract and not introduction:
        lines = full_text.split("\n")
        first_chunk = "\n".join(lines[:80])    # first 80 lines
        last_chunk = "\n".join(lines[-50:])    # last 50 lines
        combined = f"Beginning of paper:\n{first_chunk}\n\nEnd of paper:\n{last_chunk}"
    else:
        combined = (
            f"Abstract:\n{abstract}\n\n"
            f"Introduction:\n{introduction}\n\n"
            f"Conclusions:\n{conclusions}"
        )

    # Debug prints
    print(f"Extracted {len(combined)} characters from PDF")
    print(f"  - Abstract: {len(abstract)} chars, Introduction: {len(introduction)} chars, Conclusions: {len(conclusions)} chars")

    return combined[:35000]  # truncate to ~35 000 chars


# -------- 3.  Build the Gemini prompt & call ----------------------------------

def build_prompt(excerpt: str) -> str:
    """
    EXAMPLE: Construct a high-quality prompt for extracting detailed technical hypotheses and robust classification
    from a paper on power system oscillations.
    """
    return f"""
You are an expert in power-system oscillations. Given a paper, output ONLY valid JSON with keys: hypothesis, label.

REQUIREMENTS:
- The "hypothesis" field must be a *detailed*, *technical*, *testable* hypothesis
- If evidence or limitations (performance in noise, real PMU data, effect of resonance, etc) are discussed, **incorporate them into the hypothesis**
- The "label" field must be EXACTLY one of: Model-Based, Data-Driven, Hybrid or Unclear

DEFINITIONS FOR LABELS:
- **Model-Based**: The work is fundamentally based on *first-principles*, physical laws, analytical models, or explicit mathematical system models (state-space, swing equations, transfer functions)
- **Data-Driven**: The work primarily *learns patterns from measurement data* using statistical, machine learning, or deep learning methods, with little or no reliance on physical models. 
- **Hybrid**: Both Model-Based and Data-Driven elements are *substantial and intertwined* (a physics-informed neural network, data-driven parameter estimation for a model, or a deep model trained with physical constraints or state equations).
- **Unclear**: Use only if the document does not provide enough detail to classify, or if it is a review, survey, conceptual

EXAMPLES:

EXAMPLE INPUT:
Title: "Kalman Filter Location of Forced Oscillation Source"
Excerpt:
We derive a state-space small-signal model and track excitation with a multiple-model Kalman filter.

EXAMPLE OUTPUT:
{{
  "hypothesis": "We propose a small-signal electromechanical state-space model combined with a multiple-model Kalman filter for identifying forced oscillation sources on each bus. We hypothesize that this physics-based approach yields at least 25% higher localization accuracy than Prony-analysis methods when the excitation frequency is within ±0.05 Hz of an inter-area mode. Testing is conducted under ±10% load variation on a 240-bus synthetic system, with a true-positive detection rate ≥ 90% and false alarm rate < 5%. The covariance converges within 2 seconds, supporting real-time tracking.",
  "label": "Model-Based"
}}

EXAMPLE INPUT:
Title: "Deep Learning for Anomaly Detection in Power System Oscillations"
Excerpt:
We propose a novel deep neural network architecture to detect non-linear power system oscillations from wide-area measurement system (WAMS) data. The model is trained on historical PMU data, including both normal and anomalous operational states, and uses unsupervised learning techniques to identify deviations.

EXAMPLE OUTPUT:
{{
  "hypothesis": "We develop a deep convolutional autoencoder for unsupervised detection of anomalous power system oscillations using streaming WAMS PMU data. The method is trained on both normal and disturbed states, and is hypothesized to reach ≥95% recall for forced oscillations with <2% false positive rate on unseen data from the WECC system. It processes data in real time, triggering alarms within 100 ms, with no need for a pre-defined physical model.",
  "label": "Data-Driven"
}}

EXAMPLE INPUT:
Title: "Physics-Informed Neural Networks for Power System Oscillation Mode Identification"
Excerpt:
This paper introduces a Physics-Informed Neural Network (PINN) approach to identify oscillation modes.

EXAMPLE OUTPUT:
{{
  "hypothesis": "A physics-informed neural network (PINN) is presented for mode identification, where the swing equation is embedded as a hard constraint in the loss function.
  "label": "Hybrid"
}}

If the excerpt is clearly a survey, review, or conceptual paper, or lacks enough detail for classification, output:
{{
  "hypothesis": "The excerpt does not provide a specific, testable hypothesis or propose a novel methodology, but rather offers an overview, survey
  "label": "Unclear"
}}

NOW ANALYZE THIS PAPER:
Title: "<Actual Paper Title Here>"
Excerpt:
\"\"\"{excerpt}\"\"\"

Output ONLY the JSON response with "hypothesis" and "label".
""".strip()

def build_verification_prompt(excerpt: str, initial_label: str, hypothesis: str) -> str:
    """
    Build a secondary verification prompt specifically for Model-Based papers that might actually be Data-Driven
    """
    return f"""
You are an expert reviewer verifying paper classifications. A paper was initially classified as "{initial_label}" but needs verification.

TASK: Determine if this paper should actually be classified as "Data-Driven" instead of "Model-Based".

KEY INDICATORS FOR DATA-DRIVEN (even if initially seemed Model-Based):
- Time series analysis methods (ARIMA, VAR, spectral analysis)
- Statistical pattern recognition from historical data
- Machine learning on measurement data
- Empirical mode decomposition
- Statistical inference from PMU/SCADA data
- Data mining approaches
- Any method that primarily learns from patterns in measured data rather than physical equations

INITIAL CLASSIFICATION: {initial_label}
HYPOTHESIS: {hypothesis}

EXCERPT:
\"\"\"{excerpt}\"\"\"

Respond with ONLY a JSON containing:
- "verified_label": Either keep the original label or change to "Data-Driven" if the paper primarily uses data-driven methods
- "reason": Brief explanation of why the label was kept or changed

Example responses:
{{"verified_label": "Data-Driven", "reason": "Paper uses time series analysis and spectral methods on PMU data, which are fundamentally data-driven approaches"}}
{{"verified_label": "Model-Based", "reason": "Paper uses physical equations and analytical models as primary methodology"}}
"""

@retry(wait=wait_random_exponential(min=5, max=30), stop=stop_after_attempt(3))
def call_gemini(excerpt: str) -> dict:
    prompt_text = build_prompt(excerpt)
    try:
        gen_config = GenerationConfig(
            temperature=0.0,
            top_p=1.0,
            top_k=1,
            max_output_tokens=3000,
            candidate_count=1
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash-preview-05-20",
            contents=[prompt_text],
        )

        raw = resp.text
        print(f"\n<<< Gemini raw output >>>\n{raw[:500]}...\n<<< end output >>>\n")

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            result = json.loads(raw)

        if "hypothesis" not in result or "label" not in result:
            print("WARNING: Response missing required keys; defaulting to Unclear.")
            return {"hypothesis": "", "label": "Unclear"}

        valid_labels = {"Model-Based", "Data-Driven", "Hybrid", "Unclear"}
        if result["label"] not in valid_labels:
            print(f"WARNING: Invalid label '{result['label']}' returned; defaulting to Unclear.")
            result["label"] = "Unclear"

        return result

    except json.JSONDecodeError as e:
        print(f"WARNING: JSON parsing error: {e}")
        return {"hypothesis": "", "label": "Unclear"}
    except Exception as e:
        print(f"WARNING: Gemini API call error: {e}")
        raise

@retry(wait=wait_random_exponential(min=5, max=30), stop=stop_after_attempt(3))
def verify_classification(excerpt: str, initial_label: str, hypothesis: str) -> dict:
    """
    Secondary verification call to double-check Model-Based classifications
    """
    prompt_text = build_verification_prompt(excerpt, initial_label, hypothesis)
    try:
        gen_config = GenerationConfig(
            temperature=0.0,
            top_p=1.0,
            top_k=1,
            max_output_tokens=1000,
            candidate_count=1
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash-preview-05-20",
            contents=[prompt_text],
        )

        raw = resp.text
        print(f"\n<<< Verification output >>>\n{raw[:300]}...\n<<< end verification >>>\n")

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            result = json.loads(raw)

        return result

    except Exception as e:
        print(f"WARNING: Verification error: {e}")
        return {"verified_label": initial_label, "reason": "Verification failed, keeping original"}


# -------- 4.  Logging helper --------------------------------------------------

def append_log(row: dict):
    """
    Append a row with keys "document", "hypothesis", "label", "verification_notes" to log.xlsx.
    """
    if LOG_PATH.exists():
        df = pd.read_excel(LOG_PATH)
    else:
        df = pd.DataFrame(columns=["document", "hypothesis", "label", "verification_notes"])
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_excel(LOG_PATH, index=False)


# -------- 5.  Main loop -------------------------------------------------------

pdf_files = glob.glob(PDF_GLOB, recursive=False)
print(f"Found {len(pdf_files)} PDF(s)")

# For testing, limit to first 2 PDFs; remove or increase once it's working end-to-end.
pdf_files = pdf_files[:2]

for i, pdf in enumerate(tqdm(pdf_files, desc="Classifying")):
    name = pathlib.Path(pdf).name
    verification_notes = ""
    
    try:
        print(f"\nProcessing: {name}")
        excerpt = extract_sections(pdf)

        if len(excerpt.strip()) < 100:
            print(f"Warning: Very little text extracted from {name}")
            print(f"First 200 chars:\n{excerpt[:200]}")

        if i > 0:
            print("Waiting 10 seconds between requests…")
            time.sleep(10)

        # Primary classification
        result = call_gemini(excerpt)
        label = result.get("label", "Unclear")
        hypothesis = result.get("hypothesis", "")

        print(f"Initial classification for {name}: {label}")
        if hypothesis:
            print(f"Hypothesis preview: {hypothesis[:100]}...")

        # NEW: Secondary verification for Model-Based papers
        if label == "Model-Based":
            print(f" Verifying Model-Based classification for {name}...")
            time.sleep(5)  # Brief pause between calls
            
            verification = verify_classification(excerpt, label, hypothesis)
            verified_label = verification.get("verified_label", label)
            reason = verification.get("reason", "No reason provided")
            
            if verified_label != label:
                print(f" Classification changed from {label} to {verified_label}")
                print(f"   Reason: {reason}")
                label = verified_label
                verification_notes = f"Changed from Model-Based to {verified_label}. Reason: {reason}"
            else:
                print(f"CORRECT: Classification verified as {label}")
                verification_notes = f"Verified as {label}. Reason: {reason}"

    except Exception as e:
        print(f"\n[!] {name}: {e}")
        label = "Unclear"
        hypothesis = ""
        verification_notes = f"Error during processing: {str(e)}"

    # Always append to log.xlsx
    append_log({
        "document": name,
        "hypothesis": hypothesis,
        "label": label,
        "verification_notes": verification_notes
    })

    # Move file into the folder named after its label
    dest_folder = DEST.get(label, DEST["Unclear"])
    try:
        shutil.move(pdf, dest_folder / name)
        print(f"Moved to: {dest_folder.name}/")
    except Exception as e:
        print(f"Warning: Could not move file {name}: {e}")


print(f"\nDone. Log saved to {LOG_PATH}")
