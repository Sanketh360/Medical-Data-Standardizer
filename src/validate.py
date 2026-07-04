import re

def parse_reference_range(range_str):
    """
    Parses original reference range strings like '4000-10000', '<50', '>60' 
    into numerical (low, high) bounds.
    """
    if not range_str:
        return None, None
        
    range_str = range_str.replace(',', '').strip()
    
    # 1. Matches standard range format: '4000-10000' or '4.50-5.50'
    range_match = re.match(r'^([+-]?\d*\.\d+|[+-]?\d+)\s*-\s*([+-]?\d*\.\d+|[+-]?\d+)$', range_str)
    if range_match:
        try:
            return float(range_match.group(1)), float(range_match.group(2))
        except ValueError:
            pass
            
    # 2. Matches less than format: '<50' or '<= 12.5'
    lt_match = re.match(r'^<=\s*([+-]?\d*\.\d+|[+-]?\d+)|^<\s*([+-]?\d*\.\d+|[+-]?\d+)', range_str)
    if lt_match:
        val = lt_match.group(1) or lt_match.group(2)
        try:
            return None, float(val)
        except ValueError:
            pass
            
    # 3. Matches greater than format: '>60' or '>= 135'
    gt_match = re.match(r'^>=\s*([+-]?\d*\.\d+|[+-]?\d+)|^>\s*([+-]?\d*\.\d+|[+-]?\d+)', range_str)
    if gt_match:
        val = gt_match.group(1) or gt_match.group(2)
        try:
            return float(val), None
        except ValueError:
            pass
            
    return None, None

def classify_result(value, range_low, range_high, outlier_low=None, outlier_high=None, raw_text=None, rules=None, canon_name=None, ref_ranges=None):
    """
    Classify a clinical result value based on reference range and outlier limits.
    Supports qualitative validation using allowed text parameters.
    Returns: 'Within Range' | 'Above Range' | 'Below Range' | 'Outlier' | 'Invalid'
    """
    if value is None:
        if raw_text is not None:
            raw_text_str = str(raw_text).strip()
            
            # 1. Check reference range config if defined as qualitative
            if ref_ranges and canon_name and canon_name in ref_ranges:
                cfg = ref_ranges[canon_name]
                if cfg.get('validation_type') == 'qualitative':
                    allowed = [str(a).lower() for a in cfg.get('allowed', [])]
                    if raw_text_str.lower() in allowed:
                        # Treat clinical indicators (Positive, Reactive) as warning flags
                        if raw_text_str.lower() in ["positive", "reactive"]:
                            return "Above Range"
                        return "Within Range"
                    else:
                        return "Invalid"
            
            # 2. Check global allowed values in analytics rules
            if rules:
                allowed_vals = [str(v).lower() for v in rules.get('allowed_values', [])]
                if raw_text_str.lower() in allowed_vals:
                    if raw_text_str.lower() in ["positive", "reactive"]:
                        return "Above Range"
                    return "Within Range"
                    
        return "Invalid"
        
    # Check outlier limits first
    if outlier_low is not None and value <= outlier_low:
        return "Outlier"
    if outlier_high is not None and value >= outlier_high:
        return "Outlier"
        
    # Check normal reference ranges
    if range_low is not None and value < range_low:
        return "Below Range"
    if range_high is not None and value > range_high:
        return "Above Range"
        
    return "Within Range"
