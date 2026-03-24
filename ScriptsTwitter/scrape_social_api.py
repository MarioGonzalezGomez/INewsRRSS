import sys
import logging
import argparse
from urllib.parse import urlparse

# Importamos los diferentes scrapers
from scrape_tweet_api import TweetScraper
from bluesky_scraper import BlueskyScraper
from truth_scraper import TruthSocialScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Scrape Social Media Data (Multi-platform)")
    parser.add_argument("url", help="URL del post a procesar")
    parser.add_argument("--output", "-o", default=r"C:\TrabajoIPF\Pruebas", help="Directorio de salida (default: C:\TrabajoIPF\Pruebas)")
    
    args = parser.parse_args()

    domain = urlparse(args.url).netloc.lower()

    try:
        if "twitter.com" in domain or "x.com" in domain:
            logger.info("Enrutando a X / Twitter Scraper...")
            scraper = TweetScraper(output_dir=args.output)
            scraper.run(args.url)
            
        elif "bsky.app" in domain:
            logger.info("Enrutando a Bluesky Scraper...")
            scraper = BlueskyScraper(output_dir=args.output)
            scraper.run(args.url)
            
        elif "truthsocial.com" in domain:
            logger.info("Enrutando a Truth Social Scraper...")
            scraper = TruthSocialScraper(output_dir=args.output)
            scraper.run(args.url)
            
        else:
            logger.error(f"Dominio no soportado: {domain}")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error inesperado procesando la red social: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
