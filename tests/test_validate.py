import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.validate import parse_reference_range, classify_result

def test_parse_reference_range():
    # Standard range
    assert parse_reference_range("4000-10000") == (4000.0, 10000.0)
    assert parse_reference_range("4.50-5.50") == (4.5, 5.5)
    
    # Upper-bound only
    assert parse_reference_range("<50") == (None, 50.0)
    assert parse_reference_range("<= 12.5") == (None, 12.5)
    
    # Lower-bound only
    assert parse_reference_range(">60") == (60.0, None)
    assert parse_reference_range(">= 135") == (135.0, None)
    
    # Unparseable ranges
    assert parse_reference_range("Less than 1:80") == (None, None)
    assert parse_reference_range("Microscopy- Giemsa") == (None, None)

def test_classify_result_flags_outlier():
    # Test outlier low and high bounds
    # (value, range_low, range_high, outlier_low, outlier_high)
    assert classify_result(0.1, 12.0, 17.0, outlier_low=3.0) == "Outlier"
    assert classify_result(25.0, 12.0, 17.0, outlier_high=20.0) == "Outlier"
    
    # Test below and above normal ranges (but not outliers)
    assert classify_result(10.0, 12.0, 17.0, outlier_low=3.0) == "Below Range"
    assert classify_result(18.0, 12.0, 17.0, outlier_high=20.0) == "Above Range"
    
    # Test within normal range
    assert classify_result(15.0, 12.0, 17.0, outlier_low=3.0, outlier_high=20.0) == "Within Range"
    
    # Test missing results
    assert classify_result(None, 12.0, 17.0) == "Invalid"

if __name__ == "__main__":
    print("Running validate tests...")
    try:
        test_parse_reference_range()
        test_classify_result_flags_outlier()
        print("All validate tests passed successfully!")
    except AssertionError as ae:
        print(f"Test failure: {ae}")
        sys.exit(1)
