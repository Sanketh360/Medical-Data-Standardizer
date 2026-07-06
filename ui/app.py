import os
import sys
from flask import Flask, render_template, request, jsonify, redirect, Response
import io
import csv
from fpdf import FPDF

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

class ExportPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 116, 139) # slate-500
        self.cell(0, 10, 'Veritas Claims Ingestion & Standardisation Engine', 0, 0, 'L')
        self.cell(0, 10, f'Page {self.page_no()}', 0, 1, 'R')
        self.line(10, 18, 287, 18)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(148, 163, 184) # slate-400
        self.cell(0, 10, 'Confidential Audit Export', 0, 0, 'C')

def generate_records_csv(records_list):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Claim Number", 
        "Document ID", 
        "Record Type", 
        "Patient Name", 
        "Hospital/Lab Name", 
        "Attending Doctor", 
        "Date", 
        "Clinical Item (Test/Med)", 
        "Value / Dose", 
        "Unit / Frequency", 
        "Reference Range", 
        "Status"
    ])
    for r in records_list:
        rec_type = r.get('record_type', '')
        if rec_type == 'lab_report':
            item_name = r.get('test_name_canonical') or r.get('test_name_original') or ""
            val = r.get('result_value') if r.get('result_value') is not None else r.get('result_text') or ""
            unit = r.get('unit_canonical') or r.get('unit_original') or ""
            ref = r.get('range_text') or (f"{r.get('range_low')}-{r.get('range_high')}" if r.get('range_low') is not None else "")
            date = r.get('reports_date') or r.get('bill_date') or ""
            status = r.get('test_analytics') or ""
        else:
            item_name = r.get('medicine') or r.get('medication_name') or ""
            val = r.get('dose') or ""
            unit = r.get('frequency') or ""
            ref = "N/A"
            date = r.get('admission_date') or r.get('discharge_date') or ""
            status = "Duplicate" if r.get('duplicate_flag') else (r.get('processing_status') or "")
        writer.writerow([
            r.get('claim_no') or "",
            r.get('document_id') or "",
            rec_type,
            r.get('patient_name') or "",
            r.get('hospital_name') or "",
            r.get('doctor_name') or "",
            date,
            item_name,
            val,
            unit,
            ref,
            status
        ])
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=records_export.csv"
    return response

def generate_records_pdf(records_list):
    pdf = ExportPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, 'Standardised Claims Records Audit Report', 0, 1, 'L')
    pdf.ln(5)
    
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_text_color(51, 65, 85)
    
    headers = ["Claim Number", "Document ID", "Type", "Patient Name", "Hospital/Lab", "Clinical Item", "Result / Dose", "Status"]
    widths = [35, 35, 25, 35, 40, 45, 35, 27]
    for h, w in zip(headers, widths):
        pdf.cell(w, 8, h, border=1, align='L', fill=True)
    pdf.ln(8)
    
    pdf.set_font('Courier', '', 7)
    pdf.set_text_color(33, 37, 41)
    
    for r in records_list:
        rec_type = r.get('record_type', '')
        if rec_type == 'lab_report':
            item_name = r.get('test_name_canonical') or r.get('test_name_original') or ""
            val = str(r.get('result_value') if r.get('result_value') is not None else r.get('result_text') or "")
            unit = r.get('unit_canonical') or r.get('unit_original') or ""
            res_str = f"{val} {unit}".strip()
            status = r.get('test_analytics') or ""
        else:
            item_name = r.get('medicine') or r.get('medication_name') or ""
            dose = r.get('dose') or ""
            freq = r.get('frequency') or ""
            res_str = f"{dose} ({freq})".strip()
            status = "Duplicate" if r.get('duplicate_flag') else (r.get('processing_status') or "")
            
        row_data = [
            str(r.get('claim_no') or ""),
            str(r.get('document_id') or ""),
            str(rec_type),
            str(r.get('patient_name') or ""),
            str(r.get('hospital_name') or ""),
            str(item_name),
            str(res_str),
            str(status)
        ]
        cleaned_row = [x.encode('latin-1', 'replace').decode('latin-1') for x in row_data]
        
        for x, w in zip(cleaned_row, widths):
            max_char = int(w * 1.5)
            if len(x) > max_char:
                x = x[:max_char-3] + "..."
            pdf.cell(w, 6, x, border=1, align='L')
        pdf.ln(6)
        
    pdf_bytes = pdf.output()
    response = Response(pdf_bytes, mimetype="application/pdf")
    response.headers["Content-Disposition"] = "attachment; filename=records_export.pdf"
    return response

def generate_flagged_csv(records_list):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Claim Number",
        "Patient Name",
        "Test / Medicine Name",
        "Result Text",
        "Parsed Value",
        "Normal Reference Bounds",
        "Anomaly Deviation",
        "Warning Details"
    ])
    for r in records_list:
        rec_type = r.get('record_type', '')
        if rec_type == 'lab_report':
            item_name = r.get('test_name_canonical') or r.get('test_name_original') or ""
            res_text = r.get('result_text') or ""
            val = str(r.get('result_value') if r.get('result_value') is not None else "")
            bounds = f"{r.get('range_low') or 'None'} - {r.get('range_high') or 'None'}"
            deviation = r.get('test_analytics') or ""
            warning = r.get('error_message') or ""
        else:
            item_name = r.get('medicine') or r.get('medication_name') or ""
            res_text = r.get('medication_dose') or ""
            val = r.get('dose') or ""
            bounds = "N/A"
            deviation = "Duplicate" if r.get('duplicate_flag') else (r.get('processing_status') or "")
            warning = r.get('error_message') or ""
        writer.writerow([
            r.get('claim_no') or "",
            r.get('patient_name') or "",
            item_name,
            res_text,
            val,
            bounds,
            deviation,
            warning
        ])
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=flagged_export.csv"
    return response

def generate_flagged_pdf(records_list):
    pdf = ExportPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, 'Flagged Anomalies Queue Audit Report', 0, 1, 'L')
    pdf.ln(5)
    
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_text_color(51, 65, 85)
    
    headers = ["Claim Number", "Patient Name", "Test/Medicine Name", "Result Text", "Parsed Value", "Ref Bounds", "Deviation", "Warnings"]
    widths = [35, 35, 45, 35, 30, 32, 30, 40]
    for h, w in zip(headers, widths):
        pdf.cell(w, 8, h, border=1, align='L', fill=True)
    pdf.ln(8)
    
    pdf.set_font('Courier', '', 7)
    pdf.set_text_color(33, 37, 41)
    
    for r in records_list:
        rec_type = r.get('record_type', '')
        if rec_type == 'lab_report':
            item_name = r.get('test_name_canonical') or r.get('test_name_original') or ""
            res_text = r.get('result_text') or ""
            val = str(r.get('result_value') if r.get('result_value') is not None else "")
            bounds = f"{r.get('range_low') or 'None'}-{r.get('range_high') or 'None'}"
            deviation = r.get('test_analytics') or ""
            warning = r.get('error_message') or ""
        else:
            item_name = r.get('medicine') or r.get('medication_name') or ""
            res_text = r.get('medication_dose') or ""
            val = r.get('dose') or ""
            bounds = "N/A"
            deviation = "Duplicate" if r.get('duplicate_flag') else (r.get('processing_status') or "")
            warning = r.get('error_message') or ""
            
        row_data = [
            str(r.get('claim_no') or ""),
            str(r.get('patient_name') or ""),
            str(item_name),
            str(res_text),
            str(val),
            str(bounds),
            str(deviation),
            str(warning)
        ]
        cleaned_row = [x.encode('latin-1', 'replace').decode('latin-1') for x in row_data]
        
        for x, w in zip(cleaned_row, widths):
            max_char = int(w * 1.5)
            if len(x) > max_char:
                x = x[:max_char-3] + "..."
            pdf.cell(w, 6, x, border=1, align='L')
        pdf.ln(6)
        
    pdf_bytes = pdf.output()
    response = Response(pdf_bytes, mimetype="application/pdf")
    response.headers["Content-Disposition"] = "attachment; filename=flagged_export.pdf"
    return response

@app.route('/export/records/<format>')
def export_records(format):
    search = request.args.get('search', '')
    rec_type = request.args.get('type', '')
    status = request.args.get('status', '')
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    query = "SELECT * FROM standardized_records WHERE 1=1"
    params = []
    
    if search:
        query += " AND (patient_name LIKE %s OR document_id LIKE %s OR claim_no LIKE %s)"
        search_param = f"%{search}%"
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
    offset = (page - 1) * PAGE_SIZE
    params.extend([PAGE_SIZE, offset])
    
    records_list = query_db(query, params)
    
    if format == 'csv':
        return generate_records_csv(records_list)
    elif format == 'pdf':
        return generate_records_pdf(records_list)
    else:
        return "Invalid format", 400

@app.route('/export/flagged/<format>')
def export_flagged(format):
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    query = """
        SELECT * FROM standardized_records 
        WHERE processing_status = 'flagged' OR test_analytics <> 'Within Range'
        ORDER BY processed_at DESC
        LIMIT %s OFFSET %s
    """
    offset = (page - 1) * PAGE_SIZE
    records_list = query_db(query, [PAGE_SIZE, offset])
    
    if format == 'csv':
        return generate_flagged_csv(records_list)
    elif format == 'pdf':
        return generate_flagged_pdf(records_list)
    else:
        return "Invalid format", 400

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
