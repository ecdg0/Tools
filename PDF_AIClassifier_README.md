# PDF_AIClassifier.py
Classifies papers (PDFs) as **Model-Based**, **Data-Driven**, **Hybrid**, or **Unclear** using **Gemini** and generates a **technical, testable hypothesis** for each paper. Results are logged to Excel and PDFs are automatically organized into folders by classification.

installation: pip install pdfplumber google-genai pandas openpyxl python-dotenv tqdm tenacity
API key setup: create a .env file within the same directory as the script: GEMINI_API_KEY=YOUR_API_KEY_HERE, get it from: https://aistudio.google.com/app/apikey
for testing, the script only process the first n pdfs: pdf_files = pdf_files[:n]
---

## Directory structure (important)

**Place this script in a dedicated working directory.**  
All output folders and files are created **in the same directory as the script**.

Example:
project_root/
│
├─ PDF_AIClassifier.py
├─ .env
├─ log.xlsx                  ← created automatically
│
├─ model_based/              ← created automatically
├─ data_driven/              ← created automatically
├─ hybrid/                   ← created automatically
└─ unclear/                  ← created automatically


NOTE: PDFs do NOT need to be inside the script directory
You can point to any folder using a glob pattern:
python  PDF_AIClassifier.py "/path/to/pdfs/*.pdf"
Examples:
python classify_papers.py "./papers/*.pdf"
python classify_papers.py "D:/Research/ForcedOscillations/*.pdf"


