#!/usr/bin/env python3
"""
Patent Law Expert Evaluation: 20 questions across 5 categories.
Tests the CAFC Opinion Assistant for deployment readiness.
"""
import asyncio
import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db_postgres
from chat import generate_chat_response

TEST_QUESTIONS = [
    # Category 1: Doctrinal / Section 101 (Patent Eligibility)
    {
        "id": 1,
        "category": "DOCTRINAL_101",
        "question": "What is the two-step Alice/Mayo framework for patent eligibility under 35 U.S.C. § 101, and how has the Federal Circuit applied it?",
        "expected": ["Alice", "Mayo", "abstract idea", "inventive concept", "Step 1", "Step 2"],
        "difficulty": "Medium"
    },
    {
        "id": 2,
        "category": "DOCTRINAL_101",
        "question": "Under what circumstances has the CAFC found software claims patent-eligible after Alice? Cite specific cases.",
        "expected": ["Enfish", "DDR Holdings", "patent-eligible", "abstract idea"],
        "difficulty": "Hard"
    },
    # Category 2: Section 103 (Obviousness)
    {
        "id": 3,
        "category": "DOCTRINAL_103",
        "question": "What is the KSR v. Teleflex standard for obviousness, and how has the Federal Circuit refined it?",
        "expected": ["KSR", "obvious", "motivation to combine", "teaching", "suggestion"],
        "difficulty": "Medium"
    },
    {
        "id": 4,
        "category": "DOCTRINAL_103",
        "question": "How does the Federal Circuit evaluate secondary considerations of nonobviousness such as commercial success and long-felt need?",
        "expected": ["secondary considerations", "commercial success", "long-felt need", "nexus", "Graham"],
        "difficulty": "Hard"
    },
    # Category 3: Claim Construction
    {
        "id": 5,
        "category": "CLAIM_CONSTRUCTION",
        "question": "What is the Phillips v. AWH standard for claim construction and how does it differ from the broadest reasonable interpretation standard?",
        "expected": ["Phillips", "intrinsic evidence", "specification", "prosecution history", "broadest reasonable"],
        "difficulty": "Medium"
    },
    # Category 4: Case-Specific Retrieval
    {
        "id": 6,
        "category": "CASE_SPECIFIC",
        "question": "What did the Federal Circuit hold in Arthrex regarding the constitutionality of PTAB judges?",
        "expected": ["Arthrex", "Appointments Clause", "APJ", "administrative patent judge"],
        "difficulty": "Medium"
    },
    {
        "id": 7,
        "category": "CASE_SPECIFIC",
        "question": "Summarize the CAFC's holding in Berkheimer v. HP regarding the factual nature of the Alice Step 2 inquiry.",
        "expected": ["Berkheimer", "factual", "well-understood", "routine", "conventional", "summary judgment"],
        "difficulty": "Hard"
    },
    {
        "id": 8,
        "category": "CASE_SPECIFIC",
        "question": "What did the Federal Circuit decide in Amgen v. Sanofi regarding the enablement requirement for antibody claims?",
        "expected": ["Amgen", "Sanofi", "enablement", "antibody", "genus", "undue experimentation"],
        "difficulty": "Hard"
    },
    {
        "id": 9,
        "category": "CASE_SPECIFIC",
        "question": "What was the CAFC's ruling on design patent damages in Samsung v. Apple?",
        "expected": ["Samsung", "Apple", "design patent", "article of manufacture", "damages", "total profit"],
        "difficulty": "Medium"
    },
    {
        "id": 10,
        "category": "CASE_SPECIFIC",
        "question": "Explain the Federal Circuit's decision in In re Rudy regarding the on-sale bar.",
        "expected": ["on-sale", "bar", "commercial", "offer for sale"],
        "difficulty": "Hard"
    },
    # Category 5: Synthesis (multi-case reasoning)
    {
        "id": 11,
        "category": "SYNTHESIS",
        "question": "How has the doctrine of equivalents evolved in recent CAFC decisions, particularly regarding prosecution history estoppel?",
        "expected": ["doctrine of equivalents", "prosecution history estoppel", "Festo", "amendment"],
        "difficulty": "Hard"
    },
    {
        "id": 12,
        "category": "SYNTHESIS",
        "question": "Trace the evolution of the written description requirement from Ariad to recent Federal Circuit decisions for biotechnology patents.",
        "expected": ["written description", "Ariad", "possession", "biotechnology", "genus"],
        "difficulty": "Hard"
    },
    {
        "id": 13,
        "category": "SYNTHESIS",
        "question": "Compare and contrast the Federal Circuit's approach to means-plus-function limitations in Williamson v. Citrix and subsequent cases.",
        "expected": ["means-plus-function", "Williamson", "nonce word", "112(f)", "structure"],
        "difficulty": "Hard"
    },
    # Category 6: Procedural
    {
        "id": 14,
        "category": "PROCEDURAL",
        "question": "What are the standards for obtaining a preliminary injunction in patent cases after eBay v. MercExchange?",
        "expected": ["preliminary injunction", "eBay", "irreparable harm", "balance of hardships", "public interest"],
        "difficulty": "Medium"
    },
    {
        "id": 15,
        "category": "PROCEDURAL",
        "question": "What is the standard of review that the Federal Circuit applies to PTAB inter partes review final written decisions?",
        "expected": ["substantial evidence", "PTAB", "inter partes review", "IPR", "standard of review"],
        "difficulty": "Medium"
    },
    # Category 7: Edge Cases & Stress Tests
    {
        "id": 16,
        "category": "EDGE_CASE",
        "question": "Has the Federal Circuit addressed patent eligibility of AI-generated inventions or computer-generated claims?",
        "expected": ["artificial intelligence", "AI", "inventor", "natural person"],
        "difficulty": "Hard"
    },
    {
        "id": 17,
        "category": "EDGE_CASE",
        "question": "What is the current state of the law regarding divided infringement after Akamai v. Limelight?",
        "expected": ["divided infringement", "Akamai", "Limelight", "joint infringement", "direct", "control or direction"],
        "difficulty": "Hard"
    },
    {
        "id": 18,
        "category": "STRESS_TEST",
        "question": "A client has a patent on a method of using machine learning to predict drug interactions. A competitor uses a similar ML approach but with a different training dataset and slightly different neural network architecture. Analyze potential infringement under the doctrine of equivalents and any Alice § 101 issues.",
        "expected": ["doctrine of equivalents", "Alice", "101", "abstract idea", "machine learning", "function-way-result"],
        "difficulty": "Expert"
    },
    {
        "id": 19,
        "category": "STRESS_TEST",
        "question": "What are the key considerations for venue in patent cases after TC Heartland, and how has the Federal Circuit interpreted 'regular and established place of business'?",
        "expected": ["TC Heartland", "venue", "regular and established", "place of business", "28 U.S.C. § 1400"],
        "difficulty": "Medium"
    },
    {
        "id": 20,
        "category": "STRESS_TEST",
        "question": "Explain the intersection of patent exhaustion and conditional licensing after Lexmark v. Impression Products as addressed by the Federal Circuit and Supreme Court.",
        "expected": ["exhaustion", "Lexmark", "Impression Products", "conditional", "first sale", "authorized sale"],
        "difficulty": "Hard"
    },
]

SCORING_CRITERIA = {
    "citation_present": 15,
    "keyword_coverage": 25,
    "no_hallucination": 20,
    "legal_accuracy": 20,
    "response_quality": 10,
    "response_time": 10,
}

def score_response(question, response_text, sources, elapsed_time):
    score = {}
    text_lower = response_text.lower()

    has_citations = bool(sources) and len(sources) > 0
    has_inline_refs = any(f"[{i}]" in response_text for i in range(1, 20))
    citation_score = 15 if (has_citations and has_inline_refs) else (10 if has_citations else (5 if has_inline_refs else 0))
    score["citation_present"] = citation_score

    expected = question["expected"]
    matches = sum(1 for kw in expected if kw.lower() in text_lower)
    coverage = matches / len(expected) if expected else 0
    score["keyword_coverage"] = round(coverage * 25)

    not_found_ratio = text_lower.count("not found") / max(len(text_lower.split()), 1)
    refusal_phrases = ["i cannot", "i don't have", "i'm unable", "no information available"]
    is_refusal = any(p in text_lower for p in refusal_phrases) and len(response_text) < 200
    hallucination_red_flags = ["i made up", "hypothetically speaking", "this is fictional"]
    has_hallucination = any(f in text_lower for f in hallucination_red_flags)

    if has_hallucination:
        score["no_hallucination"] = 0
    elif is_refusal:
        score["no_hallucination"] = 10
    elif not_found_ratio > 0.1:
        score["no_hallucination"] = 12
    else:
        score["no_hallucination"] = 20

    word_count = len(response_text.split())
    has_legal_structure = any(term in text_lower for term in ["holding", "court held", "ruled", "concluded", "standard", "test", "framework", "analysis"])
    has_case_refs = any(term in text_lower for term in [" v. ", " vs. ", "u.s.c.", "f.3d", "f.4th", "fed. cir."])

    if has_legal_structure and has_case_refs and word_count > 150:
        score["legal_accuracy"] = 20
    elif has_legal_structure or has_case_refs:
        score["legal_accuracy"] = 14
    elif word_count > 100:
        score["legal_accuracy"] = 8
    else:
        score["legal_accuracy"] = 4

    if word_count > 200 and has_legal_structure:
        score["response_quality"] = 10
    elif word_count > 100:
        score["response_quality"] = 7
    else:
        score["response_quality"] = 3

    if elapsed_time < 30:
        score["response_time"] = 10
    elif elapsed_time < 60:
        score["response_time"] = 7
    elif elapsed_time < 120:
        score["response_time"] = 4
    else:
        score["response_time"] = 1

    score["total"] = sum(score.values())
    score["elapsed_seconds"] = round(elapsed_time, 1)
    score["word_count"] = word_count
    score["source_count"] = len(sources) if sources else 0
    return score


async def run_evaluation():
    print("=" * 80)
    print("CAFC OPINION ASSISTANT — DEPLOYMENT READINESS EVALUATION")
    print("20 Patent Law Expert Questions")
    print("=" * 80)

    ts = str(int(time.time()))
    test_user_id = "eval-test-user-" + ts
    from db_postgres import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO users (id, email, first_name, last_name, approval_status, is_admin, created_at, updated_at) 
               VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW()) 
               ON CONFLICT (id) DO NOTHING""",
            (test_user_id, f"eval-{ts}@test.local", "Eval", "Tester", "approved", False)
        )
        conn.commit()
    
    start_from = int(os.environ.get("EVAL_START", "1"))
    end_at = int(os.environ.get("EVAL_END", "20"))
    
    conv_id = db_postgres.create_conversation(user_id=test_user_id)
    print(f"\nTest conversation: {conv_id}")

    results = []
    category_scores = {}
    total_time = 0

    filtered_questions = [q for q in TEST_QUESTIONS if start_from <= q["id"] <= end_at]
    print(f"Running questions {start_from}-{end_at} ({len(filtered_questions)} questions)")
    
    for q in filtered_questions:
        qid = q["id"]
        print(f"\n{'—' * 60}")
        print(f"Q{qid:02d} [{q['category']}] ({q['difficulty']})")
        print(f"  {q['question'][:100]}...")

        db_postgres.add_message(conv_id, "user", q["question"])

        start = time.time()
        try:
            response = await generate_chat_response(
                message=q["question"],
                opinion_ids=None,
                conversation_id=conv_id,
                party_only=False,
                attorney_mode=False
            )
            elapsed = time.time() - start
        except Exception as e:
            elapsed = time.time() - start
            print(f"  ERROR: {str(e)[:100]}")
            results.append({
                "id": qid,
                "category": q["category"],
                "error": str(e)[:200],
                "scores": {"total": 0, "elapsed_seconds": round(elapsed, 1)},
            })
            continue

        answer = response.get("answer", "")
        sources = response.get("sources", [])

        db_postgres.add_message(conv_id, "assistant", answer, citations=json.dumps({"sources": sources}) if sources else None)

        scores = score_response(q, answer, sources, elapsed)
        total_time += elapsed

        cat = q["category"]
        if cat not in category_scores:
            category_scores[cat] = []
        category_scores[cat].append(scores["total"])

        result = {
            "id": qid,
            "category": cat,
            "difficulty": q["difficulty"],
            "scores": scores,
            "answer_preview": answer[:250] + "..." if len(answer) > 250 else answer,
            "source_count": len(sources),
            "source_tiers": {},
        }

        for s in sources:
            tier = s.get("tier", "unverified")
            result["source_tiers"][tier] = result["source_tiers"].get(tier, 0) + 1

        results.append(result)
        print(f"  Score: {scores['total']}/100 | Sources: {len(sources)} | Time: {scores['elapsed_seconds']}s")
        print(f"  Keywords: {scores['keyword_coverage']}/25 | Citations: {scores['citation_present']}/15 | Accuracy: {scores['legal_accuracy']}/20")

    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)

    all_totals = [r["scores"]["total"] for r in results if "total" in r["scores"]]
    overall_avg = sum(all_totals) / len(all_totals) if all_totals else 0

    print(f"\nOverall Average Score: {overall_avg:.1f}/100")
    print(f"Total Evaluation Time: {total_time:.0f}s ({total_time/60:.1f} min)")
    print(f"Average Response Time: {total_time/len(TEST_QUESTIONS):.1f}s")

    print("\nCategory Breakdown:")
    for cat, cat_scores in sorted(category_scores.items()):
        avg = sum(cat_scores) / len(cat_scores)
        print(f"  {cat:25s}: {avg:5.1f}/100 ({len(cat_scores)} questions)")

    all_tiers = {}
    for r in results:
        for tier, count in r.get("source_tiers", {}).items():
            all_tiers[tier] = all_tiers.get(tier, 0) + count
    total_sources = sum(all_tiers.values())
    print(f"\nCitation Confidence Distribution ({total_sources} total sources):")
    for tier in ["strong", "moderate", "weak", "unverified"]:
        count = all_tiers.get(tier, 0)
        pct = (count / total_sources * 100) if total_sources else 0
        print(f"  {tier:12s}: {count:4d} ({pct:5.1f}%)")

    passed = sum(1 for t in all_totals if t >= 60)
    failed = sum(1 for t in all_totals if t < 60)
    errors = sum(1 for r in results if "error" in r)

    if overall_avg >= 75 and failed <= 3 and errors == 0:
        grade = "A"
        recommendation = "GO"
    elif overall_avg >= 65 and failed <= 5:
        grade = "B"
        recommendation = "GO (with minor improvements)"
    elif overall_avg >= 55 and failed <= 8:
        grade = "C"
        recommendation = "CONDITIONAL GO (address weaknesses)"
    elif overall_avg >= 45:
        grade = "D"
        recommendation = "NO-GO (significant issues)"
    else:
        grade = "F"
        recommendation = "NO-GO (fundamental problems)"

    print(f"\n{'=' * 60}")
    print(f"  FINAL GRADE:       {grade}")
    print(f"  PASSED (≥60):      {passed}/20")
    print(f"  FAILED (<60):      {failed}/20")
    print(f"  ERRORS:            {errors}/20")
    print(f"  RECOMMENDATION:    {recommendation}")
    print(f"{'=' * 60}")

    report = {
        "overall_average": round(overall_avg, 1),
        "grade": grade,
        "recommendation": recommendation,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total_time_seconds": round(total_time, 1),
        "category_averages": {cat: round(sum(s)/len(s), 1) for cat, s in category_scores.items()},
        "citation_distribution": all_tiers,
        "total_sources": total_sources,
        "results": results,
    }

    with open("backend/eval_results_20.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nFull report saved to backend/eval_results_20.json")

    return report


if __name__ == "__main__":
    asyncio.run(run_evaluation())
