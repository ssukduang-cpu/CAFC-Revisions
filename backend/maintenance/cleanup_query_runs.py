"""
Cleanup Job for query_runs Retention Policy

Applies retention policy to query_runs table:
- Redact final_answer after 90 days (keep manifests/metrics)
- Delete rows after 365 days

Usage:
  python -m backend.maintenance.cleanup_query_runs --dry-run   # Preview changes
  python -m backend.maintenance.cleanup_query_runs --apply     # Apply changes
"""

import argparse
import logging
import sys
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup query_runs table according to retention policy"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview changes without applying them (default)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply retention policy (redact and delete old records)"
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt (for scheduled/automated runs)"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show retention statistics only"
    )
    
    args = parser.parse_args()
    
    from backend import voyager
    
    print("\n" + "=" * 60)
    print("QUERY_RUNS RETENTION CLEANUP")
    print("=" * 60)
    
    if args.stats:
        stats = voyager.get_retention_stats()
        print("\nRetention Statistics:")
        print(json.dumps(stats, indent=2))
        return 0
    
    dry_run = not args.apply
    
    if dry_run:
        print("\nMODE: DRY-RUN (no changes will be made)")
    else:
        print("\nMODE: APPLY (changes will be committed)")
        if not args.yes:
            confirm = input("Are you sure you want to apply retention policy? [y/N]: ")
            if confirm.lower() != 'y':
                print("Aborted.")
                return 1
    
    print(f"\nRetention Policy:")
    print(f"  - Redact final_answer after: {voyager.RETENTION_REDACT_DAYS} days")
    print(f"  - Delete rows after: {voyager.RETENTION_DELETE_DAYS} days")
    
    result = voyager.cleanup_query_runs(dry_run=dry_run)
    
    print("\nResults:")
    print(json.dumps(result, indent=2, default=str))
    
    if result.get("errors"):
        print("\nERRORS occurred during cleanup:")
        for err in result["errors"]:
            print(f"  - {err}")
        return 1
    
    if dry_run:
        print(f"\nDry-run complete. Would redact {result['to_redact']} rows, delete {result['to_delete']} rows.")
        print("Run with --apply to execute these changes.")
    else:
        print(f"\nCleanup complete. Redacted {result['redacted']} rows, deleted {result['deleted']} rows.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
