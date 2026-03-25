import os
import json
import logging
import re
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class BlueskyScraper:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.temp_folder_video = os.path.join(self.output_dir, "TempVideo")
        self.output_folder_images = self.output_dir
        self.output_folder_media = self.output_dir
        self.emojis_dir = os.path.join(self.output_dir, "Emojis")
        
        # Aquí se cargarán las credenciales de Bluesky en el futuro
        self.username = os.getenv("BLUESKY_HANDLE", "automatizacion.ep@rtve.es")
        self.password = os.getenv("BLUESKY_PASSWORD", "Auto1041")

        self._setup_directories()

    def _setup_directories(self):
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_folder_video, exist_ok=True)
        os.makedirs(self.emojis_dir, exist_ok=True)

    def extract_post_id(self, url: str) -> Optional[tuple[str, str]]:
        match = re.search(r'bsky\.app/profile/([^/]+)/post/([^/?#]+)', url)
        if match:
            return match.group(1), match.group(2)
        return None

    def _get_did(self, handle: str) -> str:
        url = f"https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle={handle}"
        r = requests.get(url)
        if r.status_code == 200:
            return r.json().get("did", handle)
        return handle

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

    def run(self, post_url: str):
        logger.info(f"Empezando scrape de Bluesky para: {post_url}")
        
        ids = self.extract_post_id(post_url)
        if not ids:
            logger.error("❌ No se pudo extraer el handle y el post ID de la URL.")
            return

        handle, post_id = ids
        did = self._get_did(handle)

        thread_url = f"https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?uri=at://{did}/app.bsky.feed.post/{post_id}"
        r = requests.get(thread_url)
        if r.status_code != 200:
             logger.error(f"❌ Error al obtener el post desde Bluesky: {r.status_code}")
             return
        
        thread_data = r.json()
        post = thread_data.get("thread", {}).get("post", {})
        record = post.get("record", {})
        author = post.get("author", {})

        text = record.get("text", "")
        # Opcional: Implementar traducción si es necesario usando deep_translator como en X
        text_traducido = text 

        embed = post.get("embed", {})
        tweet_image = ""
        has_video = False

        if embed.get("$type") == "app.bsky.embed.images#view":
             images = embed.get("images", [])
             if images:
                  tweet_image = images[0].get("fullsize", "")
        elif embed.get("$type") == "app.bsky.embed.video#view":
             has_video = True

        profile_image = author.get("avatar", "")
        name = author.get("displayName", author.get("handle", ""))
        username = f"@{author.get('handle', '')}"

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
            
        logger.info(f"✅ Scraping de Bluesky finalizado (Datos guardados en {json_path})")
