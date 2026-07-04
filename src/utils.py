import hashlib
import os
import yaml

def levenshtein_distance(s1, s2):
    """Calculate the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def string_similarity(s1, s2):
    """Calculate the normalized similarity ratio between two strings (0.0 to 1.0)."""
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    max_len = max(len(s1), len(s2))
    dist = levenshtein_distance(s1, s2)
    return 1.0 - (dist / max_len)

def make_id(claim_no, document_id, record_type, discriminator):
    """Generate a deterministic SHA256 hash to act as the primary key ID."""
    # Ensure no None values enter the hash key
    c_no = claim_no or ""
    doc_id = document_id or ""
    rec_type = record_type or ""
    disc = discriminator or ""
    raw = f"{c_no}|{doc_id}|{rec_type}|{disc}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def load_yaml(file_path):
    """Utility to safely load YAML files."""
    if not os.path.exists(file_path):
        return {}
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}
