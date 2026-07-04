import re
from datetime import datetime
from src.utils import string_similarity, make_id
from src.validate import parse_reference_range, classify_result

def normalize_test_name(original_name, dictionary):
    """
    Standardises test names using alias matching and Levenshtein similarity.
    Returns: (canonical_name, normalization_method, confidence)
    """
    if not original_name:
        return None, "unmapped_fallback", 0.0
    
    orig_clean = original_name.strip()
    
    # 1. Exact or case-insensitive alias match
    for canonical, info in dictionary.items():
        aliases = info.get('aliases', [])
        # Check canonical itself
        if orig_clean.lower() == canonical.lower():
            return canonical, "exact_alias", 1.0
        # Check aliases
        for alias in aliases:
            if orig_clean.lower() == alias.lower():
                return canonical, "exact_alias", 1.0
                
    # 2. Fuzzy match
    best_match = None
    best_score = 0.0
    
    for canonical, info in dictionary.items():
        aliases = info.get('aliases', [])
        # Check canonical
        score = string_similarity(orig_clean, canonical)
        if score > best_score:
            best_score = score
            best_match = canonical
        # Check aliases
        for alias in aliases:
            score = string_similarity(orig_clean, alias)
            if score > best_score:
                best_score = score
                best_match = canonical
                
    if best_score >= 0.8:
        return best_match, "fuzzy_match", round(best_score, 2)
        
    # 3. Fallback
    return orig_clean.upper(), "unmapped_fallback", 0.0

def extract_numeric(val_str):
    """
    Extract a floating point value from the result text.
    Returns None if the result contains a range (e.g. '4.50-5.50') or no numbers.
    """
    if not val_str:
        return None
    val_clean = val_str.replace(',', '').strip()
    
    # Check for range patterns like X-Y or X - Y
    if re.search(r'\d+\s*-\s*\d+', val_clean):
        return None
        
    # Find first decimal or integer number
    match = re.search(r'[-+]?\d*\.\d+|\d+', val_clean)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None

def normalize_gender(gender_str):
    """Standardise gender representations to Male/Female/Other."""
    if not gender_str:
        return None
    g = gender_str.strip().lower()
    if "redacted" in g:
        return gender_str.strip()  # Preserve REDACTED tags
    if g.startswith('m'):
        return "Male"
    if g.startswith('f'):
        return "Female"
    return "Other"

def normalize_age(age_str):
    """Standardise age representation."""
    if not age_str:
        return None
    return age_str.strip()

def normalize_date(date_str):
    """Convert input date strings to YYYY-MM-DD standard."""
    if not date_str:
        return None
    date_str = date_str.strip()
    
    formats = [
        ("%d-%m-%Y", False),
        ("%d-%b-%Y", False),
        ("%d/%b/%Y", False),
        ("%d/%m/%Y", False),
        ("%Y-%m-%d", True),
    ]
    for fmt, is_ok in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str

def normalize_unit(unit_str, conversion_dict):
    """Standardise original units to canonical units and return conversion factor."""
    if not unit_str:
        return "", 1.0
    u_clean = unit_str.strip()
    if u_clean in conversion_dict:
        info = conversion_dict[u_clean]
        if isinstance(info, dict):
            return info.get('canonical', u_clean), float(info.get('factor', 1.0))
    return u_clean, 1.0

def map_medicine(med_name, med_dict):
    """Map medication to standard canonical name and dosage type."""
    if not med_name:
        return None, None
    m_clean = med_name.strip()
    m_clean_lower = m_clean.lower()
    
    # Match in dictionary (case-insensitive alias lookup)
    for key, info in med_dict.items():
        aliases = [a.lower() for a in info.get('aliases', [])]
        canonical = info.get('canonical', key)
        if m_clean_lower == key.lower() or m_clean_lower == canonical.lower() or m_clean_lower in aliases:
            return canonical, info.get('type', 'Unknown')
            
    # Fallback to name-based inference if not found
    m_lower = m_clean.lower()
    inferred_type = "Unknown"
    if "tab" in m_lower:
        inferred_type = "Tablet"
    elif "inj" in m_lower:
        inferred_type = "Injection"
    elif "cap" in m_lower:
        inferred_type = "Capsule"
    elif "syp" in m_lower or "syrup" in m_lower:
        inferred_type = "Syrup"
    elif "powder" in m_lower:
        inferred_type = "Powder"
        
    return m_clean, inferred_type

def standardize_document(record_header, unit_conv_dict, test_dict, ref_ranges, med_dict, analytics_rules=None):
    """
    Standardises and flattens a single document into 1 or more rows matching the 78 columns.
    """
    raw_data = record_header['raw_detail_data']
    rec_type = record_header['record_type']
    
    # Pre-calculate common standardized metadata
    std_patient_name = record_header['patient_name']
    std_age = normalize_age(record_header['age'])
    std_gender = normalize_gender(record_header['gender'])
    
    # Build standard row template with all 78 schema columns set to None
    base_row = {
        'id': None, 'document_id': record_header['document_id'], 'record_type': rec_type,
        'file_gcs_path': record_header['file_gcs_path'], 'trace_id': record_header['trace_id'],
        'correlation_id': record_header['correlation_id'], 'source_system': record_header['source_system'],
        'claim_no': record_header['claim_no'], 'nt_code': record_header['nt_code'],
        'consumer_client_id': record_header['consumer_client_id'], 'destination_identifier': record_header['destination_identifier'],
        'patient_name': std_patient_name, 'age': std_age, 'gender': std_gender, 'uhid': raw_data.get('uhid'),
        'hospital_name': record_header['hospital_name'], 'doctor_name': record_header['doctor_name'],
        'bill_date': None, 'reports_date': None,
        'test_name_canonical': None, 'test_name_original': None,
        'result_value': None, 'result_text': None, 'unit_canonical': None, 'unit_original': None,
        'range_low': None, 'range_high': None, 'range_text': None, 'test_analytics': None,
        'normalization_method': None, 'normalization_confidence': None,
        'admission_date': None, 'discharge_date': None,
        'diagnosis': None, 'brief_history': None, 'general_examinations': None, 'recommendations': None,
        'hospital_address': raw_data.get('hospitalAddress'), 'ward': raw_data.get('ward'),
        'post_discharge_advice': raw_data.get('postDischargeAdvice'),
        'medicine': None, 'dose': None, 'frequency': None, 'medicine_type': None,
        'processed_at': None, 'ingested_at': None,
        # Legacy/Duplicate columns
        'basic_info_age': raw_data.get('age') if rec_type == 'discharge_summary' else raw_data.get('basic_info', {}).get('age'),
        'basic_info_bill_date': raw_data.get('basic_info', {}).get('bill_date'),
        'medicine_injections_investigation': str(raw_data.get('medicineInjectionsInvestigation')) if raw_data.get('medicineInjectionsInvestigation') else None,
        'discharge_medications_dose': None,
        'metadetails': record_header['raw_meta_details'],
        'discharge_medications_frequency': None,
        'discharge_medications_medicine': None,
        'lab_or_hospital_name': raw_data.get('basic_info', {}).get('lab_or_hospital_name'),
        'report_details_page_no': None, 'report_details_range': None, 'report_details_result': None,
        'report_details_test_analytics': None, 'report_details_test_name': None, 'report_details_unit': None,
        'age_text': raw_data.get('basic_info', {}).get('age'),
        'other_med_inj_investigations': str(raw_data.get('medicineInjectionsInvestigation')) if raw_data.get('medicineInjectionsInvestigation') else None,
        'report_date': raw_data.get('basic_info', {}).get('reports_date'),
        'course_during_hospitalisation': str(raw_data.get('courseDuringHospitalisation')) if raw_data.get('courseDuringHospitalisation') else None,
        'page_number': None, 'range_text_original': None, 'medication_dose': None, 'result_text_original': None,
        'medication_frequency': None, 'course_during_hospitalization': str(raw_data.get('courseDuringHospitalisation')) if raw_data.get('courseDuringHospitalisation') else None,
        'medication_name': None, 'page_no': None, 'test_name': None, 'medication_medicine': None,
        'result': None, 'unit': None,
        'age_years': raw_data.get('basic_info', {}).get('age'),
        'range': None
    }
    
    rows = []
    
    if rec_type == 'lab_report':
        # Standardise date fields
        base_row['bill_date'] = normalize_date(raw_data.get('basic_info', {}).get('bill_date'))
        base_row['reports_date'] = normalize_date(raw_data.get('basic_info', {}).get('reports_date'))
        base_row['uhid'] = raw_data.get('basic_info', {}).get('uhid')
        
        report_details = raw_data.get('report_details', [])
        if not report_details:
            # Fallback to single empty test row if array is empty
            row = base_row.copy()
            row['id'] = make_id(row['claim_no'], row['document_id'], row['record_type'], "empty_report")
            rows.append(row)
        else:
            for idx, test in enumerate(report_details):
                row = base_row.copy()
                orig_name = test.get('test_name')
                
                # Deterministic ID includes claim_no, document_id, record_type, and discriminator (original test name + index)
                row_id = make_id(row['claim_no'], row['document_id'], row['record_type'], f"{orig_name or 'none'}|{idx}")
                row['id'] = row_id
                
                orig_result = test.get('result')
                orig_unit = test.get('unit')
                orig_range = test.get('range')
                page_no = test.get('page_no')
                orig_analytics = test.get('test_analytics')
                
                # Test name normalisation
                canon_name, norm_method, norm_conf = normalize_test_name(orig_name, test_dict)
                row['test_name_canonical'] = canon_name
                row['test_name_original'] = orig_name
                row['normalization_method'] = norm_method
                row['normalization_confidence'] = norm_conf
                
                # Unit normalisation & conversion factor scaling
                row['unit_original'] = orig_unit
                row['unit'] = orig_unit
                canon_unit, factor = normalize_unit(orig_unit, unit_conv_dict)
                row['unit_canonical'] = canon_unit
                
                # Result parsing
                row['result_text'] = orig_result
                row['result'] = orig_result
                row['result_text_original'] = orig_result
                res_val = extract_numeric(orig_result)
                if res_val is not None:
                    res_val = float(res_val) * float(factor)
                row['result_value'] = res_val
                
                # Reference range parsing
                row['range_text'] = orig_range
                row['range'] = orig_range
                row['range_text_original'] = orig_range
                low, high = parse_reference_range(orig_range)
                if low is not None:
                    low = float(low) * float(factor)
                if high is not None:
                    high = float(high) * float(factor)
                row['range_low'] = low
                row['range_high'] = high
                
                # Outlier / Validation Classification
                low_calc = None
                high_calc = None
                outlier_low = None
                outlier_high = None
                
                # Check if test has configuration thresholds
                has_config = canon_name in ref_ranges
                if has_config:
                    outlier_low = ref_ranges[canon_name].get('outlier_low')
                    outlier_high = ref_ranges[canon_name].get('outlier_high')
                
                # Determine which range boundaries to use
                # If document provides a range (Rule 2 & Rule 4), use the parsed document range (low, high)
                if low is not None or high is not None:
                    low_calc = low
                    high_calc = high
                # Else, if present in reference_ranges.yaml (Rule 3), use configuration range
                elif has_config and (ref_ranges[canon_name].get('low') is not None or ref_ranges[canon_name].get('high') is not None):
                    low_calc = ref_ranges[canon_name].get('low')
                    high_calc = ref_ranges[canon_name].get('high')
                
                # Classify based on resolved range boundaries
                if low_calc is not None or high_calc is not None:
                    row['test_analytics'] = classify_result(
                        row['result_value'], low_calc, high_calc, outlier_low, outlier_high,
                        raw_text=orig_result, rules=analytics_rules, canon_name=canon_name, ref_ranges=ref_ranges
                    )
                else:
                    # No range is available in either the document or reference_ranges.yaml
                    # Rule 1: Check if it matches a valid qualitative test in the global rules
                    qualitative_analytics = classify_result(
                        row['result_value'], None, None, None, None,
                        raw_text=orig_result, rules=analytics_rules, canon_name=canon_name, ref_ranges=ref_ranges
                    )
                    if qualitative_analytics in ["Within Range", "Above Range"]:
                        row['test_analytics'] = qualitative_analytics
                    else:
                        # Numeric test with no range is Invalid
                        row['test_analytics'] = "Invalid"
                
                # Save raw analytics value before mapping fallbacks
                row['report_details_test_analytics'] = orig_analytics
                
                # Fallback to original classifier only if it matches one of our standard enum flags
                if row['test_analytics'] == "Invalid" and orig_analytics:
                    orig_clean_flag = orig_analytics.strip().lower()
                    valid_flags = {
                        "within range": "Within Range",
                        "above range": "Above Range",
                        "below range": "Below Range",
                        "outlier": "Outlier",
                        "invalid": "Invalid"
                    }
                    if orig_clean_flag in valid_flags:
                        row['test_analytics'] = valid_flags[orig_clean_flag]
                
                # Page numbers & duplicates fields
                row['page_no'] = str(page_no) if page_no is not None else None
                row['page_number'] = str(page_no) if page_no is not None else None
                
                row['report_details_page_no'] = str(page_no) if page_no is not None else None
                row['report_details_range'] = orig_range
                row['report_details_result'] = orig_result
                row['report_details_test_analytics'] = orig_analytics
                row['report_details_test_name'] = orig_name
                row['report_details_unit'] = orig_unit
                row['test_name'] = orig_name
                
                rows.append(row)
                
    elif rec_type == 'discharge_summary':
        # Standardise date fields
        base_row['admission_date'] = normalize_date(raw_data.get('admissionDate'))
        base_row['discharge_date'] = normalize_date(raw_data.get('dischargeDate'))
        base_row['diagnosis'] = raw_data.get('diagnosis')
        base_row['brief_history'] = raw_data.get('briefHistory')
        base_row['general_examinations'] = raw_data.get('generalExaminations')
        base_row['recommendations'] = raw_data.get('recommendations')
        
        discharge_meds = raw_data.get('dischargeMedications', [])
        if not discharge_meds:
            # Fallback to single empty row if no medicines are present (Section 5)
            row = base_row.copy()
            row['id'] = make_id(row['claim_no'], row['document_id'], row['record_type'], "empty_discharge")
            rows.append(row)
        else:
            for idx, med in enumerate(discharge_meds):
                row = base_row.copy()
                med_name = med.get('medicine')
                
                # Deterministic ID includes claim_no, document_id, record_type, and discriminator (original medicine name + index)
                row_id = make_id(row['claim_no'], row['document_id'], row['record_type'], f"{med_name or 'none'}|{idx}")
                row['id'] = row_id
                
                med_dose = med.get('dose')
                med_freq = med.get('frequency')
                
                # Medication map
                canon_med, med_type = map_medicine(med_name, med_dict)
                row['medicine'] = canon_med
                row['medication_medicine'] = med_name
                row['medication_name'] = med_name
                row['discharge_medications_medicine'] = med_name
                
                row['dose'] = med_dose
                row['medication_dose'] = med_dose
                row['discharge_medications_dose'] = med_dose
                
                row['frequency'] = med_freq
                row['medication_frequency'] = med_freq
                row['discharge_medications_frequency'] = med_freq
                
                row['medicine_type'] = med_type
                
                rows.append(row)
                
    else:
        # Generic record identification
        row = base_row.copy()
        row['id'] = make_id(row['claim_no'], row['document_id'], row['record_type'], "generic_doc")
        rows.append(row)
        
    return rows
