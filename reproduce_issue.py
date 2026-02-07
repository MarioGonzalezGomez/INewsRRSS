import json
import os
import sys
import importlib.util

def check_setup():
    print("=== Diagnosticando Configuración ===")
    
    # 1. Check Config
    if not os.path.exists("config.json"):
        print("[X] config.json NO encontrado")
        return
        
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
            print("[OK] config.json cargado")
    except Exception as e:
        print(f"[X] Error leyendo config.json: {e}")
        return

    # 2. Check Scripts Path
    scripts_path = config.get("content", {}).get("scripts_twitter_path")
    print(f"Path configurado: {scripts_path}")
    
    if os.path.exists(scripts_path):
        print("[OK] El directorio ScriptsTwitter existe")
    else:
        print("[X] El directorio ScriptsTwitter NO existe")

    # 3. Check Import
    if scripts_path not in sys.path:
        sys.path.append(scripts_path)
        
    try:
        import scrape_tweet_api
        print(f"[OK] scrape_tweet_api importado desde: {scrape_tweet_api.__file__}")
        
        # Try finding TweetScraper class
        if hasattr(scrape_tweet_api, 'TweetScraper'):
             print("[OK] Clase TweetScraper encontrada")
        else:
             print("[X] Clase TweetScraper NO encontrada en el módulo")
             
    except ImportError as e:
        print(f"[X] Error importando scrape_tweet_api: {e}")
    except Exception as e:
        print(f"[X] Error inesperado al importar: {e}")

    # 4. Check Content State
    state_file = os.path.join(config.get("content", {}).get("download_base_path", ""), "content_state.json")
    if os.path.exists(state_file):
        print(f"[INFO] content_state.json existe en {state_file}")
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
                print(f"   Contiene {len(data)} entradas")
        except:
             print("   Error leyendo content_state.json")
    else:
        print(f"[INFO] content_state.json NO existe en {state_file}")

if __name__ == "__main__":
    check_setup()
