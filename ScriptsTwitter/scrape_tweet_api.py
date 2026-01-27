import sys
import os
import json
import re
import logging
import argparse
import subprocess
from typing import Optional, Dict, List, Tuple, Any

import requests
from dotenv import load_dotenv
from yt_dlp import YoutubeDL
from langdetect import detect
from deep_translator import GoogleTranslator
import emoji

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

class TweetScraper:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.temp_folder_video = os.path.join(self.output_dir, "TempVideo")
        self.output_folder_images = self.output_dir
        self.output_folder_media = self.output_dir
        self.emojis_dir = os.path.join(self.output_dir, "Emojis")
        
        self.bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
        if not self.bearer_token:
            raise ValueError("❌ Error: TWITTER_BEARER_TOKEN no encontrado en variables de entorno.")

        self._setup_directories()

    def _setup_directories(self):
        """Crea los directorios necesarios si no existen."""
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_folder_video, exist_ok=True)
        os.makedirs(self.emojis_dir, exist_ok=True)

    def extract_tweet_id(self, tweet_url: str) -> Optional[str]:
        """Extrae el ID del tuit desde la URL."""
        match = re.search(r'/status/(\d+)', tweet_url)
        return match.group(1) if match else None

    def get_tweet_data(self, tweet_id: str) -> Dict[str, Any]:
        """Obtiene los datos del tuit desde la API de Twitter v2."""
        url = f"https://api.twitter.com/2/tweets/{tweet_id}"
        params = {
            "expansions": "author_id,attachments.media_keys",
            "tweet.fields": "created_at,text",
            "user.fields": "name,username,profile_image_url",
            "media.fields": "url,type"
        }
        headers = {
            "Authorization": f"Bearer {self.bearer_token}"
        }
        response = requests.get(url, params=params, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Error {response.status_code}: {response.text}")
        return response.json()

    def traducir_texto(self, texto: str) -> Tuple[str, str]:
        """Traduce el texto al español si detecta otro idioma."""
        try:
            idioma_detectado = detect(texto)
            logger.info(f"🌍 Idioma detectado: {idioma_detectado}")

            if idioma_detectado != "es":
                traducido = GoogleTranslator(source='auto', target='es').translate(texto)
                return texto.strip(), traducido.strip()
            else:
                return texto.strip(), texto.strip()
        except Exception as e:
            logger.error(f"❌ Error al traducir: {e}")
            return texto.strip(), texto.strip()

    def extract_relevant_data(self, json_data: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa el JSON de la API y extrae la información relevante."""
        tweet = json_data.get("data", {})
        includes = json_data.get("includes", {})
        user = includes.get("users", [{}])[0]

        media = includes.get("media", [])
        image_url = ""
        has_video = False

        for item in media:
            if item.get("type") == "photo" and not image_url:
                image_url = item.get("url")
            if item.get("type") in ["video", "animated_gif"]:
                has_video = True

        profile_image_url = user.get("profile_image_url", "")
        # Obtener imagen de perfil en mayor resolución
        profile_image_hd = re.sub(r'_normal(\.\w+)$', r'_400x400\1', profile_image_url)
        
        text = tweet.get("text", "").strip()
        # Limpiezas básicas de texto
        text = re.sub(r'^(?:@\w+\s*)+', '', text).strip()
        text = re.sub(r'https://t\.co/\S+', '', text).strip()
        
        text, texto_traducido = self.traducir_texto(text)
        
        return {
            "text": text,
            "text_traducido" : texto_traducido,
            "tweet_image": image_url,
            "has_video": has_video,
            "profile_image": profile_image_hd,
            "name": user.get("name", ""),
            "username": f"@{user.get('username', '')}"
        }

    def save_to_json(self, data: Dict[str, Any], path: str):
        """Guarda los datos en un archivo JSON."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def download_image(self, url: str, path: str):
        """Descarga una imagen desde una URL."""
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

    def download_video_or_gif(self, tweet_url: str):
        """Descarga el video o GIF usando yt-dlp."""
        try:
            ydl_opts = {
                'outtmpl': os.path.join(self.temp_folder_video, 'VideoOriginal.%(ext)s'),
                'quiet': True,
                'merge_output_format': 'mp4',
                'format': 'bestvideo+bestaudio/best'
            }
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([tweet_url])
            logger.info("✅ Video descargado correctamente.")
        except Exception as e:
            logger.error(f"❌ Error al descargar el video: {e}")

    def convertir_a_25fps(self, input_path: str, output_path: str):
        """Convierte el video a 25 fps usando ffmpeg."""
        try:
            # Verificar si ffmpeg está instalado
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            
            subprocess.run([
                "ffmpeg", "-i", input_path, "-r", "25", "-y", output_path
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("✅ Video convertido a 25 fps.")
        except FileNotFoundError:
             logger.error("❌ ffmpeg no encontrado. Asegúrate de tenerlo instalado y en el PATH.")
        except Exception as e:
            logger.error(f"❌ Error al convertir video a 25 fps: {e}")

    def extract_emojis(self, text: str) -> List[str]:
        """Extrae emojis únicos del texto."""
        return [entry['emoji'] for entry in emoji.emoji_list(text)]

    def download_emoji(self, emoji_char: str, save_path: str):
        """Descarga la imagen de un emoji desde Twemoji."""
        try:
            codepoints = "-".join(f"{ord(c):x}" for c in emoji_char)
            emoji_url = f"https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/{codepoints}.png"
            response = requests.get(emoji_url)
            response.raise_for_status()
            with open(save_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"✅ Emoji descargado: {emoji_char} → {save_path}")
        except Exception as e:
            logger.error(f"❌ Error al descargar {emoji_char}: {e}")

    def replace_emojis_with_oemj(self, text: str, emoji_map: Dict[str, str]) -> str:
        """Reemplaza emojis en el texto con etiquetas personalizadas."""
        for emoji_char, replacement in emoji_map.items():
            text = text.replace(emoji_char, replacement)
        return text

    def run(self, tweet_url: str):
        """Ejecuta el flujo principal de scraping."""
        tweet_id = self.extract_tweet_id(tweet_url)
        if not tweet_id:
            logger.error("❌ No se pudo extraer el ID del tuit.")
            return

        try:
            json_data = self.get_tweet_data(tweet_id)
            data = self.extract_relevant_data(json_data)

            # Descargar imágenes
            if data.get("profile_image"):
                self.download_image(data["profile_image"], os.path.join(self.output_folder_images, "FotoPerfil.jpg"))
            if data.get("tweet_image"):
                self.download_image(data["tweet_image"], os.path.join(self.output_folder_images, "FotoPost.jpg"))
            logger.info("✅ Imágenes descargadas si estaban disponibles.")

            # Manejo de Video
            video_original_path = os.path.join(self.temp_folder_video, "VideoOriginal.mp4")
            video_final_path = os.path.join(self.output_folder_media, "VideoPost.mp4")

            # Limpieza previa
            for path in [video_original_path, video_final_path]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.info(f"🗑️ Archivo anterior eliminado: {path}")
                    except Exception as e:
                        logger.error(f"❌ No se pudo eliminar {path}: {e}")

            if data.get("has_video"):
                self.download_video_or_gif(tweet_url)
                # yt-dlp puede guardar con otras extensiones, buscamos el archivo
                downloaded_files = os.listdir(self.temp_folder_video)
                downloaded_video = next((f for f in downloaded_files if f.startswith("VideoOriginal")), None)
                
                if downloaded_video:
                    full_downloaded_path = os.path.join(self.temp_folder_video, downloaded_video)
                    self.convertir_a_25fps(full_downloaded_path, video_final_path)
                    logger.info(f"✅ Video convertido y guardado en {video_final_path}")
                else:
                    logger.warning("⚠️ No se encontró el video descargado.")
            else:
                logger.info("ℹ️ El tuit no contiene video ni GIF.")

            # Manejo de Emojis
            text_emojis = self.extract_emojis(data["text"])
            name_emojis = self.extract_emojis(data["name"])
            emojis = list(dict.fromkeys(text_emojis + name_emojis))

            emoji_map = {emoji: f"\\oemj {i+1};" for i, emoji in enumerate(emojis)}

            for idx, emoji_char in enumerate(emojis, start=1):
                filename = f"emoji{idx}.png"
                filepath = os.path.join(self.emojis_dir, filename)
                self.download_emoji(emoji_char, filepath)

            data["text"] = self.replace_emojis_with_oemj(data["text"], emoji_map)
            data["name"] = self.replace_emojis_with_oemj(data["name"], emoji_map)
            data["text_traducido"] = self.replace_emojis_with_oemj(data["text_traducido"], emoji_map)

            # Guardar JSON
            json_path = os.path.join(self.output_dir, "tweet_api.json")
            self.save_to_json(data, json_path)
            logger.info(f"✅ JSON guardado: {json_path}")

        except Exception as e:
            logger.error(f"❌ Error al procesar el tuit: {e}", exc_info=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Tweet Data via API")
    parser.add_argument("url", help="URL del tuit a procesar")
    parser.add_argument("--output", "-o", default=r"C:\TrabajoIPF\Pruebas", help="Directorio de salida (default: C:\TrabajoIPF\Pruebas)")
    
    args = parser.parse_args()

    # Usar ruta actual si la ruta por defecto no es accesible o para pruebas
    if not os.path.exists(os.path.dirname(args.output)) and args.output == r"C:\TrabajoIPF\Pruebas":
         # Fallback a una carpeta local si la ruta hardcodeada original no tiene sentido en este entorno
         # Pero mantenemos el default solicitado por el usuario si existe
         pass

    try:
        scraper = TweetScraper(output_dir=args.output)
        scraper.run(args.url)
    except ValueError as e:
        logger.error(e)
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        sys.exit(1)