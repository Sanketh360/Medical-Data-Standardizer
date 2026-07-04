import sys
import pymysql
from database.connection import get_db_connection

def insert_standardized_records(records):
    """
    Inserts or updates standardized records in MySQL.
    """
    if not records:
        return 0, 0
        
    connection = get_db_connection()
    inserted_count = 0
    duplicate_count = 0
    
    try:
        # Clean records to leverage MySQL defaults for timestamps, and ensure operational keys exist
        for record in records:
            record.pop('processed_at', None)
            record.pop('ingested_at', None)
            record['duplicate_flag'] = False
            record.setdefault('error_message', None)

        with connection.cursor() as cursor:
            # We dynamically build the SQL query based on the fields of the first record
            # to accommodate all 78 schema columns.
            sample_record = records[0]
            columns = list(sample_record.keys())
            
            escaped_cols = [f"`{col}`" for col in columns]
            placeholders = [f"%({col})s" for col in columns]
            
            # Build ON DUPLICATE KEY UPDATE clause
            update_clauses = []
            for col in columns:
                if col == 'id':
                    continue
                # Mark as duplicate if a conflict occurs
                if col == 'duplicate_flag':
                    update_clauses.append("`duplicate_flag` = TRUE")
                else:
                    update_clauses.append(f"`{col}` = VALUES(`{col}`)")
                    
            sql = f"""
                INSERT INTO standardized_records ({', '.join(escaped_cols)})
                VALUES ({', '.join(placeholders)})
                ON DUPLICATE KEY UPDATE {', '.join(update_clauses)}
            """
            
            # Execute records one by one to count updates vs inserts
            for record in records:
                try:
                    cursor.execute(sql, record)
                    # MySQL rowcount: 1 = inserted, 2 = updated (changed), 0 = updated (no change)
                    if cursor.rowcount == 1:
                        inserted_count += 1
                    else:
                        duplicate_count += 1
                except Exception as e:
                    print(f"Error inserting record ID {record.get('id')}: {e}", file=sys.stderr)
                    # We write to ingestion errors
                    log_db_error('standardized_records', record.get('document_id'), 'load', f"RecordLoadError: {str(e)}", str(record))
                    
        connection.commit()
    finally:
        connection.close()
        
    return inserted_count, duplicate_count

def log_db_error(file_path, document_id, stage, error_reason, raw_payload):
    """Insert error log into ingestion_errors table."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO ingestion_errors (file_path, document_id, stage, error_reason, raw_payload)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (file_path, document_id, stage, error_reason, raw_payload))
        connection.commit()
    except Exception as e:
        print(f"Failed to log error to DB: {e}", file=sys.stderr)
    finally:
        connection.close()

def start_pipeline_run():
    """Log the start of a pipeline run in pipeline_runs."""
    connection = get_db_connection()
    run_id = None
    try:
        with connection.cursor() as cursor:
            sql = "INSERT INTO pipeline_runs (started_at) VALUES (CURRENT_TIMESTAMP)"
            cursor.execute(sql)
            run_id = cursor.lastrowid
        connection.commit()
    finally:
        connection.close()
    return run_id

def finish_pipeline_run(run_id, files_seen, files_processed, files_failed, records_flagged, duplicates_skipped):
    """Update pipeline_runs record upon completion."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                UPDATE pipeline_runs 
                SET finished_at = CURRENT_TIMESTAMP,
                    files_seen = %s,
                    files_processed = %s,
                    files_failed = %s,
                    records_flagged = %s,
                    duplicates_skipped = %s
                WHERE run_id = %s
            """
            cursor.execute(sql, (files_seen, files_processed, files_failed, records_flagged, duplicates_skipped, run_id))
        connection.commit()
    finally:
        connection.close()

def reset_database():
    """Wipes the database tables to start with a fresh state, preserving run history telemetry."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("TRUNCATE TABLE standardized_records;")
            cursor.execute("TRUNCATE TABLE ingestion_errors;")
            # We do not truncate pipeline_runs to preserve execution history in the dashboard
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        connection.commit()
        print("Database clinical tables truncated successfully. Running fresh load...")
    finally:
        connection.close()
