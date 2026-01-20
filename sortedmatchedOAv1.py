import pandas as pd
import re
import time
import requests
from fuzzywuzzy import fuzz

# --------------------------------------------
#  OpenAlex helper functions
# --------------------------------------------
def clean_title(raw_title: str) -> str:
    """
    Remove the '.pdf' extension (if present) and unnecessary characters
    such as underscores, hyphens, and periods from the filename
    """
    if not isinstance(raw_title, str):
        return ""
    # Strip “.pdf” or “.PDF”
    if raw_title.lower().endswith(".pdf"):
        raw_title = raw_title[:-4]
    # Replace underscores, hyphens, and periods with spaces
    cleaned = raw_title.replace("_", " ").replace("-", " ").replace(".", " ")
    # Collapse multiple spaces into one
    cleaned = " ".join(cleaned.split())
    return cleaned


def fetch_openalex_metadata(title: str):
    """
    Query the OpenAlex API for a given title string.
    Returns a dict with 'abstract', 'year', 'authors', 'doi' if found
    otherwise returns None.
    """
    if not title:
        return None

    base_url = "https://api.openalex.org/works"
    filter_query = f'title.search:"{title}"'
    params = {
        "filter": filter_query,
        "per_page": 1   # only fetch the top match
    }

    try:
        resp = requests.get(base_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None

        work = results[0]

        # --- RECONSTRUCT ABSTRACT FROM INVERTED INDEX ---
        inv_index = work.get("abstract_inverted_index", {})
        if inv_index:
            # inv_index is like { word1: [pos1, pos2, …], word2: [pos3, …], … }
            # We collect all (position, word) pairs, sort by position, then join.
            positions = []
            for word, pos_list in inv_index.items():
                for pos in pos_list:
                    positions.append((pos, word))
            positions.sort(key=lambda x: x[0])
            abstract = " ".join([w for _, w in positions])
        else:
            abstract = ""

        # --- PUBLICATION YEAR ---
        year = work.get("publication_year", None)

        # --- AUTHORS (comma separated) ---
        authors_list = work.get("authorships", [])
        authors = ", ".join(
            a["author"]["display_name"]
            for a in authors_list
            if "author" in a and "display_name" in a["author"]
        )

        # --- DOI ---
        doi = work.get("doi", "")

        return {
            "abstract": abstract,
            "year":     year,
            "authors":  authors,
            "doi":      doi
        }

    except Exception as e:
        print(f"Error fetching OpenAlex data for '{title}': {e}")
        return None


# --------------------------------------------
# Fuzzy‐matching helper functions
# --------------------------------------------
def normalize_to_wordset(s: str) -> set:
    """
    1) Remove any “.pdf” (case‐insensitive)
    2) Lowercase everything.
    3) Replace any character that is not a letter, digit, or accented word with a space
    4) Collapse multiple spaces, split on spaces, return the set of unique words
    """
    if not isinstance(s, str):
        return set()

    # Strip off any trailing “.pdf” or “.PDF”
    s = re.sub(r"\.pdf$", "", s, flags=re.IGNORECASE)

    # owercase
    s = s.lower()

    #  Replace non‐alphanumeric (except accented words) with space
    s = re.sub(r"[^0-9a-záéíóúüñ]+", " ", s)

    # Collapse spaces, split into words
    s = re.sub(r"\s+", " ", s).strip()
    return set(s.split(" "))


def token_fuzzy_overlap_ratio(words1: set, words2: set, token_threshold=90) -> float:
    """
    - For each w1 in words1, check if there's any w2 in words2 with fuzz.ratio(w1, w2) ≥ token_threshold.
    - Build matched1 = {w1 in words1 | ∃ w2 with fuzz.ratio(w1,w2) ≥ token_threshold}
    - Build matched2 = {w2 in words2 | ∃ w1 with fuzz.ratio(w1,w2) ≥ token_threshold}
    - overlap_size = min(len(matched1), len(matched2))
    - denom = max(len(words1), len(words2))
    - return overlap_size / denom
    """
    if not words1 or not words2:
        return 0.0

    matched1 = set()
    matched2 = set()
    for w1 in words1:
        for w2 in words2:
            if fuzz.ratio(w1, w2) >= token_threshold:
                matched1.add(w1)
                matched2.add(w2)

    overlap_size = min(len(matched1), len(matched2))
    denom = max(len(words1), len(words2))
    return overlap_size / denom


# --------------------------------------------
# Main script
# --------------------------------------------
def main():
    # Load Excel files
    file1 = pd.read_excel("research_background_fo.xlsx")
    file2 = pd.read_excel("log.xlsx")

    # Column‐name configuration (adjust if needed)
    file1_doc_col   = "title"
    file1_year_col  = "year"
    file1_abs_col   = "abstract"
    file1_auth_col  = "authors"

    # tell the script which column in file1 holds the DOI ──
    file1_doi_col   = "doi"      # <-- change this header if your Excel uses a different name

    file2_doc_col    = "document"
    file2_hyp_col    = "hypothesis"
    file2_label_col  = "label"
    file2_notes_col  = "verification_notes"

    # Precompute “wordset” for each title in File2
    file2["wordset"] = file2[file2_doc_col].map(normalize_to_wordset)

    # Keep track of which File2 indices are still “available” to match
    remaining_file2_indices = set(file2.index.tolist())

    # Prepare a list to collect merged‐rows
    merged_results = []

    #  Build a list of File2 columns to copy later
    all_file2_columns = [c for c in file2.columns.tolist() if c != "wordset"]

    #0 For each row in File1, find best File2 match
    for idx1, row1 in file1.iterrows():
        raw_title1 = row1[file1_doc_col]
        words1     = normalize_to_wordset(raw_title1)

        best_ratio = 0.0
        best_idx2  = None

        for idx2 in list(remaining_file2_indices):
            words2 = file2.at[idx2, "wordset"]
            ratio  = token_fuzzy_overlap_ratio(words1, words2, token_threshold=90)
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx2  = idx2

        # Build merged_row, starting by copying ALL File1 columns
        merged_row = {}
        for col in file1.columns:
            merged_row[col] = row1[col]

        merged_row["doi"] = row1.get(file1_doi_col, None)

        # If a good match was found (ratio ≥ 0.90), copy File2 columns
        if best_idx2 is not None and best_ratio >= 0.90:
            matched_row2 = file2.loc[best_idx2]
            for col in all_file2_columns:
                merged_row[col] = matched_row2[col]
            remaining_file2_indices.remove(best_idx2)

        else:
            # No valid match: set all File2 columns to None
            for col in all_file2_columns:
                merged_row[col] = None

            # It remains whatever file1 provided (or None if file1 had no DOI).

        # Record the overlap percentage
        merged_row["Overlap % (Fuzzy Tokens)"] = round(best_ratio * 100, 2)
        merged_results.append(merged_row)

    #  Now process any File2 rows that never got matched
    for idx2 in remaining_file2_indices:
        row2 = file2.loc[idx2]
        merged_row = {}

        #Set every File1 column to None
        for col in file1.columns:
            merged_row[col] = None

        # opy all File2 columns
        for col in all_file2_columns:
            merged_row[col] = row2[col]

        # Overlap percent is None (unmatched), and add a note
        merged_row["Overlap % (Fuzzy Tokens)"] = None
        merged_row["Note"] = "Unmatched File 2 row"

        # Fetch OpenAlex metadata for this File2 document
        raw_doc_name = row2[file2_doc_col]
        cleaned = clean_title(raw_doc_name)
        meta = fetch_openalex_metadata(cleaned)
        if meta is not None:
            merged_row[file1_abs_col]  = meta["abstract"]
            merged_row[file1_year_col] = meta["year"]
            merged_row[file1_auth_col] = meta["authors"]
            merged_row["doi"]          = meta["doi"]     # <— This overwrites only for file2 rows
        else:
            merged_row[file1_abs_col]  = ""
            merged_row[file1_year_col] = None
            merged_row[file1_auth_col] = ""
            merged_row["doi"]          = ""

        time.sleep(1)
        merged_results.append(merged_row)

    # Convert merged_results into a DataFrame
    results_df = pd.DataFrame(merged_results)

    # Ensure all desired columns exist (fill missing with None)
    final_col_order = [
        "title",
        "document",
        "label",
        "year",
        "authors",
        "abstract",
        "hypothesis",
        "verification_notes",
        "doi",
       # "Overlap % (Fuzzy Tokens)"
    ]
    for col in final_col_order:
        if col not in results_df.columns:
            results_df[col] = None

    results_df = results_df[final_col_order]

    # Write out to Excel
    results_df.to_excel("matched_merged.xlsx", index=False)
    print("Done! See 'matched_merged.xlsx'.")

if __name__ == "__main__":
    main()
