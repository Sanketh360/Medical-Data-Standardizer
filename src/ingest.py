import os
import json
from src.utils import load_yaml

def lookup_path(data_dict, path):
    """Retrieve values from a dictionary using dot-separated paths (e.g., 'basic_info.patient_name')."""
    if not path or not isinstance(data_dict, dict):
        return None
    keys = path.split('.')
    curr = data_dict
    for key in keys:
        if isinstance(curr, dict) and key in curr:
            curr = curr[key]
        else:
            return None
    return curr

def resolve_field(data_dict, field_name, doc_config, alias_config):
    """
    Resolve a field value from document data using:
    1. Document-type specific mappings.
    2. Fallback field aliases list.
    """
    # 1. Try document-type specific mapping
    doc_fields = doc_config.get('fields', {})
    if field_name in doc_fields:
        mapped_path = doc_fields[field_name]
        val = lookup_path(data_dict, mapped_path)
        if val is not None and val != "":
            return val
            
    # 2. Try generic field aliases
    aliases = alias_config.get(field_name, [])
    for alias in aliases:
        val = lookup_path(data_dict, alias)
        if val is not None and val != "":
            return val
            
    return None

def ingest_file(file_path, doc_configs, alias_config):
    """
    Ingest a single JSON file.
    Returns: (list of parsed records, error_dict or None)
    """
    file_name = os.path.basename(file_path)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except json.JSONDecodeError as jde:
        # Capture raw payload for audit trail (FR-4.3)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_text = f.read()
        except Exception:
            raw_text = "Could not read file text"
            
        error_info = {
            'file_path': file_path,
            'document_id': None,
            'stage': 'ingest',
            'error_reason': f"JSONDecodeError: {str(jde)}",
            'raw_payload': raw_text
        }
        return [], error_info
    except Exception as e:
        error_info = {
            'file_path': file_path,
            'document_id': None,
            'stage': 'ingest',
            'error_reason': f"FileError: {str(e)}",
            'raw_payload': ""
        }
        return [], error_info

    parsed_records = []
    
    # Check trace details
    trace_id = payload.get('traceId')
    data_node = payload.get('data', {})
    correlation_id = data_node.get('correlationId')
    document_id = data_node.get('documentId')
    meta_details = data_node.get('metaDetails', [])
    
    # Parse metaDetails array of key/value pairs
    meta_map = {}
    if isinstance(meta_details, list):
        for item in meta_details:
            if isinstance(item, dict) and 'key' in item and 'value' in item:
                meta_map[item['key']] = item['value']
                
    # Extract meta fields
    claim_no = meta_map.get('claim_no')
    nt_code = meta_map.get('nt_code')
    source_system = meta_map.get('source_system')
    consumer_client_id = meta_map.get('ConsumerClientId')
    destination_identifier = meta_map.get('DestinationIdentifier')
    
    response_details = data_node.get('responseDetails', [])
    if not isinstance(response_details, list):
        response_details = []
        
    for detail in response_details:
        if not isinstance(detail, dict):
            continue
            
        classifier = detail.get('classifier')
        detail_data = detail.get('data', {})
        
        # Select matching document configuration
        doc_config = doc_configs.get(classifier, {})
        
        # Resolve basic demographic and clinical header fields
        patient_name = resolve_field(detail_data, 'patient_name', doc_config, alias_config)
        age = resolve_field(detail_data, 'age', doc_config, alias_config)
        gender = resolve_field(detail_data, 'gender', doc_config, alias_config)
        hospital_name = resolve_field(detail_data, 'hospital_name', doc_config, alias_config)
        doctor_name = resolve_field(detail_data, 'doctor_name', doc_config, alias_config)
        
        # Build common record header
        record_header = {
            'document_id': document_id,
            'record_type': classifier,
            'file_gcs_path': f"gs://medical-records/{file_name}",
            'trace_id': trace_id,
            'correlation_id': correlation_id,
            'source_system': source_system,
            'claim_no': claim_no,
            'nt_code': nt_code,
            'consumer_client_id': consumer_client_id,
            'destination_identifier': destination_identifier,
            'patient_name': patient_name,
            'age': age,
            'gender': gender,
            'hospital_name': hospital_name,
            'doctor_name': doctor_name,
            'raw_detail_data': detail_data,  # keep for extraction phase
            'raw_meta_details': json.dumps(meta_details) if meta_details else None
        }
        
        parsed_records.append(record_header)
        
    return parsed_records, None
