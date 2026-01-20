# Document Matching & Bibliographic Pipeline

## Overview

This repository contains a **Python pipeline** designed to **match, merge and enrich academic document metadata** across two Excel datasets. 
The script combines:
- **Token-level fuzzy matching** for robust document alignment  
- **Strict one to one matching logic** to avoid ambiguity  
- **metadata preservation** (DOIs are never overwritten)  
- **data enrichment via the OpenAlex scholarly database**

The result is suitable for literature reviews and reference preprocessing.

---

## Inputs

### File  
**Filename:** :research_background_fo.xlsx

This file is treated as the **source** of paper metadata.

Expected columns:
- `title` – Canonical paper title  
- `year` – Publication year  
- `authors` – Author list  
- `abstract` – Abstract text  
- `doi` – Digital Object Identifier  

>  they can be changed in the configuration section of the script.

---

### Secondary file / Log File  
**Filename:** :log.xlsx`

Expected columns:
- `document` – Document name
- `hypothesis` – Hypothesis or research idea
- `label` – Classification or category
- `verification_notes` – Review or validation notes

---

## Output

### `matched_merged.xlsx`

A unified dataset where each row corresponds to **one paper**, combining:
-  metadata
- Research annotations
- DOI 

Final output columns:
- `title`
- `document`
- `label`
- `year`
- `authors`
- `abstract`
- `hypothesis`
- `verification_notes`
- `doi`

---

## Matching Methodology

### Title Normalization

Before matching, document titles are normalized by:
- Removing `.pdf` extensions
- Lowercasing
- Removing punctuation and special characters
- Splitting into **sets of unique tokens**

---

### Token Fuzzy Matching

Instead of comparing entire strings, the script:
- Compares **individual tokens** using Levenshtein similarity
- Requires ≥ 90% similarity per token
- Computes overlap as a fraction of total unique tokens

A match is accepted only if token overlap >90%.


This approach is significantly more reliable than full-string fuzzy matching for academic titles.

---

### One to One Match Enforcement

Each document in the secondary file can be matched **only once**.  This preventsData contamination due to multiple similar papers in the source .xlsx
Unmatched rows are explicitly handled.

---

## Metadata rules

- DOIs from the primary file are **never overwritten**
- OpenAlex DOIs are used **only for unmatched secondary documents**

---

## OpenAlex Enrichment
For documents that exist **only** in the secondary file:

- OpenAlex API is queried using the cleaned document title
- Abstracts are reconstructed from OpenAlex’s **inverted index**
- Retrieved fields include:
  - Abstract
  - Authors
  - Publication year
  - DOI

A delay between API calls is enforced to respect rate limits.

---

## Installation & Confiuratrion
pip install pandas requests fuzzywuzzy python-Levenshtein openpyxl
All file paths and column names can be modified in the configuration section:
file1_doc_col  = "title"
file1_year_col = "year"
file1_abs_col  = "abstract"
file1_auth_col = "authors"
file1_doi_col  = "doi"

file2_doc_col   = "document"
file2_hyp_col   = "hypothesis"
file2_label_col = "label"
file2_notes_col = "verification_notes"


