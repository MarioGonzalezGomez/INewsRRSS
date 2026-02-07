import logging
import sys
from inews_monitor import INewsMonitor, StoryParser

# Setup basic logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("InspectContent")

def inspect_content():
    print("=== Inspecting iNews Content ===")
    
    monitor = INewsMonitor()
    if not monitor.connection.connect():
        print("Failed to connect")
        return

    # Use the first watcher path
    path = monitor.watchers[0].path
    print(f"Inspecting path: {path}")
    
    if monitor.connection.navigate_to(path):
        entries = monitor.connection.list_entries()
        print(f"Found {len(entries)} entries. Searching for 'x.com' or 'twitter.com'...")
        
        found_count = 0
        for entry in entries:
            name = entry.get("name")
            if not name or name.startswith('.'): continue
            
            # Read content
            content = monitor.connection.read_story(name)
            if not content: continue

            # Check for URL indicators
            if "x.com" in content or "twitter.com" in content:
                found_count += 1
                print(f"\n--- MATCH FOUND: {name} ---")
                
                ap_tags = StoryParser.extract_ap_tags(content)
                print(f"  AP Tags with URL:")
                for ap in ap_tags:
                    if "x.com" in ap or "twitter.com" in ap:
                        print(f"    Raw: {ap}")
                        # Try to parse it to see what type it detects
                        r = StoryParser.parse_rotulo_from_ap(ap)
                        if r:
                            print(f"    Parsed -> Type: '{r.tipo}', Content: '{r.contenido}'")
                        else:
                            print(f"    Parsed -> FAILED")
                
            if found_count >= 5: break
            
        if found_count == 0:
            print("No entries found containing x.com or twitter.com")

    monitor.connection.disconnect()

if __name__ == "__main__":
    inspect_content()
