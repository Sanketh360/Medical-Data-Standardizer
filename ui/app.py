import os
import sys
from flask import Flask, render_template, request, jsonify, redirect

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import get_db_connection
from src.pipeline import run_pipeline

app = Flask(__name__, template_folder='templates', static_folder='static')

def query_db(query, args=(), one=False):
    """Utility to execute a query and return results."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, args)
            rv = cur.fetchall()
        conn.commit()
    except Exception as e:
        print(f"Database query error: {e}", file=sys.stderr)
        rv = []
    finally:
        conn.close()
    return (rv[0] if rv else None) if one else rv

@app.route('/')
def index():
    # 1. Fetch KPI metrics (Latest run metrics instead of cumulative sum across history)
    latest_run = query_db("SELECT files_processed, files_failed FROM pipeline_runs ORDER BY started_at DESC LIMIT 1", one=True)
    if latest_run:
        total_files_processed = latest_run.get('files_processed', 0)
        total_files_failed = latest_run.get('files_failed', 0)
    else:
        total_files_processed = 0
        total_files_failed = 0
    
    total_flagged_res = query_db("SELECT COUNT(*) as val FROM standardized_records WHERE processing_status = 'flagged'", one=True)
    total_flagged = total_flagged_res.get('val') if total_flagged_res else 0
    
    total_records_res = query_db("SELECT COUNT(*) as val FROM standardized_records", one=True)
    total_records = total_records_res.get('val') if total_records_res else 0
    
    total_runs_res = query_db("SELECT COUNT(*) as val FROM pipeline_runs", one=True)
    total_runs = total_runs_res.get('val') if total_runs_res else 0
    
    total_duplicates_res = query_db("SELECT COUNT(*) as val FROM standardized_records WHERE duplicate_flag = TRUE", one=True)
    total_duplicates = total_duplicates_res.get('val') if total_duplicates_res else 0
    
    # 2. Fetch Recent Pipeline Runs
    pipeline_runs = query_db("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 10")
    
    # 3. Fetch Clinic/Document Type Summary
    summary_query = """
        SELECT 
            COALESCE(hospital_name, 'Redacted / Unknown') as hospital_name,
            record_type,
            COUNT(*) as total_records,
            SUM(CASE WHEN processing_status = 'flagged' THEN 1 ELSE 0 END) as flagged_count,
            SUM(CASE WHEN duplicate_flag = TRUE THEN 1 ELSE 0 END) as duplicate_count
        FROM standardized_records
        GROUP BY hospital_name, record_type
    """
    clinic_summaries = query_db(summary_query)
    
    return render_template(
        'index.html',
        total_files_processed=total_files_processed,
        total_files_failed=total_files_failed,
        total_flagged=total_flagged,
        total_records=total_records,
        total_runs=total_runs,
        total_duplicates=total_duplicates,
        pipeline_runs=pipeline_runs,
        clinic_summaries=clinic_summaries
    )

PAGE_SIZE = 100
CHUNK_SIZE = 20

@app.route('/records')
def records():
    search = request.args.get('search', '')
    rec_type = request.args.get('type', '')
    status = request.args.get('status', '')
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1
        
    try:
        chunk = int(request.args.get('chunk', 0))
        if chunk < 0:
            chunk = 0
    except ValueError:
        chunk = 0

    # 1. Fetch total records matching filters to calculate total pages
    count_query = "SELECT COUNT(*) as cnt FROM standardized_records WHERE 1=1"
    count_params = []
    
    if search:
        count_query += " AND (patient_name LIKE %s OR document_id LIKE %s OR claim_no LIKE %s)"
        search_param = f"%{search}%"
        count_params.extend([search_param, search_param, search_param])
        
    if rec_type:
        count_query += " AND record_type = %s"
        count_params.append(rec_type)
        
    if status:
        if status == 'duplicate':
            count_query += " AND duplicate_flag = TRUE"
        elif status == 'processed':
            count_query += " AND processing_status = 'processed' AND (duplicate_flag = FALSE OR duplicate_flag IS NULL)"
        else:
            count_query += " AND processing_status = %s"
            count_params.append(status)

    count_res = query_db(count_query, count_params, one=True)
    total_records = count_res['cnt'] if count_res else 0
    
    import math
    total_pages = math.ceil(total_records / PAGE_SIZE)
    if total_pages < 1:
        total_pages = 1
        
    if page > total_pages:
        page = total_pages
        
    # 2. Fetch the records for current chunk of the page
    offset = (page - 1) * PAGE_SIZE + chunk * CHUNK_SIZE
    
    query = "SELECT * FROM standardized_records WHERE 1=1"
    params = []
    
    if search:
        query += " AND (patient_name LIKE %s OR document_id LIKE %s OR claim_no LIKE %s)"
        params.extend([search_param, search_param, search_param])
        
    if rec_type:
        query += " AND record_type = %s"
        params.append(rec_type)
        
    if status:
        if status == 'duplicate':
            query += " AND duplicate_flag = TRUE"
        elif status == 'processed':
            query += " AND processing_status = 'processed' AND (duplicate_flag = FALSE OR duplicate_flag IS NULL)"
        else:
            query += " AND processing_status = %s"
            params.append(status)
            
    query += " ORDER BY processed_at DESC LIMIT %s OFFSET %s"
    params.extend([CHUNK_SIZE, offset])
    
    records_list = query_db(query, params)
    
    is_ajax = request.args.get('ajax') == '1'
    if is_ajax:
        return render_template('records_rows.html', records=records_list, is_initial=(chunk == 0))
        
    has_prev = page > 1
    has_next = page < total_pages
    
    return render_template(
        'records.html', 
        records=records_list, 
        search=search, 
        type=rec_type, 
        status=status, 
        current_page=page, 
        total_pages=total_pages,
        total_records=total_records,
        has_prev=has_prev,
        has_next=has_next,
        is_initial=True
    )

@app.route('/record/<record_id>')
def get_record(record_id):
    """Retrieve detailed properties of a single standardized record (returns JSON for inspector)."""
    record = query_db("SELECT * FROM standardized_records WHERE id = %s", (record_id,), one=True)
    if not record:
        return jsonify({'error': 'Record not found'}), 404
    return jsonify(record)

@app.route('/flagged')
def flagged():
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1
        
    try:
        chunk = int(request.args.get('chunk', 0))
        if chunk < 0:
            chunk = 0
    except ValueError:
        chunk = 0
        
    # 1. Fetch total flagged records to calculate total pages
    count_query = """
        SELECT COUNT(*) as cnt FROM standardized_records 
        WHERE processing_status = 'flagged' OR test_analytics <> 'Within Range'
    """
    count_res = query_db(count_query, one=True)
    total_records = count_res['cnt'] if count_res else 0
    
    import math
    total_pages = math.ceil(total_records / PAGE_SIZE)
    if total_pages < 1:
        total_pages = 1
        
    if page > total_pages:
        page = total_pages
        
    # 2. Fetch the records for current chunk of the page
    offset = (page - 1) * PAGE_SIZE + chunk * CHUNK_SIZE
    
    # Anomaly queue lists records where validation failed or results are out of bounds
    flagged_records = query_db("""
        SELECT * FROM standardized_records 
        WHERE processing_status = 'flagged' OR test_analytics <> 'Within Range'
        ORDER BY processed_at DESC
        LIMIT %s OFFSET %s
    """, [CHUNK_SIZE, offset])
    
    is_ajax = request.args.get('ajax') == '1'
    if is_ajax:
        return render_template('flagged_rows.html', records=flagged_records, is_initial=(chunk == 0))
        
    has_prev = page > 1
    has_next = page < total_pages
    
    return render_template(
        'flagged.html', 
        records=flagged_records, 
        current_page=page, 
        total_pages=total_pages,
        total_records=total_records,
        has_prev=has_prev,
        has_next=has_next,
        is_initial=True
    )

@app.route('/errors')
def errors():
    # Audit trail for failed files and JSON parsing errors
    ingestion_errors = query_db("SELECT * FROM ingestion_errors ORDER BY occurred_at DESC")
    return render_template('errors.html', errors=ingestion_errors)

@app.route('/run-pipeline', methods=['POST'])
def trigger_pipeline():
    """Trigger the ingestion and standardisation pipeline synchronously from the dashboard."""
    try:
        run_pipeline(reset=True)
        return jsonify({'status': 'success', 'message': 'Pipeline run reset and completed successfully!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Pipeline run failed: {str(e)}"}), 500

@app.route('/clear-history', methods=['POST'])
def clear_history():
    """Clear all records from the pipeline_runs table."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cur.execute("TRUNCATE TABLE pipeline_runs;")
            cur.execute("SET FOREIGN_KEY_CHECKS = 1;")
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Pipeline run history cleared successfully!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Failed to clear history: {str(e)}"}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    # Pre-seed database with a fresh load on server start
    # We check WERKZEUG_RUN_MAIN to prevent the Flask reloader from running it twice in debug mode
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        try:
            print("Pre-seeding database with fresh load on server start...")
            run_pipeline(reset=True)
        except Exception as e:
            print(f"Failed to pre-seed database: {e}", file=sys.stderr)

    # Listen on localhost:5000
    app.run(debug=True, host='localhost', port=5000)
