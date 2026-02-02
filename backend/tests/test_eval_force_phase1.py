"""
Test EVAL_FORCE_PHASE1 flag bypasses strong baseline gating.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest


def _set_env_and_reload(**kwargs):
    """Helper to set env vars and reload config modules."""
    for key, value in kwargs.items():
        os.environ[key] = value
    
    from importlib import reload
    import backend.smart.config
    reload(backend.smart.config)
    import backend.smart.augmenter
    reload(backend.smart.augmenter)


class TestEvalForcePhase1:
    """Test that EVAL_FORCE_PHASE1 bypasses gating."""
    
    def test_force_flag_bypasses_strong_baseline(self):
        """When EVAL_FORCE_PHASE1=true (in eval mode), Phase 1 should trigger even with strong baseline."""
        _set_env_and_reload(
            PHASE1_ENABLED='true',
            PHASE1_EVAL_MODE='true',
            EVAL_FORCE_PHASE1='true',
            SMART_QUERY_DECOMPOSE_ENABLED='true',
            SMART_EMBED_RECALL_ENABLED='false'
        )
        
        from backend.smart.augmenter import should_augment, is_strong_baseline
        from backend.smart import config as smart_config
        
        assert smart_config.EVAL_FORCE_PHASE1 == True
        
        # Create a strong baseline (10 results, high score)
        fts_results = [{'id': i, 'score': 0.5} for i in range(10)]
        
        # Verify it's detected as strong baseline
        is_strong, evidence = is_strong_baseline(fts_results)
        assert is_strong == True, "Should detect strong baseline"
        
        # But with EVAL_FORCE_PHASE1=true, should_augment should still return True
        should_trigger, reasons, ctx = should_augment(fts_results, "test query")
        
        assert should_trigger == True, "Should trigger despite strong baseline"
        assert "eval_force" in reasons, "Should have eval_force in reasons"
        assert "skip_strong_baseline" not in reasons, "Should NOT skip"
        
        print("✓ TEST 1 PASSED: Force flag bypasses strong baseline")
    
    def test_force_flag_disabled_respects_strong_baseline(self):
        """When EVAL_FORCE_PHASE1=false, Phase 1 should respect strong baseline check."""
        _set_env_and_reload(
            PHASE1_ENABLED='true',
            PHASE1_EVAL_MODE='false',
            EVAL_FORCE_PHASE1='false',
            SMART_QUERY_DECOMPOSE_ENABLED='true',
            SMART_EMBED_RECALL_ENABLED='false'
        )
        
        from backend.smart.augmenter import should_augment, is_strong_baseline
        from backend.smart import config as smart_config
        
        assert smart_config.EVAL_FORCE_PHASE1 == False
        
        # Create a strong baseline
        fts_results = [{'id': i, 'score': 0.5} for i in range(10)]
        
        # Verify it's detected as strong baseline
        is_strong, evidence = is_strong_baseline(fts_results)
        assert is_strong == True, "Should detect strong baseline"
        
        # Without force flag, should NOT trigger
        should_trigger, reasons, ctx = should_augment(fts_results, "test query")
        
        assert should_trigger == False, "Should NOT trigger with strong baseline"
        assert "skip_strong_baseline" in reasons, "Should have skip_strong_baseline"
        
        print("✓ TEST 2 PASSED: Force flag disabled respects strong baseline")
    
    def test_force_flag_adds_eval_force_reason(self):
        """When forced, the 'eval_force' reason should be added."""
        _set_env_and_reload(
            PHASE1_ENABLED='true',
            PHASE1_EVAL_MODE='true',
            EVAL_FORCE_PHASE1='true',
            SMART_QUERY_DECOMPOSE_ENABLED='true'
        )
        
        from backend.smart.augmenter import should_augment
        
        # Any query with force enabled should have eval_force reason
        fts_results = [{'id': 1, 'score': 0.9}]
        should_trigger, reasons, ctx = should_augment(fts_results, "simple query")
        
        assert "eval_force" in reasons, "Should have eval_force in reasons"
        
        print("✓ TEST 3 PASSED: Force flag adds eval_force reason")
    
    def test_set_phase1_flags_enables_force(self):
        """set_phase1_flags with force_trigger=True should set EVAL_FORCE_PHASE1."""
        from backend.smart.eval_phase1 import set_phase1_flags
        from backend.smart import config as smart_config
        
        # Enable with force
        set_phase1_flags(enabled=True, decompose_only=True, force_trigger=True)
        
        from importlib import reload
        import backend.smart.config
        reload(backend.smart.config)
        from backend.smart import config as smart_config
        
        assert smart_config.EVAL_FORCE_PHASE1 == True, "EVAL_FORCE_PHASE1 should be True"
        assert smart_config.SMART_QUERY_DECOMPOSE_ENABLED == True, "Decompose should be enabled"
        
        # Disable
        set_phase1_flags(enabled=False)
        reload(backend.smart.config)
        from backend.smart import config as smart_config
        
        assert smart_config.EVAL_FORCE_PHASE1 == False, "EVAL_FORCE_PHASE1 should be False after disable"
        
        print("✓ TEST 4 PASSED: set_phase1_flags properly enables force flag")


if __name__ == "__main__":
    test = TestEvalForcePhase1()
    test.test_force_flag_bypasses_strong_baseline()
    test.test_force_flag_disabled_respects_strong_baseline()
    test.test_force_flag_adds_eval_force_reason()
    test.test_set_phase1_flags_enables_force()
    print("\n✅ All EVAL_FORCE_PHASE1 tests passed!")
