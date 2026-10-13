import os
import json
import argparse
from chain.logger import verify_decision_record

def verify_file(file_path: str):
    """Verify a decision record file"""
    if not os.path.exists(file_path):
        print(f"[ERR] File not found: {file_path}")
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        record = json.load(f)

    res = verify_decision_record(record)
    
    print("=========================================")
    print(f" DECISION VERIFICATION: {record.get('decision_id')}")
    print("=========================================")
    print(f"Timestamp UTC: {record.get('timestamp_utc')}")
    print(f"Action:        {record.get('action')}")
    print(f"Stored Hash:   {res['stored_hash']}")
    print(f"Computed Hash: {res['computed_hash']}")
    print(f"Prev Chain:    {record.get('previous_decision_hash')}")
    
    if res["valid"]:
        print("\n[PASS] VERIFICATION RESULT: PASS (Record is authentic and untampered)")
    else:
        print("\n[FAIL] VERIFICATION RESULT: FAIL (Record has been tampered with!)")
        
    return res["valid"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify Mortis SHA-256 Decision Proof")
    parser.add_argument("file_path", type=str, help="Path to decision JSON file")
    args = parser.parse_args()
    verify_file(args.file_path)
