"""
Tests for Voyager production hardening features:
- Circuit breaker behavior
- Retention policy
- Replay packet auth
"""

import pytest
import os
import time
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from backend import voyager


class TestCircuitBreaker:
    """Test circuit breaker implementation."""
    
    def setup_method(self):
        """Reset circuit breaker before each test."""
        voyager._circuit_breaker = voyager.CircuitBreaker(
            failure_threshold=3,
            cooldown_seconds=1
        )
    
    def test_initial_state_is_closed(self):
        """Circuit breaker starts in CLOSED state."""
        state = voyager.get_circuit_breaker_state()
        assert state["state"] == "closed"
        assert state["failure_count"] == 0
    
    def test_can_execute_when_closed(self):
        """Execution is allowed when circuit is CLOSED."""
        assert voyager._circuit_breaker.can_execute() is True
    
    def test_opens_after_failure_threshold(self):
        """Circuit opens after reaching failure threshold."""
        for _ in range(3):
            voyager._circuit_breaker.record_failure()
        
        state = voyager.get_circuit_breaker_state()
        assert state["state"] == "open"
        assert voyager._circuit_breaker.can_execute() is False
    
    def test_skips_execution_when_open(self):
        """Execution is skipped when circuit is OPEN."""
        for _ in range(3):
            voyager._circuit_breaker.record_failure()
        
        assert voyager._circuit_breaker.can_execute() is False
    
    def test_transitions_to_half_open_after_cooldown(self):
        """Circuit transitions to HALF_OPEN after cooldown period."""
        for _ in range(3):
            voyager._circuit_breaker.record_failure()
        
        assert voyager._circuit_breaker.state == "open"
        time.sleep(1.1)
        
        assert voyager._circuit_breaker.can_execute() is True
        assert voyager._circuit_breaker.state == "half_open"
    
    def test_closes_after_successful_test(self):
        """Circuit closes after successful execution in HALF_OPEN."""
        for _ in range(3):
            voyager._circuit_breaker.record_failure()
        
        time.sleep(1.1)
        voyager._circuit_breaker.can_execute()
        voyager._circuit_breaker.record_success()
        
        assert voyager._circuit_breaker.state == "closed"
    
    def test_reopens_on_failure_in_half_open(self):
        """Circuit reopens on failure in HALF_OPEN state."""
        for _ in range(3):
            voyager._circuit_breaker.record_failure()
        
        time.sleep(1.1)
        voyager._circuit_breaker.can_execute()
        voyager._circuit_breaker.record_failure()
        
        assert voyager._circuit_breaker.state == "open"


class TestRetentionPolicy:
    """Test retention policy functions."""
    
    def test_retention_constants(self):
        """Verify retention policy constants."""
        assert voyager.RETENTION_REDACT_DAYS == 90
        assert voyager.RETENTION_DELETE_DAYS == 365
    
    @patch('backend.voyager.db.get_db')
    def test_cleanup_dry_run_reports_counts(self, mock_db):
        """Dry run reports counts without making changes."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        
        mock_cursor.fetchone.side_effect = [
            {"cnt": 5},
            {"cnt": 2}
        ]
        
        result = voyager.cleanup_query_runs(dry_run=True)
        
        assert result["dry_run"] is True
        assert result["to_redact"] == 5
        assert result["to_delete"] == 2
        assert result["redacted"] == 0
        assert result["deleted"] == 0
        mock_conn.commit.assert_not_called()
    
    @patch('backend.voyager.db.get_db')
    def test_cleanup_apply_executes_changes(self, mock_db):
        """Apply mode executes redaction and deletion."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        
        mock_cursor.fetchone.side_effect = [
            {"cnt": 5},
            {"cnt": 2}
        ]
        mock_cursor.rowcount = 5
        
        result = voyager.cleanup_query_runs(dry_run=False)
        
        assert result["dry_run"] is False
        mock_conn.commit.assert_called_once()
    
    @patch('backend.voyager.db.get_db')
    def test_get_retention_stats(self, mock_db):
        """get_retention_stats returns correct statistics."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        
        mock_cursor.fetchone.side_effect = [
            {"cnt": 100},
            {"cnt": 80},
            {"cnt": 15},
            {"cnt": 5},
            {"cnt": 10}
        ]
        
        stats = voyager.get_retention_stats()
        
        assert stats["total_runs"] == 100
        assert stats["active_runs"] == 80
        assert stats["redactable_runs"] == 15
        assert stats["deletable_runs"] == 5
        assert stats["already_redacted"] == 10


class TestReplayPacket:
    """Test replay packet generation and size limits."""
    
    def test_replay_packet_max_size_constant(self):
        """Verify replay packet size limit is set."""
        assert voyager.REPLAY_PACKET_MAX_SIZE == 1_000_000
    
    @patch('backend.voyager.get_query_run')
    def test_returns_none_for_missing_run(self, mock_get_run):
        """Returns None when run_id not found."""
        mock_get_run.return_value = None
        
        result = voyager.get_replay_packet("nonexistent-id")
        
        assert result is None
    
    @patch('backend.voyager.get_query_run')
    def test_returns_packet_with_all_fields(self, mock_get_run):
        """Returns packet with all expected fields."""
        mock_get_run.return_value = {
            "id": "test-run-id",
            "created_at": datetime.utcnow(),
            "conversation_id": "conv-123",
            "user_query": "test query",
            "doctrine_tag": "101",
            "corpus_version_id": "abc123",
            "retrieval_manifest": {"page_ids": [1, 2, 3]},
            "context_manifest": {"page_ids": [1, 2]},
            "model_config": {"model": "gpt-4o"},
            "system_prompt_version": "v2.0",
            "final_answer": "Test answer",
            "citation_verifications": [],
            "latency_ms": 1000,
            "failure_reason": None
        }
        
        packet = voyager.get_replay_packet("test-run-id")
        
        assert packet["run_id"] == "test-run-id"
        assert packet["user_query"] == "test query"
        assert packet["doctrine_tag"] == "101"
        assert "_size_limited" not in packet
    
    @patch('backend.voyager.get_query_run')
    def test_truncates_oversized_packet(self, mock_get_run):
        """Truncates packet when size exceeds limit."""
        large_answer = "x" * 2_000_000
        mock_get_run.return_value = {
            "id": "test-run-id",
            "created_at": datetime.utcnow(),
            "conversation_id": "conv-123",
            "user_query": "test query",
            "doctrine_tag": None,
            "corpus_version_id": "abc123",
            "retrieval_manifest": {"page_ids": list(range(10000))},
            "context_manifest": {"page_ids": list(range(5000))},
            "model_config": {"model": "gpt-4o"},
            "system_prompt_version": "v2.0",
            "final_answer": large_answer,
            "citation_verifications": [],
            "latency_ms": 1000,
            "failure_reason": None
        }
        
        packet = voyager.get_replay_packet("test-run-id")
        
        assert packet["_size_limited"] is True
        assert packet["final_answer"] == "[TRUNCATED - exceeds size limit]"
        assert packet["retrieval_manifest"]["truncated"] is True
        assert packet["context_manifest"]["truncated"] is True


class TestCreateQueryRunWithCircuitBreaker:
    """Test create_query_run integration with circuit breaker."""
    
    def setup_method(self):
        """Reset circuit breaker before each test."""
        voyager._circuit_breaker = voyager.CircuitBreaker(
            failure_threshold=2,
            cooldown_seconds=1
        )
    
    @patch('backend.voyager.db.get_db')
    @patch('backend.voyager.compute_corpus_version_id')
    def test_skips_insert_when_circuit_open(self, mock_version, mock_db):
        """Skips DB insert when circuit breaker is OPEN."""
        mock_version.return_value = "test-version"
        
        voyager._circuit_breaker.record_failure()
        voyager._circuit_breaker.record_failure()
        
        assert voyager._circuit_breaker.state == "open"
        
        run_id = voyager.create_query_run("conv-1", "test query")
        
        assert run_id is not None
        mock_db.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
