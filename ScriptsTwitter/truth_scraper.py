import os
import json
import logging
import re
import time
from typing import Dict, Any, Optional, Tuple, List

import requests
import emoji

try:
    import cloudscraper  # type: ignore
except Exception:  # pragma: no cover
    cloudscraper = None

logger = logging.getLogger(__name__)


class TruthSocialScraper:
    def __init__(self, output_dir: str, download_emojis: bool = True):
        self.output_dir = output_dir
        self.temp_folder_video = os.path.join(self.output_dir, "TempVideo")
        self.output_folder_images = self.output_dir
        self.output_folder_media = self.output_dir
        self.emojis_dir = os.path.join(self.output_dir, "Emojis")
        self.download_emojis = bool(download_emojis)

        self.username = os.getenv("TRUTH_SOCIAL_USER", "automatizacion.ep")
        self.password = os.getenv("TRUTH_SOCIAL_PASS", "Auto1041")
        self.access_token = os.getenv("TRUTH_SOCIAL_TOKEN")
        self.cookies_raw = os.getenv("TRUTH_SOCIAL_COOKIES", "").strip()

        self.timeout = int(os.getenv("TRUTH_SOCIAL_TIMEOUT", "25"))
        self.max_retries = max(0, int(os.getenv("TRUTH_SOCIAL_RETRIES", "2")))

        primary_base = os.getenv("TRUTH_SOCIAL_API_BASE", "https://truthsocial.com").rstrip("/")
        fallback_base = os.getenv("TRUTH_SOCIAL_API_BASE_FALLBACK", "https://api.truthsocial.com").rstrip("/")
        self.api_bases: List[str] = [primary_base]
        if fallback_base and fallback_base not in self.api_bases:
            self.api_bases.append(fallback_base)

        self.session = self._build_requests_session()
        self._setup_directories()

    def _setup_directories(self):
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_folder_video, exist_ok=True)
        if self.download_emojis:
            os.makedirs(self.emojis_dir, exist_ok=True)

    def _build_requests_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Referer": "https://truthsocial.com/",
            "Origin": "https://truthsocial.com",
            "Connection": "keep-alive",
        })
        if self.access_token:
            session.headers["Authorization"] = f"Bearer {self.access_token}"
        if self.cookies_raw:
            session.headers["Cookie"] = self.cookies_raw
        return session

    def _build_cloudscraper_session(self):
        if cloudscraper is None:
            return None
        try:
            session = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
            session.headers.update(self.session.headers)
            return session
        except Exception as e:
            logger.warning(f"No se pudo inicializar cloudscraper: {e}")
            return None

    @staticmethod
    def _extract_cloudflare_ray(html: str) -> str:
        if not html:
            return ""
        match = re.search(r'Cloudflare Ray ID:\s*<strong[^>]*>([^<]+)</strong>', html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _looks_like_cloudflare_block(response: requests.Response) -> bool:
        if response.status_code not in (403, 429, 503):
            return False
        text = (response.text or "").lower()
        return "cloudflare" in text or "attention required" in text or "you have been blocked" in text

    def extract_post_id(self, url: str) -> Optional[str]:
        match = re.search(r'truthsocial\.com/@[^/]+/posts/(\d+)', url, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def download_image(self, url: str, path: str):
        if not url:
            return
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            with open(path, 'wb') as f:
                f.write(response.content)
            logger.info(f"Imagen descargada: {url} -> {path}")
        except Exception as e:
            logger.error(f"Error al descargar {url}: {e}")

    def clean_html(self, raw_html: str) -> str:
        cleanr = re.compile('<.*?>')
        cleantext = re.sub(cleanr, '', raw_html or "")
        return cleantext

    @staticmethod
    def extract_emojis(text: str) -> List[str]:
        """Extrae emojis (sin duplicados y preservando orden)."""
        found = [entry["emoji"] for entry in emoji.emoji_list(text or "")]
        deduped = []
        seen = set()
        for item in found:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    @staticmethod
    def replace_emojis_with_oemj(text: str, emoji_map: Dict[str, str]) -> str:
        for emoji_char, replacement in emoji_map.items():
            text = (text or "").replace(emoji_char, replacement)
        return text

    @staticmethod
    def remove_emojis_and_compact_spaces(text: str) -> str:
        """Elimina emojis y evita huecos dobles por su eliminación."""
        no_emojis = emoji.replace_emoji(text or "", replace="")
        return re.sub(r"\s+", " ", no_emojis).strip()

    def download_emoji(self, emoji_char: str, save_path: str):
        try:
            codepoints = "-".join(f"{ord(c):x}" for c in emoji_char)
            emoji_url = f"https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/{codepoints}.png"
            response = self.session.get(emoji_url, timeout=self.timeout)
            response.raise_for_status()
            with open(save_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"Emoji descargado: {emoji_char} -> {save_path}")
        except Exception as e:
            logger.error(f"Error al descargar emoji {emoji_char}: {e}")

    def _fetch_status_json(self, post_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
        last_error = ""

        for base_url in self.api_bases:
            api_url = f"{base_url}/api/v1/statuses/{post_id}"

            for attempt in range(self.max_retries + 1):
                try:
                    resp = self.session.get(api_url, timeout=self.timeout)
                except Exception as e:
                    last_error = f"Error de red en {api_url}: {e}"
                    if attempt < self.max_retries:
                        time.sleep(1.0 + attempt)
                    continue

                if resp.status_code == 200:
                    try:
                        return resp.json(), ""
                    except Exception as e:
                        last_error = f"JSON invalido en {api_url}: {e}"
                        break

                if self._looks_like_cloudflare_block(resp):
                    ray = self._extract_cloudflare_ray(resp.text or "")
                    ray_msg = f" (Ray ID: {ray})" if ray else ""
                    last_error = (
                        f"Bloqueado por Cloudflare en {api_url}{ray_msg}. "
                        "Prueba TRUTH_SOCIAL_TOKEN o TRUTH_SOCIAL_COOKIES."
                    )
                else:
                    snippet = (resp.text or "").strip().replace("\n", " ")
                    snippet = snippet[:240]
                    last_error = f"HTTP {resp.status_code} en {api_url}: {snippet}"

                if attempt < self.max_retries:
                    time.sleep(1.0 + attempt)

            # Fallback anti-bot con cloudscraper (si esta instalado)
            cf_session = self._build_cloudscraper_session()
            if not cf_session:
                continue

            try:
                resp = cf_session.get(api_url, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json(), ""

                if self._looks_like_cloudflare_block(resp):
                    ray = self._extract_cloudflare_ray(resp.text or "")
                    ray_msg = f" (Ray ID: {ray})" if ray else ""
                    last_error = f"Cloudscraper tambien bloqueado en {api_url}{ray_msg}."
                else:
                    snippet = (resp.text or "").strip().replace("\n", " ")
                    snippet = snippet[:240]
                    last_error = f"Cloudscraper HTTP {resp.status_code} en {api_url}: {snippet}"
            except Exception as e:
                last_error = f"Cloudscraper fallo en {api_url}: {e}"

        return None, last_error or "No se pudo recuperar el post de Truth Social"

    def run(self, post_url: str):
        logger.info(f"Empezando scrape de Truth Social para: {post_url}")

        post_id = self.extract_post_id(post_url)
        if not post_id:
            logger.error("No se pudo extraer el post ID de la URL.")
            return

        data_api, error = self._fetch_status_json(post_id)
        if not data_api:
            logger.error(f"Error al obtener post de Truth Social: {error}")
            return

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
            media_type = media.get("type")
            if media_type == "image" and not tweet_image:
                tweet_image = media.get("url", "") or media.get("preview_url", "")
            elif media_type in ["video", "gifv"]:
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

        # Rutas absolutas en formato coherente con index.csv + nombre de archivo.
        abs_profile = os.path.abspath(os.path.join(self.output_folder_images, "FotoPerfil.jpg")).replace("\\", "/")
        abs_post_img = os.path.abspath(os.path.join(self.output_folder_images, "FotoPost.jpg")).replace("\\", "/")

        if profile_image:
            self.download_image(profile_image, os.path.join(self.output_folder_images, "FotoPerfil.jpg"))
            data["profile_image"] = abs_profile
        else:
            data["profile_image"] = ""
        if tweet_image:
            self.download_image(tweet_image, os.path.join(self.output_folder_images, "FotoPost.jpg"))
            data["tweet_image"] = abs_post_img
        else:
            data["tweet_image"] = ""

        # Mantener semántica consistente con X para consumidores del JSON.
        data["tweet_video"] = ""

        text_fields = ["text", "name", "text_traducido"]
        if self.download_emojis:
            text_emojis = self.extract_emojis(data.get("text", ""))
            name_emojis = self.extract_emojis(data.get("name", ""))
            emojis = list(dict.fromkeys(text_emojis + name_emojis))
            emoji_map = {emoji_char: f"\\oemj {i + 1};" for i, emoji_char in enumerate(emojis)}

            for idx, emoji_char in enumerate(emojis, start=1):
                filename = f"emoji{idx}.png"
                filepath = os.path.join(self.emojis_dir, filename)
                self.download_emoji(emoji_char, filepath)

            for field in text_fields:
                if field in data:
                    data[field] = self.replace_emojis_with_oemj(data.get(field, ""), emoji_map)
        else:
            for field in text_fields:
                if field in data:
                    data[field] = self.remove_emojis_and_compact_spaces(data.get(field, ""))

        json_path = os.path.join(self.output_dir, "tweet_api.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Scraping de Truth Social finalizado (datos guardados en {json_path})")
