import os
import json
import logging
import re
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class TruthSocialScraper:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.temp_folder_video = os.path.join(self.output_dir, "TempVideo")
        self.output_folder_images = self.output_dir
        self.output_folder_media = self.output_dir
        self.emojis_dir = os.path.join(self.output_dir, "Emojis")
        
        self.username = os.getenv("TRUTH_SOCIAL_USER", "automatizacion.ep")
        self.password = os.getenv("TRUTH_SOCIAL_PASS", "Auto1041")
        self.access_token = os.getenv("TRUTH_SOCIAL_TOKEN")

        self._setup_directories()

    def _setup_directories(self):
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_folder_video, exist_ok=True)
        os.makedirs(self.emojis_dir, exist_ok=True)

    def extract_post_id(self, url: str) -> Optional[str]:
        match = re.search(r'truthsocial\.com/@[^/]+/posts/(\d+)', url)
        if match:
            return match.group(1)
        return None

    def download_image(self, url: str, path: str):
        if not url:
            return
        try:
            response = requests.get(url)
            response.raise_for_status()
            with open(path, 'wb') as f:
                f.write(response.content)
            logger.info(f"✅ Imagen descargada: {url} -> {path}")
        except Exception as e:
            logger.error(f"❌ Error al descargar {url}: {e}")

    def clean_html(self, raw_html: str) -> str:
        cleanr = re.compile('<.*?>')
        cleantext = re.sub(cleanr, '', raw_html)
        return cleantext

    def run(self, post_url: str):
        logger.info(f"Empezando scrape de Truth Social para: {post_url}")
        
        post_id = self.extract_post_id(post_url)
        if not post_id:
            logger.error("❌ No se pudo extraer el post ID de la URL.")
            return

        api_url = f"https://truthsocial.com/api/v1/statuses/{post_id}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        if self.access_token:
             headers["Authorization"] = f"Bearer {self.access_token}"
        
        r = requests.get(api_url, headers=headers)
        if r.status_code != 200:
             logger.error(f"❌ Error al obtener post de Truth Social: {r.status_code} - {r.text}")
             return

        data_api = r.json()
        
        content_html = data_api.get("content", "")
        text = self.clean_html(content_html)
        text_traducido = text

        profile_image = data_api.get("account", {}).get("avatar", "")
        name = data_api.get("account", {}).get("display_name", "")
        username = f"@{data_api.get('account', {}).get('acct', '')}"

        media_attachments = data_api.get("media_attachments", [])
        tweet_image = ""
        has_video = False

        for media in media_attachments:
             if media.get("type") == "image" and not tweet_image:
                  tweet_image = media.get("url", "")
             elif media.get("type") in ["video", "gifv"]:
                  has_video = True
                  
        data = {
            "text": text,
            "text_traducido": text_traducido,
            "tweet_image": tweet_image,
            "has_video": has_video,
            "profile_image": profile_image,
            "name": name,
            "username": username
        }
        
        if profile_image:
            self.download_image(profile_image, os.path.join(self.output_folder_images, "FotoPerfil.jpg"))
        if tweet_image:
            self.download_image(tweet_image, os.path.join(self.output_folder_images, "FotoPost.jpg"))
            
        json_path = os.path.join(self.output_dir, "tweet_api.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"✅ Scraping de Truth Social finalizado (Datos guardados en {json_path})")
