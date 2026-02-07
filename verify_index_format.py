import os
import json
import logging
import csv
from inews_monitor import ContentManager

# Dummy Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VerifyIndex")

# Mock Config
config = {
    "content": {
        "download_base_path": "\\\\172.28.142.62\\CAMIO4\\TwitterPrime", 
        "scripts_twitter_path": "C:\\TrabajosPRIME\\AppTuitsDoble\\ScriptsTwitter"
    }
}

def verify_index_format():
    print("=== Verifying Index Format ===")
    
    # 1. Initialize ContentManager
    cm = ContentManager(config, logger)
    
    # 2. Mock State (Simulate a downloaded tweet)
    test_url = "https://x.com/Yolanda_Diaz_/status/1880677589356020087"
    test_id = "1880677589356020087"
    
    print(f"Injecting state: {test_url} -> {test_id}")
    cm.state[test_url] = test_id
    
    # Ensure the directory exists effectively for the test to pass 'os.path.exists' checks in _update_index
    target_dir = os.path.join(cm.download_base, test_id)
    target_json = os.path.join(target_dir, "tweet_api.json")
    
    # We need to ensure checks pass, but we can't easily write to network path if auth is needed
    # Ideally checking existence. If it doesn't exist, we skip writing to CSV, so we can't verify format.
    # Assuming user has access or we can just mock os.path.exists
    
    original_exists = os.path.exists
    def mock_exists(path):
        if path == target_json:
            return True
        return original_exists(path)
    
    os.path.exists = mock_exists
    print("MOCKED os.path.exists for target JSON")

    # 3. Trigger Update Index
    print("Running _update_index...")
    try:
        cm._update_index()
    except Exception as e:
        print(f"Error updating index: {e}")
    finally:
        os.path.exists = original_exists # Restore

    # 4. Read Result
    index_file = os.path.join(cm.download_base, "index.csv")
    if os.path.exists(index_file):
        print(f"[OK] index.csv created at {index_file}")
        with open(index_file, "r") as f:
            reader = csv.reader(f, delimiter=";")
            headers = next(reader)
            print(f"Headers: {headers}")
            
            t = list(reader)
            if not t:
                print("[X] CSV is empty!")
                return

            row = t[0]
            print(f"Row: {row}")
            if len(row) < 2:
                 print("[X] Row has less than 2 columns")
                 return
                 
            path_in_csv = row[1]
            print(f"Path in CSV: {path_in_csv}")
            
            if path_in_csv.endswith("tweet_api.json"):
                print("[X] FAILED: Path still points to json file")
            elif path_in_csv.endswith(test_id) or path_in_csv.endswith(test_id + os.sep) or path_in_csv.endswith(test_id + "\\"):
                 print("[OK] SUCCEEDED: Path points to folder")
            else:
                 # Check if it is a folder path (no extension)
                 _, ext = os.path.splitext(path_in_csv)
                 if not ext:
                     print("[OK] SUCCEEDED: Path appears to be a folder (no extension)")
                 else:
                     print(f"[?] WARNING: Path ends with {ext}")

    else:
        print("[X] index.csv NOT created")

if __name__ == "__main__":
    verify_index_format()
