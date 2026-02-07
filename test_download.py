import os
import logging
import time
from inews_monitor import ContentManager

# Setup basic logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestDownload")

# Config mirroring the user's
config = {
    "content": {
        "download_base_path": "\\\\172.28.142.62\\CAMIO4\\TwitterPrime", 
        "scripts_twitter_path": "C:\\TrabajosPRIME\\AppTuitsDoble\\ScriptsTwitter"
    }
}

def test_real_download():
    print("=== Testing Real Download & Index ===")
    
    cm = ContentManager(config, logger)
    
    # URL provided by user
    url = "https://x.com/Yolanda_Diaz_/status/1880677589356020087"
    
    print(f"Attempting to sync URL: {url}")
    
    # This should trigger download
    cm.sync_content([url], clean=False)
    
    # Check if index exists
    index_file = os.path.join(cm.download_base, "index.csv")
    if os.path.exists(index_file):
        print(f"[OK] index.csv found at {index_file}")
        with open(index_file, "r") as f:
            content = f.read()
            print("--- Index Content ---")
            print(content)
            print("---------------------")
            
            if url in content:
                print("[SUCCESS] URL found in index!")
            else:
                print("[FAILURE] URL NOT found in index (file might verify failed?)")
    else:
        print("[FAILURE] index.csv NOT created")

if __name__ == "__main__":
    try:
        test_real_download()
    except Exception as e:
        print(f"[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
