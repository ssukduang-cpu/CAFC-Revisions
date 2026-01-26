# Ingestion module for CAFC opinions
from backend.ingest.run import ingest_document, ingest_document_from_url, run_batch_ingest

__all__ = ["ingest_document", "ingest_document_from_url", "run_batch_ingest"]
