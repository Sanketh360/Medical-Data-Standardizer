import csv
import os

TYPE_MAP = {
    "STRING": "VARCHAR(128)",
    "FLOAT64": "DOUBLE",
    "TIMESTAMP": "TIMESTAMP"
}

LONG_TEXT_FIELDS = {
    "diagnosis", "brief_history", "general_examinations", "recommendations", 
    "hospital_address", "post_discharge_advice", "medicine_injections_investigation",
    "metadetails", "other_med_inj_investigations", "course_during_hospitalisation",
    "course_during_hospitalization", "result_text_original", "range_text_original",
    "error_message", "raw_payload",
    "result_text", "result", "range_text", "range", "test_name_original", "test_name",
    "report_details_range", "report_details_result", "report_details_test_name"
}

def build_ddl(csv_path, out_path):
    rows = list(csv.DictReader(open(csv_path, encoding='utf-8')))
    
    cols = []
    for r in rows:
        col_name = r['column_name']
        data_type = r['data_type']
        
        # We handle 'id' separately to make it primary key
        if col_name == 'id':
            cols.append(f"    `id` VARCHAR(64) PRIMARY KEY")
            continue
            
        sql_type = TYPE_MAP.get(data_type, "VARCHAR(128)")
        
        # Override long text fields to TEXT
        if col_name in LONG_TEXT_FIELDS:
            sql_type = "TEXT"
        
        # Override processed_at and ingested_at defaults
        if col_name == 'processed_at':
            cols.append(f"    `processed_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
        elif col_name == 'ingested_at':
            cols.append(f"    `ingested_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        else:
            cols.append(f"    `{col_name}` {sql_type} NULL")
            
    # Add operational columns (except processed_at which is already in CSV)
    cols.append("    processing_status VARCHAR(16) DEFAULT 'processed'")
    cols.append("    duplicate_flag BOOLEAN DEFAULT FALSE")
    cols.append("    error_message TEXT NULL")
    
    # Add Unique Index
    cols.append("    UNIQUE KEY uq_dedupe (claim_no(100), document_id(100), record_type(50), test_name_original(100), medicine(100), id(64))")
    
    ddl = "CREATE DATABASE IF NOT EXISTS medical_data_standardisation CHARACTER SET utf8mb4;\n"
    ddl += "USE medical_data_standardisation;\n\n"
    
    ddl += "DROP TABLE IF EXISTS standardized_records;\n"
    ddl += "CREATE TABLE standardized_records (\n"
    ddl += ",\n".join(cols)
    ddl += "\n) ENGINE=InnoDB;\n\n"
    
    ddl += "DROP TABLE IF EXISTS ingestion_errors;\n"
    ddl += """CREATE TABLE ingestion_errors (
    error_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    file_path     VARCHAR(512),
    document_id   VARCHAR(64) NULL,
    stage         VARCHAR(32),        -- ingest | standardize | validate | load
    error_reason  TEXT,
    raw_payload   LONGTEXT,
    occurred_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;\n\n"""

    ddl += "DROP TABLE IF EXISTS pipeline_runs;\n"
    ddl += """CREATE TABLE pipeline_runs (
    run_id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at     TIMESTAMP NULL,
    files_seen      INT DEFAULT 0,
    files_processed INT DEFAULT 0,
    files_failed    INT DEFAULT 0,
    records_flagged INT DEFAULT 0,
    duplicates_skipped INT DEFAULT 0
) ENGINE=InnoDB;\n"""
    
    with open(out_path, "w", encoding='utf-8') as f:
        f.write(ddl)
    print(f"Generated DDL at {out_path}")

if __name__ == "__main__":
    csv_file = os.path.join(os.path.dirname(__file__), "Ourput-table-ideal-schema.csv")
    sql_file = os.path.join(os.path.dirname(__file__), "schema.sql")
    build_ddl(csv_file, sql_file)
