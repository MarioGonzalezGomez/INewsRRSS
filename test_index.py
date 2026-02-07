import os
import json
import logging
import csv
from inews_monitor import ContentManager

# Dummy Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestIndex")

# Mock Config
config = {
    "content": {
        "download_base_path": "\\\\172.28.142.62\\CAMIO4\\TwitterPrime", # Using the path from user/config
        "scripts_twitter_path": "C:\\TrabajosPRIME\\AppTuitsDoble\\ScriptsTwitter"
    }
}

def test_index_generation():
    print("=== Testing Index Generation ===")
    
    # 1. Initialize ContentManager
    cm = ContentManager(config, logger)
    
    # 2. Mock State (Simulate a downloaded tweet)
    test_url = "https://x.com/Yolanda_Diaz_/status/1880677589356020087"
    test_id = "1880677589356020087"
    
    print(f"Injecting state: {test_url} -> {test_id}")
    cm.state[test_url] = test_id
    
    # Ensure the directory exists effectively for the test to pass 'os.path.exists' checks in _update_index
    # We might need to fake the file system or actually check if the folder exists.
    # The user provided path: \\172.28.142.62\CAMIO4\TwitterPrime\1880677589356020087
    
    target_dir = os.path.join(cm.download_base, test_id)
    target_json = os.path.join(target_dir, "tweet_api.json")
    
    print(f"Checking if target exists: {target_json}")
    if not os.path.exists(target_json):
        print(f"[WARN] Target file does not exist. _update_index check might fail.")
        # Attempt to create dummy if local, but this is a network path...
        # If network path is not accessible, that explains why index isn't updating.
    else:
        print("✅ Target file exists.")

    # 3. Trigger Update Index
    print("Running _update_index...")
    cm._update_index()
    
    # 4. Read Result
    index_file = os.path.join(cm.download_base, "index.csv")
    if os.path.exists(index_file):
        print(f"[OK] index.csv created at {index_file}")
        with open(index_file, "r") as f:
            print("--- Content ---")
            print(f.read())
            print("---------------")
    else:
        print("[X] index.csv NOT created")

if __name__ == "__main__":
    test_index_generation()
