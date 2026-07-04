import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.standardize import normalize_test_name, extract_numeric, normalize_date
from src.utils import make_id

# Test dictionary mapping
TEST_DICTIONARY = {
    "HAEMOGLOBIN": {
        "aliases": ["HAEMOGLOBIN", "Haemoglobin", "Hb", "haemoglobin", "aemoglobin"]
    },
    "WHITE_BLOOD_CELL_COUNT": {
        "aliases": ["TOTAL WBC COUNT", "Total WBC Count", "WBC COUNT", "tal WBC Count"]
    }
}

def test_normalize_test_name_handles_ocr_typo():
    canonical, method, score = normalize_test_name("aemoglobin", TEST_DICTIONARY)
    assert canonical == "HAEMOGLOBIN"
    assert method == "exact_alias"
    
    # Test fuzzy matching
    canonical, method, score = normalize_test_name("haemoglobn", TEST_DICTIONARY) # small typo
    assert canonical == "HAEMOGLOBIN"
    assert method == "fuzzy_match"
    assert score >= 0.8

def test_extract_numeric_strips_units():
    assert extract_numeric("120000 cells/cu.mm") == 120000.0
    assert extract_numeric("13.7 g/dl") == 13.7
    assert extract_numeric("4,290") == 4290.0
    assert extract_numeric("POSITIVE") is None
    assert extract_numeric("4.50-5.50") is None  # Range, must not parse as result value

def test_normalize_date_formats():
    assert normalize_date("09-10-2025") == "2025-10-09"
    assert normalize_date("07-Oct-2025") == "2025-10-07"
    assert normalize_date("08/Oct/2025") == "2025-10-08"

def test_idempotent_id_includes_claim_no():
    id1 = make_id("CLAIM-A", "DOC001", "lab_report", "HEMOGLOBIN")
    id2 = make_id("CLAIM-B", "DOC001", "lab_report", "HEMOGLOBIN")
    assert id1 != id2   # same document_id, different claim_no -> must not collide

if __name__ == "__main__":
    # If run directly as a script
    print("Running standardize tests...")
    try:
        test_normalize_test_name_handles_ocr_typo()
        test_extract_numeric_strips_units()
        test_normalize_date_formats()
        test_idempotent_id_includes_claim_no()
        print("All standardize tests passed successfully!")
    except AssertionError as ae:
        print(f"Test failure: {ae}")
        sys.exit(1)
