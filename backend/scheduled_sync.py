"""
Scheduled sync module for weekly CAFC opinion updates.
Fetches new precedential opinions from CourtListener and ingests them.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import requests

from backend import db_postgres as db

logger = logging.getLogger(__name__)

COURTLISTENER_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
COURTLISTENER_API_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN", "")

def get_session() -> requests.Session:
    session = requests.Session()
    headers = {
        'User-Agent': 'Federal-Circuit-AI-Research/1.0 (legal research tool)',
        'Accept': 'application/json',
    }
    if COURTLISTENER_API_TOKEN:
        headers['Authorization'] = f'Token {COURTLISTENER_API_TOKEN}'
    session.headers.update(headers)
    return session

def get_last_sync_date() -> Optional[str]:
    """Get the date of the last successful sync from sync_history table."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT completed_at 
                FROM sync_history 
                WHERE status = 'completed' 
                ORDER BY completed_at DESC 
                LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row.get('completed_at'):
                return row['completed_at'].strftime("%Y-%m-%d")
    except Exception as e:
        logger.error(f"Error getting last sync date: {e}")
    return None

def get_latest_document_date() -> Optional[str]:
    """Get the date of the most recent document in the database."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT release_date 
                FROM documents 
                ORDER BY release_date DESC 
                LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row.get('release_date'):
                return row['release_date']
    except Exception as e:
        logger.error(f"Error getting latest document date: {e}")
    return None

def create_sync_record(sync_type: str) -> str:
    """Create a new sync history record and return its ID."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sync_history (id, sync_type, status, started_at)
                VALUES (gen_random_uuid(), %s, 'running', NOW())
                RETURNING id
            """, (sync_type,))
            sync_id = cursor.fetchone()['id']
            conn.commit()
            return sync_id
    except Exception as e:
        logger.error(f"Error creating sync record: {e}")
        raise

def update_sync_record(sync_id: str, status: str, found: int = 0, ingested: int = 0, 
                       error_msg: Optional[str] = None, date_range: Optional[str] = None):
    """Update a sync history record."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sync_history 
                SET status = %s, 
                    completed_at = NOW(),
                    new_opinions_found = %s,
                    new_opinions_ingested = %s,
                    error_message = %s,
                    last_synced_date = %s
                WHERE id = %s
            """, (status, found, ingested, error_msg, date_range, sync_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating sync record: {e}")

def fetch_new_opinions(filed_after: str, max_retries: int = 3) -> List[Dict[str, Any]]:
    """Fetch new CAFC opinions from CourtListener since the given date."""
    import time
    session = get_session()
    opinions = []
    next_url = None
    
    logger.info(f"Fetching CAFC opinions filed after {filed_after}")
    
    while True:
        for attempt in range(max_retries):
            try:
                if next_url:
                    resp = session.get(next_url, timeout=60)
                else:
                    params = {
                        'type': 'o',
                        'court': 'cafc',
                        'stat_Published': 'on',
                        'order_by': 'dateFiled desc',
                        'filed_after': filed_after,
                    }
                    resp = session.get(f"{COURTLISTENER_BASE_URL}/search/", params=params, timeout=60)
                
                resp.raise_for_status()
                data = resp.json()
                
                results = data.get('results', [])
                for result in results:
                    if is_opinion_document(result):
                        parsed = parse_opinion_result(result)
                        if parsed.get('courtlistener_cluster_id') or parsed.get('pdf_url'):
                            opinions.append(parsed)
                        else:
                            logger.warning(f"Skipping opinion without valid ID: {result.get('caseName')}")
                
                next_url = data.get('next')
                break
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"Max retries reached, stopping fetch")
                    next_url = None
            except Exception as e:
                logger.error(f"Error fetching opinions: {e}")
                next_url = None
                break
        
        if not next_url:
            break
            
        time.sleep(0.5)
    
    logger.info(f"Found {len(opinions)} new opinions")
    return opinions

def is_opinion_document(result: Dict) -> bool:
    """Check if result is an opinion (not order, judgment, etc.)."""
    case_name = result.get('caseName', '').lower()
    skip_patterns = ['order', 'judgment', 'errat', 'rule 36']
    for pattern in skip_patterns:
        if pattern in case_name:
            return False
    return True

def parse_opinion_result(result: Dict) -> Dict[str, Any]:
    """Parse a CourtListener search result into our opinion format."""
    docket_numbers = result.get('docketNumber', '')
    if isinstance(docket_numbers, list):
        appeal_number = docket_numbers[0] if docket_numbers else ''
    else:
        appeal_number = docket_numbers
    
    pdf_url = None
    if result.get('download_url'):
        pdf_url = result['download_url']
    elif result.get('local_path'):
        pdf_url = f"https://storage.courtlistener.com/{result['local_path']}"
    
    cluster_id = result.get('cluster_id')
    courtlistener_url = f"https://www.courtlistener.com/opinion/{cluster_id}/" if cluster_id else None
    
    return {
        'case_name': result.get('caseName', 'Unknown'),
        'appeal_number': appeal_number,
        'release_date': result.get('dateFiled', ''),
        'pdf_url': pdf_url,
        'courtlistener_cluster_id': cluster_id,
        'courtlistener_url': courtlistener_url,
        'origin': 'CourtListener',
        'status': 'Precedential',
        'document_type': 'OPINION',
    }

def opinion_exists(cluster_id: Optional[str], appeal_number: str, pdf_url: Optional[str]) -> bool:
    """Check if an opinion already exists in the database.
    
    Deduplication priority:
    1. courtlistener_cluster_id (most reliable)
    2. pdf_url (unique constraint)
    3. appeal_number (may have false positives for consolidated cases)
    """
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            if cluster_id:
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM documents 
                    WHERE courtlistener_cluster_id = %s
                """, (cluster_id,))
                if cursor.fetchone()['cnt'] > 0:
                    return True
            if pdf_url:
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM documents 
                    WHERE pdf_url = %s
                """, (pdf_url,))
                if cursor.fetchone()['cnt'] > 0:
                    return True
            if appeal_number and appeal_number.strip():
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM documents 
                    WHERE appeal_number = %s
                """, (appeal_number,))
                if cursor.fetchone()['cnt'] > 0:
                    return True
            return False
    except Exception as e:
        logger.error(f"Error checking opinion existence: {e}")
        return True

def add_opinion_to_manifest(opinion: Dict[str, Any]) -> Optional[str]:
    """Add a new opinion to the documents table and return its ID."""
    if not opinion.get('pdf_url'):
        logger.warning(f"Skipping opinion without PDF URL: {opinion.get('case_name')}")
        return None
    
    if opinion_exists(
        opinion.get('courtlistener_cluster_id'),
        opinion.get('appeal_number', ''),
        opinion.get('pdf_url')
    ):
        logger.debug(f"Opinion already exists: {opinion.get('case_name')}")
        return None
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO documents (
                    id, case_name, appeal_number, release_date, pdf_url,
                    status, origin, document_type, courtlistener_url, courtlistener_cluster_id
                ) VALUES (
                    gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (pdf_url) DO NOTHING
                RETURNING id
            """, (
                opinion['case_name'],
                opinion.get('appeal_number', ''),
                opinion['release_date'],
                opinion['pdf_url'],
                opinion['status'],
                opinion['origin'],
                opinion['document_type'],
                opinion.get('courtlistener_url'),
                opinion.get('courtlistener_cluster_id'),
            ))
            result = cursor.fetchone()
            conn.commit()
            if result:
                logger.info(f"Added new opinion: {opinion['case_name']}")
                return result['id']
            return None
    except Exception as e:
        logger.error(f"Error adding opinion: {e}")
        return None

async def ingest_new_opinions(doc_ids: List[str], limit: int = 50) -> int:
    """Ingest newly added opinions."""
    from backend.ingest.run import ingest_document
    
    ingested = 0
    for doc_id in doc_ids[:limit]:
        try:
            doc = db.get_document(doc_id)
            if doc:
                result = await ingest_document(doc)
                if result.get('success'):
                    ingested += 1
                    logger.info(f"Ingested: {doc.get('case_name')}")
        except Exception as e:
            logger.error(f"Error ingesting document {doc_id}: {e}")
    
    return ingested

async def run_scheduled_sync(sync_type: str = "scheduled", force: bool = False) -> Dict[str, Any]:
    """
    Run a scheduled sync to fetch and ingest new CAFC opinions.
    
    Args:
        sync_type: "scheduled" or "manual"
        force: If True, sync from 30 days ago even if last sync was recent
    
    Returns:
        Dict with sync results
    """
    sync_id = create_sync_record(sync_type)
    
    try:
        last_sync = get_last_sync_date()
        latest_doc = get_latest_document_date()
        
        if force or not last_sync:
            since_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        else:
            sync_dt = datetime.strptime(last_sync, "%Y-%m-%d")
            since_date = (sync_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        
        today = datetime.now().strftime("%Y-%m-%d")
        date_range = f"{since_date} to {today}"
        
        logger.info(f"Running {sync_type} sync for date range: {date_range}")
        
        new_opinions = fetch_new_opinions(since_date)
        found_count = len(new_opinions)
        
        added_ids = []
        for opinion in new_opinions:
            doc_id = add_opinion_to_manifest(opinion)
            if doc_id:
                added_ids.append(doc_id)
        
        ingested_count = 0
        if added_ids:
            ingested_count = await ingest_new_opinions(added_ids)
        
        update_sync_record(
            sync_id, 
            status='completed',
            found=found_count,
            ingested=ingested_count,
            date_range=date_range
        )
        
        return {
            'success': True,
            'sync_id': sync_id,
            'date_range': date_range,
            'opinions_found': found_count,
            'opinions_added': len(added_ids),
            'opinions_ingested': ingested_count,
        }
        
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        update_sync_record(sync_id, status='failed', error_msg=str(e))
        return {
            'success': False,
            'sync_id': sync_id,
            'error': str(e),
        }

def get_sync_history(limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent sync history records."""
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, sync_type, status, started_at, completed_at,
                       new_opinions_found, new_opinions_ingested, error_message, last_synced_date
                FROM sync_history
                ORDER BY started_at DESC
                LIMIT %s
            """, (limit,))
            rows = cursor.fetchall()
            return [
                {
                    'id': row['id'],
                    'sync_type': row['sync_type'],
                    'status': row['status'],
                    'started_at': row['started_at'].isoformat() if row['started_at'] else None,
                    'completed_at': row['completed_at'].isoformat() if row['completed_at'] else None,
                    'new_opinions_found': row['new_opinions_found'],
                    'new_opinions_ingested': row['new_opinions_ingested'],
                    'error_message': row['error_message'],
                    'last_synced_date': row['last_synced_date'],
                }
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Error getting sync history: {e}")
        return []

def get_next_scheduled_sync() -> Optional[str]:
    """Calculate when the next scheduled sync should run (every Sunday at 2 AM)."""
    now = datetime.now()
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.hour >= 2:
        days_until_sunday = 7
    
    next_sync = now.replace(hour=2, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
    return next_sync.isoformat()
