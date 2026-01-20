
## PDF_AIClassifier.py

Classifies papers (PDFs) as **Model-Based**, **Data-Driven**, **Hybrid**, or **Unclear** using **Gemini**, and generates a **technical, testable hypothesis** for each paper. Results are logged to Excel and PDFs are automatically organized into folders by classification.

---

## Installation

pip install pdfplumber google-genai pandas openpyxl python-dotenv tqdm tenacity

---

## API Key Setup

Create a .env file in the same directory as the script:

GEMINI_API_KEY=YOUR_API_KEY_HERE

Get your API key from:
https://aistudio.google.com/app/apikey

---

## Testing Mode

For testing, the script processes only the first n PDFs:

pdf_files = pdf_files[:n]

Remove or increase n for full runs.

---

## Directory Structure

Place this script in a dedicated working directory.
All output folders and files are created in the same directory as the script.

Example:
project_root/
|-- PDF_AIClassifier.py
|-- .env
|-- log.xlsx                  (created automatically)
|-- model_based/              (created automatically)
|-- data_driven/              (created automatically)
|-- hybrid/                   (created automatically)
`-- unclear/                  (created automatically)


## PDF Location and Execution

PDFs do NOT need to be inside the script directory.
You can point to any folder using a glob pattern.

python PDF_AIClassifier.py "/path/to/pdfs/*.pdf"

Examples:

python PDF_AIClassifier.py "./papers/*.pdf"
python PDF_AIClassifier.py "D:/Research/ForcedOscillations/*.pdf"

After processing, each PDF is moved into the corresponding classification folder

---

## Notes

PDFs are moved, not copied. Keep backups if needed.
Designed for systematic literature review in power-system FORCED OSCILLATIONS

