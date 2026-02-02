#!/usr/bin/env python3
"""
Phase 1 Regression Analysis Script

Loads eval reports and identifies:
- Queries where NOT FOUND flips from False (baseline) to True (phase1)
- Largest latency deltas
- Per-query decision context, subqueries, and retrieval delta

Usage:
    # Process multiple reports (shell glob expansion):
    python scripts/print_phase1_regressions.py reports/phase1_eval_*.json
    
    # Process a single report with --report:
    python scripts/print_phase1_regressions.py --report reports/phase1_eval_20260202_034850.json
    
    # Show top N latency deltas:
    python scripts/print_phase1_regressions.py --top 10 reports/phase1_eval_*.json
    
    # Auto-find latest report:
    python scripts/print_phase1_regressions.py
"""

import argparse
import json
import os
import sys
import glob as glob_module
from typing import Dict, List, Any, Optional


def find_latest_report(reports_dir: str = "reports") -> Optional[str]:
    """Find the most recent phase1_eval_*.json report."""
    pattern = os.path.join(reports_dir, "phase1_eval_*.json")
    files = glob_module.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def load_report(path: str) -> Dict[str, Any]:
    """Load JSON report."""
    with open(path) as f:
        return json.load(f)


def analyze_nf_flips(report: Dict) -> List[Dict]:
    """Find queries where NOT FOUND flips F→T between baseline and phase1."""
    flips = []
    
    baseline_data = report.get("baseline", {})
    phase1_data = report.get("phase1", {})
    baseline_results = {r["query_id"]: r for r in baseline_data.get("results", [])}
    phase1_results = {r["query_id"]: r for r in phase1_data.get("results", [])}
    
    for query_id, baseline in baseline_results.items():
        phase1 = phase1_results.get(query_id)
        if not phase1:
            continue
        
        baseline_nf = baseline.get("not_found", False)
        phase1_nf = phase1.get("not_found", False)
        
        if baseline_nf is False and phase1_nf is True:
            flips.append({
                "query_id": query_id,
                "query": baseline.get("query", "")[:100],
                "baseline_not_found": baseline_nf,
                "phase1_not_found": phase1_nf,
                "baseline_verified": baseline.get("verified_citations", 0),
                "phase1_verified": phase1.get("verified_citations", 0),
                "decision_context": phase1.get("decision_context", {}),
                "subqueries": phase1.get("subqueries_list", []),
                "candidates_added": phase1.get("candidates_added_list", []),
                "retrieval_delta": phase1.get("retrieval_delta", {})
            })
    
    return flips


def analyze_latency_deltas(report: Dict) -> List[Dict]:
    """Find queries with largest latency deltas."""
    deltas = []
    
    baseline_data = report.get("baseline", {})
    phase1_data = report.get("phase1", {})
    baseline_results = {r["query_id"]: r for r in baseline_data.get("results", [])}
    phase1_results = {r["query_id"]: r for r in phase1_data.get("results", [])}
    
    for query_id, baseline in baseline_results.items():
        phase1 = phase1_results.get(query_id)
        if not phase1:
            continue
        
        baseline_lat = baseline.get("latency_ms", 0)
        phase1_lat = phase1.get("latency_ms", 0)
        delta_ms = phase1_lat - baseline_lat
        
        deltas.append({
            "query_id": query_id,
            "query": baseline.get("query", "")[:80],
            "baseline_latency_ms": baseline_lat,
            "phase1_latency_ms": phase1_lat,
            "delta_ms": delta_ms,
            "delta_pct": (delta_ms / baseline_lat * 100) if baseline_lat > 0 else 0,
            "triggered": phase1.get("phase1_triggered", False),
            "triggers": phase1.get("triggers", []),
            "candidates_added": phase1.get("candidates_added", 0)
        })
    
    return sorted(deltas, key=lambda x: x["delta_ms"], reverse=True)


def print_nf_flips(flips: List[Dict]):
    """Print NOT FOUND flip analysis."""
    print("\n" + "="*70)
    print("NOT FOUND FLIPS (False → True)")
    print("="*70)
    
    if not flips:
        print("✓ No NOT FOUND regressions detected!")
        return
    
    for i, flip in enumerate(flips, 1):
        print(f"\n--- Flip #{i}: {flip['query_id']} ---")
        print(f"Query: {flip['query']}")
        print(f"Baseline verified: {flip['baseline_verified']}, Phase1 verified: {flip['phase1_verified']}")
        
        ctx = flip.get("decision_context", {})
        if ctx:
            print(f"Doctrines: {ctx.get('doctrines_detected', [])}")
            print(f"Evidence: {ctx.get('doctrine_evidence', {})}")
            print(f"Multi-issue: {ctx.get('multi_issue_detected', False)}")
            print(f"Thin retrieval: {ctx.get('thin_retrieval_detected', False)}")
            print(f"Strong baseline: {ctx.get('strong_baseline_evidence', {})}")
        
        if flip.get("subqueries"):
            print(f"Subqueries: {flip['subqueries']}")
        
        if flip.get("candidates_added"):
            print(f"Candidates added: {flip['candidates_added']}")
        
        delta = flip.get("retrieval_delta", {})
        if delta:
            print(f"Retrieval delta: total_sources={delta.get('total_sources')}")


def print_latency_analysis(deltas: List[Dict], top_n: int = 5):
    """Print latency delta analysis."""
    print("\n" + "="*70)
    print(f"TOP {top_n} LATENCY DELTAS")
    print("="*70)
    
    for i, d in enumerate(deltas[:top_n], 1):
        sign = "+" if d["delta_ms"] > 0 else ""
        print(f"\n{i}. {d['query_id']}")
        print(f"   Query: {d['query']}")
        print(f"   Baseline: {d['baseline_latency_ms']}ms → Phase1: {d['phase1_latency_ms']}ms ({sign}{d['delta_ms']}ms, {sign}{d['delta_pct']:.1f}%)")
        print(f"   Triggered: {d['triggered']}, Triggers: {d['triggers']}, Candidates: {d['candidates_added']}")


def print_summary(report: Dict):
    """Print summary statistics."""
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    baseline = report.get("baseline", {})
    phase1 = report.get("phase1", {})
    
    print(f"Baseline NOT FOUND rate: {baseline.get('not_found_rate', 'N/A')}")
    print(f"Phase1 NOT FOUND rate: {phase1.get('not_found_rate', 'N/A')}")
    print(f"Phase1 Trigger rate: {phase1.get('trigger_rate', 'N/A')}")
    print(f"Phase1 Avg candidates added: {phase1.get('avg_candidates_added', 'N/A')}")
    print(f"Baseline Avg latency: {baseline.get('avg_latency_ms', 'N/A')}ms")
    print(f"Phase1 Avg latency: {phase1.get('avg_latency_ms', 'N/A')}ms")


def process_report(report_path: str, top_n: int = 5) -> int:
    """Process a single report file. Returns 1 if regressions found, 0 otherwise."""
    if not os.path.exists(report_path):
        print(f"ERROR: Report not found: {report_path}")
        return 2
    
    print(f"\n{'='*70}")
    print(f"Report: {report_path}")
    print(f"{'='*70}")
    
    report = load_report(report_path)
    
    print_summary(report)
    
    flips = analyze_nf_flips(report)
    print_nf_flips(flips)
    
    deltas = analyze_latency_deltas(report)
    print_latency_analysis(deltas, top_n)
    
    if flips:
        print(f"\n⚠️  {len(flips)} NOT FOUND regression(s) detected!")
        return 1
    else:
        print("\n✓ No regressions detected.")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Phase 1 eval regressions",
        epilog="""
Examples:
  # Process multiple reports (shell glob expansion):
  python scripts/print_phase1_regressions.py reports/phase1_eval_*.json
  
  # Process a single report with --report:
  python scripts/print_phase1_regressions.py --report reports/phase1_eval_20260202_034850.json
  
  # Show top N latency deltas:
  python scripts/print_phase1_regressions.py --top 10 reports/phase1_eval_*.json
  
  # Auto-find latest report:
  python scripts/print_phase1_regressions.py
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "reports", 
        nargs="*", 
        help="Report file paths (supports shell glob expansion)"
    )
    parser.add_argument(
        "--report", 
        dest="legacy_report",
        help="Path to eval report JSON (legacy, use positional args instead)"
    )
    parser.add_argument(
        "--top", 
        type=int, 
        default=5, 
        help="Number of top latency deltas to show (default: 5)"
    )
    args = parser.parse_args()
    
    # Collect all report paths
    report_paths = list(args.reports) if args.reports else []
    if args.legacy_report:
        report_paths.append(args.legacy_report)
    
    # If no reports specified, auto-find latest
    if not report_paths:
        latest = find_latest_report()
        if latest:
            report_paths = [latest]
    
    # Validate we have reports
    if not report_paths:
        print("ERROR: No eval reports found.")
        print()
        print("Usage examples:")
        print("  python scripts/print_phase1_regressions.py reports/phase1_eval_*.json")
        print("  python scripts/print_phase1_regressions.py --report reports/phase1_eval_20260202_034850.json")
        print()
        print("To generate a report, run:")
        print("  PYTHONPATH=. python backend/smart/eval_phase1.py --compare --queries 12")
        return 2
    
    # Process all reports
    exit_code = 0
    for report_path in sorted(report_paths):
        result = process_report(report_path, args.top)
        if result > exit_code:
            exit_code = result
    
    if len(report_paths) > 1:
        print(f"\n{'='*70}")
        print(f"Processed {len(report_paths)} reports")
        print(f"{'='*70}")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
