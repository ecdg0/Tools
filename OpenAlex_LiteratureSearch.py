import requests
import pandas as pd
import time
import re

# =============================================================================
# Utility functions
# =============================================================================

def reconstruct_abstract(inv_idx):
    """
    Reconstructs the full abstract text from OpenAlex's abstract_inverted_index

    Parameters
    ----------
    inv_idx : dict
        Dictionary where keys are words and values are lists of word positions

    Returns
    -------
    str
        Reconstructed abstract text. Returns an empty string if unavailable
    """
    if not inv_idx:
        return ""

    # Determine abstract length from maximum word position
    length = 1 + max(pos for positions in inv_idx.values() for pos in positions)
    words = [""] * length

    # Place each word in its corresponding position
    for word, positions in inv_idx.items():
        for pos in positions:
            words[pos] = word

    return " ".join(words)


def normalize_title(title):
    """
    Normalizes a title string for deduplication purposes

    Normalization steps:
    - Convert to lowercase
    - Trim spaces
    - Replace basic punctuation with spaces
    - Collapse multiple spaces into a single space

    Parameters
    ----------
    title : str

    Returns
    -------
    str
        Normalized title.
    """
    if not isinstance(title, str):
        return ""

    text = title.strip().lower()
    text = re.sub(r"[,\.\:\;\-\(\)\[\]\{\}]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text


# =============================================================================
# Phase A: Retrieve works matching BOTH title and abstract (all years)
# =============================================================================

base_url_A = (
    "https://api.openalex.org/works?"
    # TITLE SEARCH (MODIFY THIS QUERY)
    "filter=title.search:(%22forced%20oscillation%22%20OR%20%22forced%20oscillations%22"
    "%20OR%20%22oscillation%20location%22%20OR%20%22oscillation%20localization%22),"
    # ABSTRACT SEARCH (MODIFY THIS QUERY)
    "abstract.search:(%22power%20systems%22%20OR%20%22power%20system%22"
    "%20OR%20%22forced%20oscillation%20localization%22%20OR%20%22oscillation%20location%22"
    "%20OR%20%22forced%20oscillations%20localization%22"
    "%20OR%20%22forced%20oscillation%20power%20systems%22)"
    "&per-page=200"
)

all_items = []
seen_ids = set()
seen_titles_norm = set()
cursor = "*"

print("=== Phase A: Fetching works matching title AND abstract ===")

while cursor:
    paged_url = f"{base_url_A}&cursor={cursor}"
    print(f"Fetching (Phase A): {paged_url}")

    results = requests.get(paged_url).json()

    for item in results["results"]:
        oid = item["id"]
        title = item["title"]
        title_norm = normalize_title(title)

        # Skip duplicates by ID or normalized title
        if oid in seen_ids or title_norm in seen_titles_norm:
            continue

        abstract_text = reconstruct_abstract(
            item.get("abstract_inverted_index", {})
        )

        all_items.append({
            "id": oid,
            "title": title,
            "title_norm": title_norm,
            "authors": ", ".join(
                a["author"]["display_name"] for a in item["authorships"]
            ),
            "year": item["publication_year"],
            "journal": item.get("host_venue", {}).get("display_name", ""),
            "doi": item.get("doi", ""),
            "abstract": abstract_text
        })

        seen_ids.add(oid)
        seen_titles_norm.add(title_norm)

    cursor = results["meta"].get("next_cursor")
    if cursor:
        time.sleep(1)  # Respect API rate limits

print(f"Phase A complete. Retrieved {len(all_items)} records.\n")


# =============================================================================
# Phase B: Retrieve ONLY 2025 works matching title (no abstract filter)
# =============================================================================

base_url_B = ( 
    #MODIFY THIS QUERY, PUBLICATION YEAR AND TITLE KEY WORDS EVEN IF THE ABSTRACT IS MISSING
    "https://api.openalex.org/works?"
    "filter=publication_year:2025,"
    "title.search:(%22forced%20oscillation%22%20OR%20%22forced%20oscillations%22"
    "%20OR%20%22oscillation%20location%22%20OR%20%22oscillation%20localization%22)"
    "&per-page=200"
)

cursor = "*"
print("=== Phase B: Fetching 2025 works matching title only ===")

while cursor:
    paged_url = f"{base_url_B}&cursor={cursor}"
    print(f"Fetching (Phase B): {paged_url}")

    results = requests.get(paged_url).json()

    for item in results["results"]:
        oid = item["id"]
        title = item["title"]
        title_norm = normalize_title(title)

        # Skip already collected works
        if oid in seen_ids or title_norm in seen_titles_norm:
            continue

        abstract_text = reconstruct_abstract(
            item.get("abstract_inverted_index", {})
        )

        all_items.append({
            "id": oid,
            "title": title,
            "title_norm": title_norm,
            "authors": ", ".join(
                a["author"]["display_name"] for a in item["authorships"]
            ),
            "year": item["publication_year"],
            "journal": item.get("host_venue", {}).get("display_name", ""),
            "doi": item.get("doi", ""),
            "abstract": abstract_text
        })

        seen_ids.add(oid)
        seen_titles_norm.add(title_norm)

    cursor = results["meta"].get("next_cursor")
    if cursor:
        time.sleep(1)

print(f"Phase B complete. Total records collected: {len(all_items)}.\n")


# =============================================================================
# Deduplication by normalized title
# =============================================================================

print("=== Deduplicating by normalized title ===")

df = pd.DataFrame(all_items)
print(f"Records before deduplication: {len(df)}")

df = df.drop_duplicates(subset=["title_norm"], keep="first")

print(f"Records after deduplication: {len(df)}")
print(f"Duplicates removed: {len(all_items) - len(df)}\n")

# Remove auxiliary column before export
df_final = df.drop(columns=["title_norm"])


# =============================================================================
# Export to Excel
# =============================================================================

output_filename = "openalex_results.xlsx"
df_final.to_excel(output_filename, index=False)

print(f"{len(df_final)} unique records saved to '{output_filename}'.")
