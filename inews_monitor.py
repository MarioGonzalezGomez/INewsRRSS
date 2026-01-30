#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
iNews Monitor Service
=====================
Servicio en segundo plano que monitorea un minutado de iNews,
detecta cambios y filtra entradas según el contenido de la etiqueta <ap>.

Uso:
    python inews_monitor.py              # Ejecutar en modo continuo
    python inews_monitor.py --once       # Ejecutar una sola vez
    python inews_monitor.py --config X   # Usar archivo de config alternativo
"""

import ftplib
import json
import logging
import argparse
import time
import re
import os
import sys
import csv
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from io import StringIO


class INewsConnection:
    """Gestiona la conexión FTP a un servidor iNews."""
    
    def __init__(self, host: str, user: str, password: str):
        self.host = host
        self.user = user
        self.password = password
        self.ftp: Optional[ftplib.FTP] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def connect(self) -> bool:
        """Establece conexión con el servidor iNews."""
        try:
            self.logger.info(f"Conectando a {self.host}...")
            self.ftp = ftplib.FTP(self.host, timeout=30)
            self.ftp.login(self.user, self.password)
            
            # Intentar configurar charset UTF-8
            try:
                self.ftp.sendcmd('SITE CHARSET UTF-8')
            except ftplib.error_perm:
                pass
            
            self.logger.info("Conexión establecida correctamente")
            return True
        except ftplib.all_errors as e:
            self.logger.error(f"Error de conexión: {e}")
            return False
    
    def disconnect(self):
        """Cierra la conexión FTP."""
        if self.ftp:
            try:
                self.ftp.quit()
                self.logger.info("Desconectado del servidor")
            except:
                pass
            self.ftp = None
    
    def is_connected(self) -> bool:
        """Verifica si la conexión está activa."""
        if not self.ftp:
            return False
        try:
            self.ftp.voidcmd("NOOP")
            return True
        except:
            return False
    
    def ensure_connected(self) -> bool:
        """Asegura que haya una conexión activa, reconectando si es necesario."""
        if not self.is_connected():
            self.disconnect()
            return self.connect()
        return True
    
    def navigate_to(self, path: str) -> bool:
        """Navega a una ruta específica en el servidor, carpeta por carpeta."""
        if not self.ensure_connected():
            return False
        try:
            self.ftp.cwd("/")  # Ir a raíz primero
            if path.startswith("/"):
                path = path[1:]
            if path:
                # Navegar carpeta por carpeta
                folders = path.replace("\\", "/").split("/")
                for folder in folders:
                    if folder:  # Ignorar strings vacíos
                        self.ftp.cwd(folder)
            self.logger.debug(f"Navegado a: {self.ftp.pwd()}")
            return True
        except ftplib.error_perm as e:
            self.logger.error(f"Error navegando a {path}: {e}")
            return False
    
    def list_directory(self, path: str = None) -> List[str]:
        """Lista los archivos en el directorio actual o en la ruta especificada."""
        if not self.ensure_connected():
            return []
        
        try:
            if path:
                self.navigate_to(path)
            
            files = []
            self.ftp.retrlines('LIST', files.append)
            return files
        except ftplib.error_perm as e:
            self.logger.error(f"Error listando directorio: {e}")
            return []
    
    def list_entries(self, path: str = None) -> List[Dict]:
        """
        Lista las entradas del directorio parseando la salida LIST.
        Retorna una lista de diccionarios con información de cada entrada.
        """
        raw_list = self.list_directory(path)
        entries = []
        
        for line in raw_list:
            entry = self._parse_list_entry(line)
            if entry:
                entries.append(entry)
        
        return entries
    
    def _parse_list_entry(self, line: str) -> Optional[Dict]:
        """Parsea una línea de la salida LIST."""
        # Formato típico FTP: drwxr-xr-x 1 user group size date name
        # iNews puede tener formato diferente, adaptamos según necesidad
        parts = line.split()
        if len(parts) < 9:
            # Formato simplificado: solo nombre
            if parts:
                return {"name": parts[-1], "raw": line, "is_dir": line.startswith('d')}
            return None
        
        return {
            "permissions": parts[0],
            "is_dir": parts[0].startswith('d'),
            "size": parts[4] if len(parts) > 4 else "0",
            "name": " ".join(parts[8:]),  # El nombre puede tener espacios
            "raw": line
        }
    
    def read_story(self, filename: str) -> Optional[str]:
        """Lee el contenido de una historia/entrada del minutado."""
        if not self.ensure_connected():
            return None
        
        try:
            content_lines = []
            
            def collect_line(line):
                content_lines.append(line)
            
            self.ftp.retrlines(f'RETR {filename}', collect_line)
            return '\n'.join(content_lines)
        except ftplib.error_perm as e:
            self.logger.error(f"Error leyendo {filename}: {e}")
            return None


class Rotulo:
    """Representa un rótulo extraído de una etiqueta <ap>."""
    
    def __init__(self, canal: str, tipo: str, contenido: str):
        self.canal = canal      # Ej: CG1
        self.tipo = tipo        # Ej: Faldon, X_Total, X_Faldon
        self.contenido = contenido  # La URL o texto del contenido
    
    def __repr__(self):
        return f"Rotulo(canal='{self.canal}', tipo='{self.tipo}', contenido='{self.contenido}')"
    
    def to_dict(self) -> Dict:
        return {
            "canal": self.canal,
            "tipo": self.tipo,
            "contenido": self.contenido
        }


class StoryParser:
    """Parser para contenido NSML de iNews."""
    
    # Tipos de rótulo que nos interesan (para filtrado)
    TIPOS_VALIDOS = ["X_Total", "X_Faldon"]
    
    @staticmethod
    def extract_ap_tags(content: str) -> List[str]:
        """Extrae todos los contenidos de etiquetas <ap>."""
        # Regex para encontrar contenido entre <ap> y </ap>
        pattern = r'<ap>(.*?)</ap>'
        matches = re.findall(pattern, content, re.DOTALL)
        return matches
    
    @staticmethod
    def parse_rotulo_from_ap(ap_content: str) -> Optional[Rotulo]:
        """
        Parsea un rótulo desde el contenido de una etiqueta <ap>.
        
        Soporta múltiples formatos:
        1. Con [canal]: [A1-A2-A3] 10 QR -- 00010829: |contenido|
        2. Sin canal: Faldon | 00013523: |contenido(
        3. Antiguo: [CG1] Faldon | 00013523: |contenido(
        
        Extrae:
        - Canal: Entre corchetes [XXX] o vacío
        - Tipo: Palabra que identifica el tipo de rótulo
        - Contenido: Texto entre el primer | y ( o siguiente |
        """
        if not ap_content or not ap_content.strip():
            return None
        
        try:
            # Buscar canal entre corchetes [XXX]
            canal_match = re.search(r'\[([A-Za-z0-9\-]+)\]', ap_content)
            canal = canal_match.group(1).strip() if canal_match else ""
            
            # Si hay canal, obtener el texto después de él
            if canal_match:
                after_canal = ap_content[canal_match.end():].strip()
            else:
                after_canal = ap_content.strip()
            
            # El tipo es una palabra que sigue patrones:
            # - Después de números/códigos: "QR", "Titulo", "Tema", etc.
            # - O la primera palabra: "Faldon", "Titular", etc.
            tipo = ""
            
            # Intentar extraer tipo después de patrón "NN -- " (código)
            tipo_match = re.search(r'--\s+\d+:\s+([A-Za-z_0-9]+)', after_canal)
            if tipo_match:
                tipo = tipo_match.group(1).strip()
            
            # Si no encontró con patrón anterior, buscar palabra antes de | o después de números
            if not tipo:
                # Buscar patrón: números, espacios, luego palabras antes de |
                tipo_match = re.search(r'\d+\s+([A-Za-z_][A-Za-z_0-9]*(?:\s+\d+)?)', after_canal)
                if tipo_match:
                    tipo = tipo_match.group(1).strip()
                else:
                    # Última opción: primera palabra no numérica
                    words = after_canal.split()
                    for word in words:
                        if not word.replace('-', '').isdigit() and word not in [']', '[[', ']]', '|', '--']:
                            tipo = word.strip()
                            break
            
            # Extraer contenido entre el primer | y el siguiente | o (
            contenido = ""
            # Patrón: después de | y antes de ( o siguiente |
            contenido_match = re.search(r'\|([^|\(]+)', after_canal)
            if contenido_match:
                contenido = contenido_match.group(1).strip()
                # Limpiar espacios extras
                contenido = ' '.join(contenido.split())
            
            # Solo retornar si tenemos al menos tipo (canal es opcional)
            if tipo:
                return Rotulo(canal=canal, tipo=tipo, contenido=contenido)
                
        except Exception as e:
            # Si falla el parsing, retornar None silenciosamente
            pass
        
        return None
    
    @staticmethod
    def extract_rotulos(content: str) -> List[Rotulo]:
        """
        Extrae todos los rótulos de todas las etiquetas <ap> de una historia.
        """
        ap_tags = StoryParser.extract_ap_tags(content)
        rotulos = []
        
        for ap in ap_tags:
            rotulo = StoryParser.parse_rotulo_from_ap(ap)
            if rotulo:
                rotulos.append(rotulo)
        
        return rotulos
    
    @staticmethod
    def extract_rotulos_filtrados(content: str, tipos_validos: List[str] = None) -> List[Rotulo]:
        """
        Extrae solo los rótulos que coinciden con los tipos válidos.
        
        Args:
            content: Contenido NSML de la historia
            tipos_validos: Lista de tipos a filtrar. Por defecto: ["X_Total", "X_Faldon"]
        
        Returns:
            Lista de rótulos que coinciden con los tipos válidos
        """
        if tipos_validos is None:
            tipos_validos = StoryParser.TIPOS_VALIDOS
        
        all_rotulos = StoryParser.extract_rotulos(content)
        
        # Filtrar por tipo (case-insensitive)
        tipos_lower = [t.lower() for t in tipos_validos]
        filtered = [r for r in all_rotulos if r.tipo.lower() in tipos_lower]
        
        return filtered
    
    @staticmethod
    def extract_urls_from_story(content: str) -> List[str]:
        """
        Extrae las URLs/contenidos de los rótulos válidos (X_Total, X_Faldon).
        
        Returns:
            Lista de URLs/contenidos encontrados
        """
        rotulos = StoryParser.extract_rotulos_filtrados(content)
        urls = [r.contenido for r in rotulos if r.contenido]
        return urls
    
    @staticmethod
    def extract_field(content: str, field_id: str) -> Optional[str]:
        """Extrae el valor de un campo específico del NSML."""
        # Buscar <f id=field_id>valor</f>
        pattern = rf'<f id={field_id}[^>]*>([^<]*)</f>'
        match = re.search(pattern, content)
        if match:
            return match.group(1)
        return None
    
    @staticmethod
    def extract_story_info(content: str) -> Dict:
        """Extrae información relevante de una historia NSML."""
        rotulos = StoryParser.extract_rotulos(content)
        rotulos_filtrados = StoryParser.extract_rotulos_filtrados(content)
        
        info = {
            "title": StoryParser.extract_field(content, "title") or "",
            "status": StoryParser.extract_field(content, "status") or "",
            "modify_by": StoryParser.extract_field(content, "modify-by") or "",
            "modify_date": StoryParser.extract_field(content, "modify-date") or "",
            "audio_time": StoryParser.extract_field(content, "audio-time") or "",
            "ap_tags": StoryParser.extract_ap_tags(content),
            "has_ap_content": len(StoryParser.extract_ap_tags(content)) > 0,
            "rotulos": [r.to_dict() for r in rotulos],
            "rotulos_filtrados": [r.to_dict() for r in rotulos_filtrados],
            "urls": [r.contenido for r in rotulos_filtrados if r.contenido]
        }
        return info
    
    @staticmethod
    def has_valid_rotulos(content: str) -> bool:
        """
        Verifica si la historia tiene al menos un rótulo válido (X_Total o X_Faldon).
        """
        rotulos = StoryParser.extract_rotulos_filtrados(content)
        return len(rotulos) > 0
    
    @staticmethod
    def matches_ap_filter(content: str, filter_pattern: str) -> bool:
        """
        Verifica si alguna etiqueta <ap> coincide con el patrón de filtro.
        
        NOTA: Este método ahora también verifica que haya rótulos válidos
        (X_Total o X_Faldon) si filter_pattern está vacío.
        
        Args:
            content: Contenido NSML de la historia
            filter_pattern: Patrón a buscar (texto o regex). 
                          Si es "ROTULOS" (especial), filtra por tipos válidos.
        
        Returns:
            True si hay coincidencia
        """
        # Modo especial: filtrar solo entradas con rótulos válidos
        if filter_pattern == "ROTULOS" or filter_pattern == "":
            return StoryParser.has_valid_rotulos(content)
        
        ap_contents = StoryParser.extract_ap_tags(content)
        
        for ap in ap_contents:
            # Primero intentar como texto simple (contiene)
            if filter_pattern in ap:
                return True
            # Luego como regex
            try:
                if re.search(filter_pattern, ap):
                    return True
            except re.error:
                pass  # Patrón no es regex válido, ya intentamos como texto
        
        return False



import shutil
import importlib.util

class ContentManager:
    """Gestiona la descarga y limpieza de contenido multimedia de Twitter."""
    
    def __init__(self, config: Dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.download_base = config.get("content", {}).get("download_base_path", "Descargas")
        self.state_file = os.path.join(self.download_base, "content_state.json")
        
        # Cargar módulo de Twitter dinámicamente
        self.tweet_scraper_class = self._load_twitter_scraper_class()
        
        # Asegurar directorio base
        os.makedirs(self.download_base, exist_ok=True)
        
        # Estado actual {url: tweet_id}
        self.state = self._load_state()

    def _load_twitter_scraper_class(self):
        """Carga la clase TweetScraper desde la ruta configurada."""
        scripts_path = self.config.get("content", {}).get("scripts_twitter_path")
        if not scripts_path or not os.path.exists(scripts_path):
            self.logger.warning(f"Ruta de scripts Twitter no válida: {scripts_path}")
            return None
            
        sys.path.append(scripts_path)
        try:
            import scrape_tweet_api
            
            # Definir la clase personalizada heredando de la importada
            class CustomTweetScraper(scrape_tweet_api.TweetScraper):
                def run(self, tweet_url: str):
                    """Sobrescribe run para personalizar paths y JSON."""
                    tweet_id = self.extract_tweet_id(tweet_url)
                    if not tweet_id:
                        print("❌ No se pudo extraer ID")
                        return

                    try:
                        # Crear carpeta para este tweet
                        tweet_dir = os.path.join(self.output_dir, tweet_id)
                        os.makedirs(tweet_dir, exist_ok=True)
                        
                        # Actualizar directorios de salida de la instancia
                        self.output_dir = tweet_dir  # Base para el JSON
                        self.output_folder_images = tweet_dir
                        self.output_folder_media = tweet_dir
                        self.temp_folder_video = os.path.join(tweet_dir, "TempVideo")
                        self.emojis_dir = os.path.join(tweet_dir, "Emojis")
                        self._setup_directories()

                        # --- Lógica original adaptada ---
                        json_data = self.get_tweet_data(tweet_id)
                        data = self.extract_relevant_data(json_data)

                        # Rutas absolutas para el JSON
                        abs_profile = os.path.abspath(os.path.join(tweet_dir, "FotoPerfil.jpg")).replace("\\", "/")
                        abs_post_img = os.path.abspath(os.path.join(tweet_dir, "FotoPost.jpg")).replace("\\", "/")
                        abs_video = os.path.abspath(os.path.join(tweet_dir, "VideoPost.mp4")).replace("\\", "/")

                        # Descargar imágenes
                        if data.get("profile_image"):
                            self.download_image(data["profile_image"], os.path.join(self.output_folder_images, "FotoPerfil.jpg"))
                            data["profile_image"] = abs_profile
                        else:
                            data["profile_image"] = ""

                        if data.get("tweet_image"):
                            self.download_image(data["tweet_image"], os.path.join(self.output_folder_images, "FotoPost.jpg"))
                            data["tweet_image"] = abs_post_img
                        else:
                            data["tweet_image"] = ""

                        # Manejo de Video
                        data["tweet_video"] = "" # Default vacío
                        
                        video_original_path = os.path.join(self.temp_folder_video, "VideoOriginal.mp4")
                        video_final_path = os.path.join(self.output_folder_media, "VideoPost.mp4")

                        # Limpieza previa de video
                        for path in [video_original_path, video_final_path]:
                            if os.path.exists(path):
                                try: os.remove(path)
                                except: pass

                        if data.get("has_video"):
                            self.download_video_or_gif(tweet_url)
                            downloaded_files = os.listdir(self.temp_folder_video)
                            downloaded_video = next((f for f in downloaded_files if f.startswith("VideoOriginal")), None)
                            
                            if downloaded_video:
                                full_downloaded_path = os.path.join(self.temp_folder_video, downloaded_video)
                                self.convertir_a_25fps(full_downloaded_path, video_final_path)
                                data["tweet_video"] = abs_video
                                print(f"✅ Video guardado: {abs_video}")

                        # Eliminar has_video si no se quiere en JSON final o dejarlo
                        if "has_video" in data: del data["has_video"]

                        # Emojis (Lógica igual, rutas relativas dentro de carpeta tweet)
                        text_emojis = self.extract_emojis(data.get("text", ""))
                        name_emojis = self.extract_emojis(data.get("name", ""))
                        emojis = list(dict.fromkeys(text_emojis + name_emojis))
                        emoji_map = {emoji: f"\\oemj {i+1};" for i, emoji in enumerate(emojis)}

                        for idx, emoji_char in enumerate(emojis, start=1):
                            filename = f"emoji{idx}.png"
                            filepath = os.path.join(self.emojis_dir, filename)
                            self.download_emoji(emoji_char, filepath)

                        if "text" in data: data["text"] = self.replace_emojis_with_oemj(data["text"], emoji_map)
                        if "name" in data: data["name"] = self.replace_emojis_with_oemj(data["name"], emoji_map)
                        if "text_traducido" in data: data["text_traducido"] = self.replace_emojis_with_oemj(data["text_traducido"], emoji_map)

                        # Guardar JSON
                        json_path = os.path.join(self.output_dir, "tweet_api.json")
                        self.save_to_json(data, json_path)
                        print(f"✅ JSON guardado en: {json_path}")
                        
                        # Limpiar temp video
                        try: shutil.rmtree(self.temp_folder_video)
                        except: pass

                    except Exception as e:
                        print(f"❌ Error procesando tweet {tweet_id}: {e}")
                        import traceback
                        traceback.print_exc()

            return CustomTweetScraper
            
        except ImportError as e:
            self.logger.error(f"Error importando scrape_tweet_api: {e}")
            return None

    def _load_state(self) -> Dict[str, str]:
        """Carga el estado de descargas desde JSON."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _save_state(self):
        """Guarda el estado actual."""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error guardando estado: {e}")

    def sync_content(self, current_urls: List[str]):
        """Sincroniza el contenido: descarga nuevos, borra obsoletos."""
        if not self.tweet_scraper_class:
            self.logger.error("No se puede sincronizar: Scraper no cargado.")
            return

        current_set = set(current_urls)
        known_set = set(self.state.keys())

        # Identificar nuevos y obsoletos
        new_urls = current_set - known_set
        obsolete_urls = known_set - current_set

        # Procesar NUEVOS
        if new_urls:
            self.logger.info(f"Detectadas {len(new_urls)} URLs nuevas para descargar.")
            scraper = self.tweet_scraper_class(output_dir=self.download_base) # output_dir base, luego se ajusta en run
            
            for url in new_urls:
                try:
                    self.logger.info(f"Descargando contenido para: {url}")
                    # Extraer ID para guardar en estado
                    tweet_id = scraper.extract_tweet_id(url)
                    if tweet_id:
                        scraper.run(url)
                        self.state[url] = tweet_id
                        self._save_state()
                    else:
                        self.logger.warning(f"URL inválida (no se pudo extraer ID): {url}")
                except Exception as e:
                    self.logger.error(f"Error descargando {url}: {e}")

        # Procesar OBSOLETOS
        if obsolete_urls:
            self.logger.info(f"Detectadas {len(obsolete_urls)} URLs obsoletas. Limpiando...")
            for url in obsolete_urls:
                tweet_id = self.state.get(url)
                if tweet_id:
                    folder_path = os.path.join(self.download_base, tweet_id)
                    if os.path.exists(folder_path):
                        try:
                            self.logger.info(f"Eliminando carpeta obsoleta: {folder_path}")
                            shutil.rmtree(folder_path)
                        except Exception as e:
                            self.logger.error(f"Error eliminando carpeta {folder_path}: {e}")
                
                del self.state[url]
                self._save_state()
        
        # Siempre actualizar el índice maestro al final de la sincronización
        self._update_index()

    def _update_index(self):
        """Genera/Actualiza el archivo index.csv con el mapeo URL -> Ruta Local JSON."""
        index_file = os.path.join(self.download_base, "index.csv")
        
        try:
            with open(index_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                # Escribir encabezado
                writer.writerow(["URL", "RUTA LOCAL"])
                
                # Escribir datos
                for url, tweet_id in self.state.items():
                    # Construir ruta absoluta al tweet_api.json
                    json_path = os.path.join(self.download_base, tweet_id, "tweet_api.json")
                    abs_json_path = os.path.abspath(json_path)
                    
                    # Verificar si existe para no meter basura (opcional, pero recomendable)
                    if os.path.exists(json_path):
                        writer.writerow([url, abs_json_path])
            
            self.logger.info(f"Índice maestro actualizado: {index_file}")
        except Exception as e:
            self.logger.error(f"Error actualizando índice maestro: {e}")


class INewsMonitor:
    """Servicio de monitoreo de minutado de iNews."""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self._setup_logging()
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.content_manager = ContentManager(self.config, self.logger)
        
        self.connection = INewsConnection(
            host=self.config["inews"]["host"],
            user=self.config["inews"]["user"],
            password=self.config["inews"]["password"]
        )
        
        self.running = False
        self.last_entries: Dict[str, str] = {}  # nombre -> hash/contenido para detectar cambios
    
    def _load_config(self) -> Dict:
        """Carga la configuración desde el archivo JSON."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"ERROR: No se encontró el archivo de configuración: {self.config_path}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Archivo de configuración inválido: {e}")
            sys.exit(1)
    
    def _setup_logging(self):
        """Configura el sistema de logging."""
        log_config = self.config.get("logging", {})
        log_level = getattr(logging, log_config.get("level", "INFO"))
        log_file = log_config.get("file", "inews_monitor.log")
        
        # Configurar formato
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Handler para archivo
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        
        # Handler para consola
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        # Configurar logger raíz
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
    
    def get_rundown_entries(self) -> List[Dict]:
        """Obtiene la lista de entradas del minutado configurado."""
        rundown_path = self.config["inews"]["rundown_path"]
        return self.connection.list_entries(rundown_path)
    
    def process_entry(self, entry: Dict) -> Optional[Dict]:
        """
        Procesa una entrada del minutado: lee su contenido y extrae información.
        
        Returns:
            Diccionario con la información de la entrada si pasa el filtro, None si no
        """
        entry_name = entry.get("name", "")
        if not entry_name or entry.get("is_dir", False):
            return None
        
        # Leer contenido NSML
        content = self.connection.read_story(entry_name)
        if not content:
            return None
        
        # Verificar filtro de etiqueta <ap>
        ap_filter = self.config["monitor"].get("ap_filter", "")
        if not StoryParser.matches_ap_filter(content, ap_filter):
            return None
        
        # Extraer información
        story_info = StoryParser.extract_story_info(content)
        
        return {
            "entry_name": entry_name,
            "content": content,
            "info": story_info,
            "timestamp": datetime.now().isoformat()
        }
    
    def check_for_changes(self, entry_name: str, content: str) -> bool:
        """Verifica si una entrada ha cambiado desde la última revisión."""
        content_hash = hash(content)
        previous_hash = self.last_entries.get(entry_name)
        
        if previous_hash != content_hash:
            self.last_entries[entry_name] = content_hash
            return True
        return False
    
    def run_once(self) -> List[Dict]:
        """
        Ejecuta una sola iteración del monitoreo.
        
        Returns:
            Lista de entradas que pasaron el filtro
        """
        self.logger.info("Iniciando revisión del minutado...")
        
        if not self.connection.connect():
            self.logger.error("No se pudo conectar al servidor iNews")
            return []
        
        try:
            entries = self.get_rundown_entries()
            self.logger.info(f"Encontradas {len(entries)} entradas en el minutado")
            
            filtered_results = []
            all_found_urls = []
            
            for entry in entries:
                result = self.process_entry(entry)
                if result:
                    # Recolectar URLs activas
                    urls = result['info'].get('urls', [])
                    all_found_urls.extend(urls)
                    
                    is_new_or_changed = self.check_for_changes(
                        result["entry_name"],
                        result["content"]
                    )
                    
                    if is_new_or_changed:
                        urls = result['info'].get('urls', [])
                        rotulos = result['info'].get('rotulos_filtrados', [])
                        
                        self.logger.info(
                            f"Entrada filtrada: {result['entry_name']} - "
                            f"Título: {result['info']['title']} - "
                            f"URLs: {len(urls)}"
                        )
                        filtered_results.append(result)
                        
                        # Mostrar rótulos y URLs
                        print("\n" + "="*60)
                        print(f"ENTRADA: {result['entry_name']}")
                        print(f"TÍTULO: {result['info']['title']}")
                        print("-"*60)
                        print("RÓTULOS ENCONTRADOS:")
                        for r in rotulos:
                            print(f"  - Canal: {r['canal']}, Tipo: {r['tipo']}")
                            print(f"    Contenido/URL: {r['contenido']}")
                        print("-"*60)
                        print("URLs PARA DESCARGA:")
                        for url in urls:
                            print(f"  → {url}")
                        print("="*60 + "\n")
            
            # Sincronizar contenido (descargar nuevos, borrar viejos)
            self.content_manager.sync_content(all_found_urls)

            self.logger.info(f"Revisión completada. {len(filtered_results)} entradas nuevas/modificadas")
            return filtered_results
            
        finally:
            self.connection.disconnect()
    
    def run(self):
        """Ejecuta el monitoreo continuo."""
        interval = self.config["monitor"].get("interval_seconds", 30)
        self.running = True
        
        self.logger.info(f"Iniciando monitoreo continuo (intervalo: {interval}s)")
        self.logger.info(f"Ruta del minutado: {self.config['inews']['rundown_path']}")
        self.logger.info("Presiona Ctrl+C para detener")
        
        try:
            while self.running:
                self.run_once()
                
                self.logger.debug(f"Esperando {interval} segundos hasta la próxima revisión...")
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.logger.info("Deteniendo monitoreo...")
            self.running = False
        finally:
            self.connection.disconnect()
            self.logger.info("Monitor detenido")
    
    def stop(self):
        """Detiene el monitoreo."""
        self.running = False


def main():
    """Punto de entrada principal."""
    parser = argparse.ArgumentParser(
        description='Monitor de minutado iNews',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python inews_monitor.py                    # Ejecutar en modo continuo
  python inews_monitor.py --once             # Ejecutar una sola vez
  python inews_monitor.py --config mi_config.json  # Usar config alternativo
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        default='config.json',
        help='Ruta al archivo de configuración (default: config.json)'
    )
    
    parser.add_argument(
        '--once', '-o',
        action='store_true',
        help='Ejecutar una sola revisión y terminar'
    )
    
    args = parser.parse_args()
    
    # Cambiar al directorio del script para encontrar el config
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    print("="*60)
    print("  iNews Monitor Service")
    print("="*60)
    
    monitor = INewsMonitor(config_path=args.config)
    
    if args.once:
        results = monitor.run_once()
        print(f"\nTotal de entradas filtradas: {len(results)}")
    else:
        monitor.run()


if __name__ == "__main__":
    main()
