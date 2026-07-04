# Assumptions and Design Decisions

This document outlines the core engineering assumptions, design choices, and scoping exclusions for the Veritas Claims Medical Data Standardisation prototype.

---

## 1. clinical row grain decisions

**Design Choice: One row per medication or lab test (Flattening).**
- **Reasoning**:
  1. **Consistency**: Lab reports naturally translate to one row per test (exploding the `report_details` array). Exploding the `dischargeMedications` array in the same way establishes a uniform, clean, and singular flattening rule across the whole ETL pipeline.
  2. **Queryability**: Storing one row per medication makes it straightforward to run relational queries (e.g., `SELECT * FROM standardized_records WHERE medicine = 'Paracetamol'`). If medications were stored as a JSON array or a comma-separated cell string, query performance would suffer and require complex, database-specific JSON functions.
  3. **Data Volume**: The maximum medication count in the sample files is 18. Replicating the visit metadata (demographics, hospital, diagnosis) for 18 rows is negligible in terms of database storage and I/O overhead.
- **Production Tradeoff**: In a high-throughput production system with hundreds of medications per summary, this row replication would consume storage. The production evolution would be to decouple demographic/visit header records from detail rows (Tests and Medications) into separate normalized tables (`claims`, `clinical_tests`, and `claim_medications`).

---

## 2. Hospital config variability & redaction strategy

**Design Choice: Config variations are keyed on Document Type rather than Clinic/Hospital.**
- **Reasoning**:
  1. **Redacted Data**: Every occurrence of `hospitalName` and `lab_or_hospital_name` in the provided sample data is redacted (e.g., `"[HOSPITAL NAME REDACTED]"`). We cannot demonstrate or test clinic-specific overrides (`fortis.yaml`, `max.yaml`) against data that contains identical redacted strings.
  2. **Zero-Code Onboarding**: The prototype fulfills the onboarding requirement by split-routing mappings: trying document-type specific configuration first (`discharge_summary.yaml` / `lab_report.yaml`), and falling back to a global `field_aliases.yaml` list.
- **Production Evolution**: Once real clinic identifiers are available, we would add a third, highest-priority layer of configuration lookup: `config/clinics/{clinic_id}.yaml`. This layer would override specific field mapping paths, leaving the underlying document type and fallback aliases intact.

---

## 3. Idempotency and Deduplication hash

**Design Choice: Hash keys are generated deterministically using `claim_no` as a disambiguator.**
- **Reasoning**:
  - A primary key hash calculated purely on `document_id` and test names is insufficient. `document_id` values (e.g., `DOC01`) are only guaranteed unique *within* their origin source system.
  - If two different hospitals submit records using colliding document IDs, they would overwrite each other.
  - We incorporate `claim_no` (which is present in every file's `metaDetails` block) into our SHA256 key:
    `hash(claim_no + "|" + document_id + "|" + record_type + "|" + test_or_medicine_name)`
  - Using this primary key with `INSERT ... ON DUPLICATE KEY UPDATE` ensures the pipeline maintains strict idempotency.

---

## 4. Scope Exclusions and Out of Scope Items

- **GCS Integration**: Simulated locally using standard file directory paths.
- **Vocabulary Dictionaries**: Seeding is strictly limited to the tests, units, and medications present in the 5 sample files to ensure 100% test coverage without dummy records. Production implementation would replace these with RxNorm, LOINC, or internal clinical master lists.
- **Ingestion Mode**: Batch-processed locally. Production scale would use a streaming microservice (e.g., FastAPI + Celery / Apache Kafka) to trigger ingestion in real time.
- **PII Tokenisation**: Excluded as the sample data arrives with PII already redacted (e.g. `[PATIENT NAME REDACTED]`, `[AGE REDACTED]`).
- **Dashboard Authentication**: Omitted for developer simplicity.
