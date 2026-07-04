import os
import sys
import glob
import argparse
from src.utils import load_yaml
from src.ingest import ingest_file
from src.standardize import standardize_document
from src.db_loader import (
    start_pipeline_run,
    finish_pipeline_run,
    insert_standardized_records,
    log_db_error,
    reset_database
)

def run_pipeline(data_dir=None, reset=False):
    # Resolve project paths
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    if not data_dir:
        data_dir = os.path.join(project_root, "sample-data")
        
    config_dir = os.path.join(project_root, "config")
    
    print("Initializing Veritas Claims Pipeline Run...")
    
    if reset:
        reset_database()
    
    # 1. Start pipeline run logging in the database
    run_id = start_pipeline_run()
    print(f"Pipeline Run Started. Run ID: {run_id}")
    
    # 2. Load configurations
    doc_configs = {
        'discharge_summary': load_yaml(os.path.join(config_dir, "document_types", "discharge_summary.yaml")),
        'lab_report': load_yaml(os.path.join(config_dir, "document_types", "lab_report.yaml"))
    }
    alias_config = load_yaml(os.path.join(config_dir, "field_aliases.yaml"))
    test_dict = load_yaml(os.path.join(config_dir, "test_name_dictionary.yaml"))
    unit_conv = load_yaml(os.path.join(config_dir, "unit_conversion.yaml"))
    ref_ranges = load_yaml(os.path.join(config_dir, "reference_ranges.yaml"))
    med_dict = load_yaml(os.path.join(config_dir, "medicine_dictionary.yaml"))
    analytics_rules = load_yaml(os.path.join(config_dir, "analytics_rules.yaml"))
    
    # Check data directory
    if not os.path.exists(data_dir):
        print(f"Error: Data directory not found at {data_dir}", file=sys.stderr)
        finish_pipeline_run(run_id, 0, 0, 1, 0, 0)
        return
        
    # Search for all JSON files in the sample-data directory
    search_path = os.path.join(data_dir, "*.json")
    json_files = glob.glob(search_path)
    
    files_seen = len(json_files)
    files_processed = 0
    files_failed = 0
    records_flagged = 0
    duplicates_skipped = 0
    total_rows_inserted = 0
    
    print(f"Scanning directory: {data_dir}. Found {files_seen} files.")
    
    for fpath in json_files:
        fname = os.path.basename(fpath)
        print(f"Processing: {fname}...", end="")
        
        # Ingest file
        records, error_info = ingest_file(fpath, doc_configs, alias_config)
        
        if error_info:
            print(" FAILED (Ingestion Error)")
            # Log failure to database (FR-4.2)
            log_db_error(
                file_path=fpath,
                document_id=error_info.get('document_id'),
                stage=error_info.get('stage'),
                error_reason=error_info.get('error_reason'),
                raw_payload=error_info.get('raw_payload')
            )
            files_failed += 1
            continue
            
        # Standardise and flatten records
        flattened_rows = []
        for record_header in records:
            # Standardise document
            rows = standardize_document(
                record_header=record_header,
                unit_conv_dict=unit_conv,
                test_dict=test_dict,
                ref_ranges=ref_ranges,
                med_dict=med_dict,
                analytics_rules=analytics_rules
            )
            flattened_rows.extend(rows)
            
        # Apply validation checks and determine operational status flags
        for row in flattened_rows:
            # Outliers or Invalid results are flagged (FR-3.4 / FR-5.1)
            is_anomaly = row['test_analytics'] in ['Below Range', 'Above Range', 'Outlier', 'Invalid']
            if is_anomaly:
                row['processing_status'] = 'flagged'
                records_flagged += 1
            else:
                row['processing_status'] = 'processed'
                
            # If the result value is null and result text is not empty for lab reports,
            # this represents a parsing warning (e.g. Range-as-Result or non-numeric result)
            if row['record_type'] == 'lab_report' and row['result_value'] is None and row['result_text']:
                if row['test_analytics'] == 'Invalid':
                    row['error_message'] = "Value could not be parsed numerically (warning: text or range-as-result)."
                    row['processing_status'] = 'flagged'
                    # Count as flagged if not already counted
                    if not is_anomaly:
                        records_flagged += 1
                        
        # Load into database
        if flattened_rows:
            inserted, duplicates = insert_standardized_records(flattened_rows)
            total_rows_inserted += inserted
            duplicates_skipped += duplicates
            print(f" SUCCESS. Flattened into {len(flattened_rows)} rows (Inserted: {inserted}, Duplicates: {duplicates})")
        else:
            print(" SUCCESS (No records found)")
            
        files_processed += 1
        
    # 3. Finalize run logging in the database
    finish_pipeline_run(
        run_id=run_id,
        files_seen=files_seen,
        files_processed=files_processed,
        files_failed=files_failed,
        records_flagged=records_flagged,
        duplicates_skipped=duplicates_skipped
    )
    
    print("\n" + "="*40)
    print("Veritas Claims Pipeline Run Completed!")
    print(f"Total Files Scanned:  {files_seen}")
    print(f"Files Processed:      {files_processed}")
    print(f"Files Failed:         {files_failed}")
    print(f"Total Rows Inserted:  {total_rows_inserted}")
    print(f"Duplicates Flagged:   {duplicates_skipped}")
    print(f"Records Flagged (Anomalies): {records_flagged}")
    print("="*40)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Veritas Claims Ingestion & Standardisation Pipeline")
    parser.add_argument("--data-dir", help="Path to sample data folder containing JSON files")
    parser.add_argument("--reset", action="store_true", help="Clear all database tables before processing")
    args = parser.parse_args()
    
    run_pipeline(args.data_dir, reset=args.reset)
