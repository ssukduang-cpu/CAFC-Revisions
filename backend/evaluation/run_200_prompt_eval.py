#!/usr/bin/env python3
"""
Large-scale verification evaluation: 200 attorney-style prompts across 10 doctrine families.

Reports:
- Verification rate overall and by doctrine
- Median/95th percentile latency
- % of case-named holdings unsupported
- Top 10 failure modes with examples
"""

import requests
import json
import time
import statistics
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple

BASE_URL = "http://localhost:5000"

# 10 doctrine families with 20 prompts each = 200 total
DOCTRINE_PROMPTS = {
    "101_eligibility": [
        "What is the Alice/Mayo two-step test for patent eligibility?",
        "How do courts analyze abstract ideas under Alice step one?",
        "What constitutes an inventive concept under Alice step two?",
        "How did Bilski v. Kappos define abstract ideas?",
        "What are the Enfish factors for software patent eligibility?",
        "How does DDR Holdings apply to internet-based claims?",
        "What makes a claim patent-ineligible under Section 101?",
        "How do courts handle mathematical algorithms under 101?",
        "What is the preemption concern in eligibility analysis?",
        "How did Diamond v. Diehr treat software claims?",
        "What are methods of organizing human activity under Alice?",
        "How do courts analyze diagnostic method claims under Mayo?",
        "What is the significance of Vanda Pharmaceuticals for method claims?",
        "How does American Axle apply to eligibility analysis?",
        "What are the Federal Circuit's guidelines for step two analysis?",
        "How do courts treat data manipulation claims under 101?",
        "What makes a claim directed to a law of nature?",
        "How did CardioNet expand eligibility for health monitoring?",
        "What is the role of claim construction in 101 analysis?",
        "How do courts analyze claims directed to natural phenomena?",
    ],
    "103_obviousness": [
        "What is the KSR framework for analyzing obviousness?",
        "How do courts apply the Graham v. John Deere factors?",
        "What is the motivation to combine analysis under KSR?",
        "How does obvious to try apply to obviousness?",
        "What are teaching away arguments in obviousness?",
        "How do courts analyze secondary considerations of nonobviousness?",
        "What is the TSM test after KSR?",
        "How does hindsight reconstruction apply to obviousness?",
        "What makes a combination of known elements obvious?",
        "How do courts handle predictable results in obviousness?",
        "What is the role of commercial success in nonobviousness?",
        "How do long-felt but unsolved needs support nonobviousness?",
        "What is the failure of others doctrine?",
        "How do courts analyze unexpected results?",
        "What is a design choice in obviousness analysis?",
        "How does In re Wands apply to obviousness?",
        "What is the level of ordinary skill in the art?",
        "How do courts handle combining prior art references?",
        "What is the rational underpinning requirement for obviousness?",
        "How did SRI International v. Cisco apply KSR?",
    ],
    "112_disclosure": [
        "What is the written description requirement under 35 USC 112?",
        "How do courts analyze enablement under Section 112?",
        "What are the Wands factors for enablement?",
        "How does the full scope of claims affect enablement?",
        "What is undue experimentation in enablement analysis?",
        "How do courts analyze definiteness under 112(b)?",
        "What is the Nautilus standard for definiteness?",
        "How does claim construction affect 112 analysis?",
        "What is the written description requirement for genus claims?",
        "How do Ariad and Lockwood apply to written description?",
        "What is possession of the invention under 112?",
        "How do courts handle prophetic examples in enablement?",
        "What is the relationship between enablement and written description?",
        "How does the specification support functional claim language?",
        "What makes a claim indefinite under Nautilus?",
        "How do courts analyze best mode under Section 112?",
        "What is the disclosure requirement for means-plus-function claims?",
        "How does Williamson affect claim construction?",
        "What is the unpredictability of technology in enablement?",
        "How do courts evaluate the scope of generic claims?",
    ],
    "claim_construction": [
        "What is the Phillips standard for claim construction?",
        "How do courts use intrinsic evidence in claim construction?",
        "What is the role of the specification in construing claims?",
        "How does prosecution history affect claim construction?",
        "When can extrinsic evidence be used in claim construction?",
        "What is claim differentiation in construction?",
        "How do courts construe means-plus-function claims?",
        "What is the ordinary meaning of claim terms?",
        "How does Markman apply to claim construction?",
        "What is the role of dictionaries in claim construction?",
        "How do courts handle preamble limitations?",
        "What is the prosecution disclaimer doctrine?",
        "How do courts construe transitional phrases?",
        "What is the effect of exemplary embodiments on construction?",
        "How do courts handle open-ended claim language?",
        "What is lexicography in claim construction?",
        "How do courts construe product-by-process claims?",
        "What is the broadest reasonable interpretation standard?",
        "How does en banc Williamson affect means-plus-function?",
        "What is the role of expert testimony in construction?",
    ],
    "infringement": [
        "What is literal infringement of patent claims?",
        "How does the doctrine of equivalents apply?",
        "What is the function-way-result test for equivalents?",
        "How does prosecution history estoppel limit equivalents?",
        "What is all-elements rule in infringement?",
        "How do courts analyze induced infringement under 271(b)?",
        "What is contributory infringement under 271(c)?",
        "How does Akamai apply to divided infringement?",
        "What is the knowledge requirement for indirect infringement?",
        "How do courts analyze method claims in infringement?",
        "What is joint infringement doctrine?",
        "How does Limelight affect multi-actor infringement?",
        "What is the substantial noninfringing use defense?",
        "How do courts handle means-plus-function in infringement?",
        "What is the timing of infringement for method claims?",
        "How does the all-advantages rule apply?",
        "What is the insubstantial differences test?",
        "How do courts analyze claim limitations in infringement?",
        "What is the role of claim construction in infringement?",
        "How does exhaustion affect infringement claims?",
    ],
    "remedies": [
        "What are the eBay factors for permanent injunctions?",
        "How do courts calculate reasonable royalty damages?",
        "What is the Georgia-Pacific framework for royalties?",
        "How do courts determine lost profits damages?",
        "What is the Panduit test for lost profits?",
        "How does enhanced damages work under 35 USC 284?",
        "What is the Halo standard for willful infringement?",
        "How do courts award attorney fees under Section 285?",
        "What makes a case exceptional for fee shifting?",
        "How does Octane Fitness apply to fee awards?",
        "What is the entire market value rule?",
        "How do courts apportion damages for multi-component products?",
        "What is the smallest salable unit for damages?",
        "How do courts handle ongoing royalties?",
        "What is prejudgment interest in patent damages?",
        "How do courts analyze irreparable harm for injunctions?",
        "What is the public interest factor in injunctions?",
        "How does Grain Processing affect damages?",
        "What are the requirements for preliminary injunctions?",
        "How do courts handle damages for design patents?",
    ],
    "ptab": [
        "What is inter partes review at the PTAB?",
        "How do courts review PTAB decisions on appeal?",
        "What is the claim construction standard at the PTAB?",
        "How does the PTAB apply obviousness in IPR?",
        "What is post-grant review procedure?",
        "How does discretionary denial work at the PTAB?",
        "What is the Fintiv doctrine for stays?",
        "How do courts handle estoppel from PTAB proceedings?",
        "What is the difference between IPR and PGR?",
        "How does ex parte reexamination work?",
        "What is the standard of review for PTAB findings?",
        "How do courts handle constitutional challenges to PTAB?",
        "What is the appointment of PTAB judges issue?",
        "How does Arthrex affect PTAB proceedings?",
        "What is the NHK-Fintiv discretionary denial?",
        "How do courts review PTAB claim construction?",
        "What is the burden of proof in IPR?",
        "How does the PTAB handle new prior art references?",
        "What is the effect of a final written decision?",
        "How do courts handle parallel litigation and IPR?",
    ],
    "doe_equivalents": [
        "What is the doctrine of equivalents in patent law?",
        "How does prosecution history estoppel limit DOE?",
        "What is the Festo presumption for claim amendments?",
        "How do courts apply the function-way-result test?",
        "What is the insubstantial differences test for DOE?",
        "How does the all-elements rule apply to DOE?",
        "What is the vitiation doctrine?",
        "How do courts analyze dedication to the public?",
        "What is argument-based estoppel?",
        "How does Warner-Jenkinson apply to DOE?",
        "What is the tangential relation exception to estoppel?",
        "How do courts determine if an element is equivalent?",
        "What is the objective inquiry for equivalents?",
        "How does technology at the time of infringement matter?",
        "What is the after-arising technology doctrine?",
        "How do courts handle narrowing amendments for estoppel?",
        "What is the complete bar for estoppel?",
        "How does Graver Tank apply to equivalents?",
        "What is the role of expert testimony in DOE?",
        "How do courts analyze claim scope limits on DOE?",
    ],
    "validity": [
        "What is the presumption of validity under 35 USC 282?",
        "How do courts analyze anticipation under Section 102?",
        "What is the clear and convincing evidence standard?",
        "How does prior art invalidate claims?",
        "What is inherent anticipation?",
        "How do courts analyze on-sale bar?",
        "What is the public use bar under AIA?",
        "How does experimental use exception apply?",
        "What is the printed publication bar?",
        "How do courts handle secret prior art?",
        "What is the critical date for prior art?",
        "How does AIA change prior art rules?",
        "What is the grace period under AIA?",
        "How do courts analyze derivation?",
        "What is double patenting doctrine?",
        "How does terminal disclaimer work?",
        "What is the on-sale bar for methods?",
        "How do courts handle commercial offers for sale?",
        "What is the ready for patenting standard?",
        "How does Helsinn affect the on-sale bar?",
    ],
    "procedure": [
        "What is venue for patent cases under TC Heartland?",
        "How do courts handle case-within-a-case in malpractice?",
        "What is the standard for summary judgment in patent cases?",
        "How do courts handle claim construction appeals?",
        "What is the role of the jury in patent trials?",
        "How does Markman hearing work?",
        "What is the standard for preliminary injunctions?",
        "How do courts handle discovery in patent cases?",
        "What is the procedure for IPR appeals?",
        "How does standing work in patent cases?",
        "What is the Declaratory Judgment Act in patent law?",
        "How do courts analyze joinder in patent cases?",
        "What is the standard for transfer of venue?",
        "How do courts handle stays pending IPR?",
        "What is the procedure for design patent cases?",
        "How does Federal Circuit jurisdiction work?",
        "What is the standard of review for claim construction?",
        "How do courts handle bifurcation in patent trials?",
        "What is the procedure for Hatch-Waxman litigation?",
        "How do courts analyze laches in patent cases?",
    ],
}

def run_single_query(query: str, doctrine: str) -> Dict:
    """Run a single query and collect metrics."""
    start_time = time.time()
    
    try:
        # Create conversation
        resp = requests.post(f"{BASE_URL}/api/conversations", 
                           json={"title": f"Eval: {doctrine}"}, 
                           timeout=10)
        conv_id = resp.json()["id"]
        
        # Send query
        resp = requests.post(f"{BASE_URL}/api/chat", 
                           json={"message": query, "conversationId": conv_id, "searchMode": "all"},
                           timeout=180)
        
        latency = time.time() - start_time
        result = resp.json()
        
        # Extract metrics
        metrics = result.get("debug", {}).get("citation_metrics", {})
        total_citations = metrics.get("total_citations", 0)
        verified_citations = metrics.get("verified_citations", 0)
        unsupported_statements = metrics.get("unsupported_statements", 0)
        total_statements = metrics.get("total_statements", 0)
        
        # Check for binding failures
        sources = result.get("sources", [])
        binding_failures = []
        for s in sources:
            # Support both top-level fields (new contract) and nested (legacy)
            tier = (s.get("tier") or s.get("citation_verification", {}).get("tier", "")).upper()
            if tier == "UNVERIFIED":
                signals = s.get("signals") or s.get("citation_verification", {}).get("signals", [])
                binding_failures.append({
                    "case_name": s.get("case_name", "Unknown"),
                    "quote": s.get("quote", "")[:100],
                    "signals": signals
                })
        
        return {
            "success": True,
            "doctrine": doctrine,
            "query": query,
            "latency": latency,
            "total_citations": total_citations,
            "verified_citations": verified_citations,
            "unsupported_statements": unsupported_statements,
            "total_statements": total_statements,
            "binding_failures": binding_failures,
            "verification_rate": (verified_citations / total_citations * 100) if total_citations > 0 else 100,
        }
        
    except Exception as e:
        return {
            "success": False,
            "doctrine": doctrine,
            "query": query,
            "error": str(e),
            "latency": time.time() - start_time,
        }

def run_evaluation(sample_size: int = 200) -> Dict:
    """Run full evaluation across all doctrines."""
    results = []
    doctrines = list(DOCTRINE_PROMPTS.keys())
    prompts_per_doctrine = sample_size // len(doctrines)
    
    print(f"Running evaluation: {sample_size} prompts across {len(doctrines)} doctrines")
    print(f"({prompts_per_doctrine} prompts per doctrine)")
    print("=" * 80)
    
    for doctrine in doctrines:
        prompts = DOCTRINE_PROMPTS[doctrine][:prompts_per_doctrine]
        print(f"\n[{doctrine}] Running {len(prompts)} prompts...")
        
        for i, query in enumerate(prompts, 1):
            result = run_single_query(query, doctrine)
            results.append(result)
            
            if result["success"]:
                print(f"  {i}/{len(prompts)}: {result['verification_rate']:.0f}% verified, {result['latency']:.1f}s")
            else:
                print(f"  {i}/{len(prompts)}: ERROR - {result.get('error', 'Unknown')}")
    
    return analyze_results(results)

def analyze_results(results: List[Dict]) -> Dict:
    """Analyze evaluation results."""
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    
    # Overall metrics
    all_latencies = [r["latency"] for r in successful]
    all_verification_rates = [r["verification_rate"] for r in successful]
    
    total_citations = sum(r["total_citations"] for r in successful)
    verified_citations = sum(r["verified_citations"] for r in successful)
    total_unsupported = sum(r["unsupported_statements"] for r in successful)
    total_statements = sum(r["total_statements"] for r in successful)
    
    overall_verification_rate = (verified_citations / total_citations * 100) if total_citations > 0 else 0
    unsupported_rate = (total_unsupported / total_statements * 100) if total_statements > 0 else 0
    
    # By doctrine
    by_doctrine = defaultdict(lambda: {"latencies": [], "verification_rates": [], "failures": []})
    for r in successful:
        d = r["doctrine"]
        by_doctrine[d]["latencies"].append(r["latency"])
        by_doctrine[d]["verification_rates"].append(r["verification_rate"])
        by_doctrine[d]["failures"].extend(r.get("binding_failures", []))
    
    doctrine_stats = {}
    for d, data in by_doctrine.items():
        doctrine_stats[d] = {
            "verification_rate": statistics.mean(data["verification_rates"]) if data["verification_rates"] else 0,
            "median_latency": statistics.median(data["latencies"]) if data["latencies"] else 0,
            "p95_latency": sorted(data["latencies"])[int(len(data["latencies"]) * 0.95)] if data["latencies"] else 0,
            "failure_count": len(data["failures"]),
        }
    
    # Top 10 failure modes
    all_failures = []
    for r in successful:
        for f in r.get("binding_failures", []):
            all_failures.append({
                "doctrine": r["doctrine"],
                "query": r["query"],
                **f
            })
    
    # Group failures by signal pattern
    failure_modes = defaultdict(list)
    for f in all_failures:
        key = tuple(sorted(f.get("signals", [])))
        failure_modes[key].append(f)
    
    top_failures = sorted(failure_modes.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    
    return {
        "summary": {
            "total_prompts": len(results),
            "successful_prompts": len(successful),
            "failed_prompts": len(failed),
            "overall_verification_rate": overall_verification_rate,
            "total_citations": total_citations,
            "verified_citations": verified_citations,
            "unsupported_statements_rate": unsupported_rate,
            "median_latency": statistics.median(all_latencies) if all_latencies else 0,
            "p95_latency": sorted(all_latencies)[int(len(all_latencies) * 0.95)] if all_latencies else 0,
        },
        "by_doctrine": doctrine_stats,
        "top_10_failure_modes": [
            {
                "signals": list(signals),
                "count": len(examples),
                "examples": examples[:3]  # Include up to 3 examples
            }
            for signals, examples in top_failures
        ],
        "target_met": overall_verification_rate >= 90,
    }

def generate_report(analysis: Dict) -> str:
    """Generate markdown report."""
    report = []
    report.append("# Large-Scale Verification Evaluation Report")
    report.append(f"\nGenerated: {datetime.now().isoformat()}\n")
    
    s = analysis["summary"]
    report.append("## Summary")
    report.append(f"- **Total prompts**: {s['total_prompts']}")
    report.append(f"- **Successful prompts**: {s['successful_prompts']}")
    report.append(f"- **Failed prompts**: {s['failed_prompts']}")
    report.append(f"- **Overall Verification Rate**: {s['overall_verification_rate']:.1f}% (Target: ≥90%)")
    report.append(f"- **Total Citations**: {s['total_citations']}")
    report.append(f"- **Verified Citations**: {s['verified_citations']}")
    report.append(f"- **Unsupported Statements Rate**: {s['unsupported_statements_rate']:.1f}%")
    report.append(f"- **Median Latency**: {s['median_latency']:.1f}s")
    report.append(f"- **95th Percentile Latency**: {s['p95_latency']:.1f}s")
    
    target_status = "✓ PASS" if analysis["target_met"] else "✗ FAIL"
    report.append(f"\n**Target Status**: {target_status}")
    
    report.append("\n## Verification Rate by Doctrine")
    report.append("| Doctrine | Verification Rate | Median Latency | P95 Latency | Failures |")
    report.append("|----------|------------------|----------------|-------------|----------|")
    for d, stats in sorted(analysis["by_doctrine"].items()):
        report.append(f"| {d} | {stats['verification_rate']:.1f}% | {stats['median_latency']:.1f}s | {stats['p95_latency']:.1f}s | {stats['failure_count']} |")
    
    report.append("\n## Top 10 Failure Modes")
    for i, fm in enumerate(analysis["top_10_failure_modes"], 1):
        report.append(f"\n### {i}. Signals: {', '.join(fm['signals']) or 'None'} ({fm['count']} occurrences)")
        for ex in fm["examples"]:
            report.append(f"- **Case**: {ex.get('case_name', 'Unknown')}")
            report.append(f"  - Query: {ex.get('query', '')[:80]}...")
            report.append(f"  - Quote: {ex.get('quote', '')[:100]}...")
    
    return "\n".join(report)

if __name__ == "__main__":
    import sys
    
    # Allow running with fewer prompts for testing
    sample_size = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    
    print(f"Starting evaluation with {sample_size} prompts...")
    analysis = run_evaluation(sample_size)
    
    # Generate and save report
    report = generate_report(analysis)
    
    report_path = f"backend/evaluation/eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(report_path, "w") as f:
        f.write(report)
    
    # Also save raw JSON
    json_path = report_path.replace(".md", ".json")
    with open(json_path, "w") as f:
        json.dump(analysis, f, indent=2, default=str)
    
    print(f"\n{'='*80}")
    print(f"Report saved to: {report_path}")
    print(f"JSON data saved to: {json_path}")
    print(f"{'='*80}")
    print(report)
