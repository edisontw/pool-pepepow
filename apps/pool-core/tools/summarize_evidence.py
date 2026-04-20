import json
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

def get_summary(log_path, window_minutes=None):
    path = Path(log_path)
    if not path.exists():
        return None
    
    now = datetime.now(timezone.utc)
    records = []
    with open(path, "r") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if window_minutes:
                    ts_str = rec.get("timestamp")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if (now - ts).total_seconds() > window_minutes * 60:
                            continue
                records.append(rec)
            except Exception:
                continue
    
    if not records:
        return None
        
    summary = {
        "total": len(records),
        "accepted": sum(1 for r in records if r.get("shareHashValidationStatus") == "share-hash-valid"),
        "rejected": sum(1 for r in records if r.get("shareHashValidationStatus") == "share-hash-invalid"),
        "shareHashStatus": Counter(r.get("shareHashValidationStatus", "none") for r in records),
        "targetStatus": Counter(r.get("targetValidationStatus", "none") for r in records),
        "rejectReasons": Counter(r.get("rejectReason") for r in records if r.get("rejectReason")),
        "jobStatus": Counter(r.get("jobStatus") for r in records),
    }
    return summary

def print_summary(summary, title):
    print(f"=== {title} ===")
    if not summary:
        print("No records found.")
        return
    print(f"Total: {summary['total']}")
    print(f"Accepted: {summary['accepted']}")
    print(f"Rejected: {summary['rejected']}")
    ratio = (summary['accepted'] / summary['total'] * 100) if summary['total'] > 0 else 0
    print(f"Accepted Ratio: {ratio:.2f}%")
    
    print("\nShare Hash Status:")
    for k, v in sorted(summary['shareHashStatus'].items()):
        print(f"  {k}: {v}")
    
    print("\nTarget Status:")
    for k, v in sorted(summary['targetStatus'].items()):
        print(f"  {k}: {v}")
        
    print("\nReject Reasons:")
    for k, v in sorted(summary['rejectReasons'].items()):
        print(f"  {k}: {v}")

    print("\nJob Status:")
    for k, v in sorted(summary['jobStatus'].items()):
        print(f"  {k}: {v}")

if __name__ == "__main__":
    log_path = "/home/ubuntu/pool-pepepow/.runtime/live-stratum/submit-evidence.jsonl"
    
    since_ts = None
    win = None
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.startswith("2026"):
            since_ts = datetime.fromisoformat(arg.replace("Z", "+00:00"))
            title = f"Summary since {arg}"
        else:
            win = int(arg)
            title = f"Summary (Last {win}m)"
    else:
        title = "Full Summary"
        
    records = []
    path = Path(log_path)
    now = datetime.now(timezone.utc)
    with open(path, "r") as f:
        for line in f:
            try:
                rec = json.loads(line)
                ts_str = rec.get("timestamp")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if since_ts and ts < since_ts:
                        continue
                    if win and (now - ts).total_seconds() > win * 60:
                        continue
                records.append(rec)
            except Exception:
                continue

    summary = {
        "total": len(records),
        "accepted": sum(1 for r in records if r.get("shareHashValidationStatus") == "share-hash-valid"),
        "rejected": sum(1 for r in records if r.get("shareHashValidationStatus") == "share-hash-invalid"),
        "shareHashStatus": Counter(r.get("shareHashValidationStatus", "none") for r in records),
        "targetStatus": Counter(r.get("targetValidationStatus", "none") for r in records),
        "rejectReasons": Counter(r.get("rejectReason") for r in records if r.get("rejectReason")),
        "jobStatus": Counter(r.get("jobStatus") for r in records),
    }
    
    print_summary(summary, title)
