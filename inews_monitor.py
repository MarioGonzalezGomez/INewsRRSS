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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from io import StringIO
import io
import requests
from urllib.parse import urlparse

# Force UTF-8 for stdout/stderr to avoid crashes with emojis on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


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

    def list_story_names(self, path: str = None) -> List[str]:
        """
        Lista nombres de stories de forma robusta.
        Prioriza NLST (nombres puros) y usa LIST parseado como respaldo.
        """
        if not self.ensure_connected():
            return []

        # Intento principal: NLST
        try:
            if path:
                self.navigate_to(path)

            names: List[str] = []
            self.ftp.retrlines('NLST', names.append)

            cleaned = []
            for raw_name in names:
                name = (raw_name or "").strip().rstrip("/")
                if not name:
                    continue
                if "/" in name:
                    name = name.split("/")[-1]
                cleaned.append(name)

            # Deduplicar preservando orden
            deduped = []
            seen = set()
            for name in cleaned:
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(name)
            return deduped

        except ftplib.all_errors as e:
            self.logger.warning(f"NLST falló, usando LIST parseado como respaldo: {e}")

        # Respaldo: LIST parseado
        entries = self.list_entries(path)
        story_names = []
        for entry in entries:
            name = entry.get("name", "")
            if not name or entry.get("is_dir", False):
                continue
            story_names.append(name)
        return story_names
    
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
    SOCIAL_URL_PATTERN = re.compile(
        r'https?://(?:www\.)?(?:x\.com|twitter\.com|bsky\.app|truthsocial\.com)/[^\s<>\]\|"\')]+',
        re.IGNORECASE
    )
    
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
    def _normalize_url(url: str) -> str:
        """Limpia separadores frecuentes al final de una URL extraida del NSML."""
        clean = (url or "").strip().strip("'\"")
        # iNews suele concatenar metadatos tras la URL: "(In  Dur", "|", etc.
        for sep in ("(", "|", "<", ">", "]", ")", " ", "\t", "\r", "\n"):
            if sep in clean:
                clean = clean.split(sep, 1)[0]
        return clean.rstrip(".,;:|)]}>")

    @staticmethod
    def _extract_social_urls_from_text(text: str) -> List[str]:
        if not text:
            return []
        matches = StoryParser.SOCIAL_URL_PATTERN.findall(text)
        normalized = []
        for m in matches:
            clean = StoryParser._normalize_url(m)
            if clean:
                normalized.append(clean)
        return normalized

    @staticmethod
    def extract_social_urls(content: str) -> List[str]:
        """
        Extrae URLs sociales de forma robusta:
        1) rotulos filtrados por tipo
        2) todos los rotulos parseados
        3) contenido bruto de <ap>
        4) contenido completo NSML (respaldo)
        """
        urls: List[str] = []

        filtered_rotulos = StoryParser.extract_rotulos_filtrados(content)
        for rotulo in filtered_rotulos:
            urls.extend(StoryParser._extract_social_urls_from_text(rotulo.contenido))

        all_rotulos = StoryParser.extract_rotulos(content)
        for rotulo in all_rotulos:
            urls.extend(StoryParser._extract_social_urls_from_text(rotulo.contenido))

        for ap in StoryParser.extract_ap_tags(content):
            urls.extend(StoryParser._extract_social_urls_from_text(ap))

        # Buscar también en todo el contenido bruto por si hay formato NSML raro
        urls.extend(StoryParser._extract_social_urls_from_text(content))

        deduped = []
        seen = set()
        for url in urls:
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(url)
        return deduped
    
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
        social_urls = StoryParser.extract_social_urls(content)
        
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
            "urls": social_urls
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
        if filter_pattern == "ROTULOS":
            return StoryParser.has_valid_rotulos(content)

        if filter_pattern == "":
            return len(StoryParser.extract_social_urls(content)) > 0
        
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
import subprocess
import importlib.util

def _robust_rmtree(path: str, logger=None) -> bool:
    """
    Elimina un directorio de forma robusta, manejando errores de permisos.
    Intenta múltiples métodos si el primero falla.
    
    Returns:
        True si se eliminó correctamente, False si falló
    """
    import stat
    
    def handle_remove_readonly(func, path, exc_info):
        """Handler para errores de permisos en shutil.rmtree"""
        # Si es error de permisos, intentar quitar readonly y reintentar
        if exc_info[0] == PermissionError:
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except:
                pass
    
    # Método 1: shutil.rmtree con handler de errores
    try:
        shutil.rmtree(path, onerror=handle_remove_readonly)
        if not os.path.exists(path):
            return True
    except Exception as e:
        if logger:
            logger.debug(f"shutil.rmtree falló para {path}: {e}")
    
    # Método 2: Usar cmd rmdir /s /q (Windows)
    if os.name == 'nt':
        try:
            result = subprocess.run(
                ['cmd', '/c', 'rmdir', '/s', '/q', path],
                capture_output=True,
                timeout=30
            )
            if not os.path.exists(path):
                return True
        except Exception as e:
            if logger:
                logger.debug(f"cmd rmdir falló para {path}: {e}")
        
        # Método 3: takeown + icacls + rmdir (requiere permisos)
        try:
            subprocess.run(
                ['takeown', '/f', path, '/r', '/d', 'y'],
                capture_output=True,
                timeout=30
            )
            subprocess.run(
                ['icacls', path, '/grant', f'{os.environ.get("USERNAME", "Everyone")}:F', '/t'],
                capture_output=True,
                timeout=30
            )
            subprocess.run(
                ['cmd', '/c', 'rmdir', '/s', '/q', path],
                capture_output=True,
                timeout=30
            )
            if not os.path.exists(path):
                return True
        except Exception as e:
            if logger:
                logger.debug(f"takeown/icacls falló para {path}: {e}")
    
    # Si llegamos aquí, no pudimos eliminar
    if logger:
        logger.warning(f"No se pudo eliminar carpeta: {path}")
    return False


class ContentManager:
    """Gestiona la descarga y limpieza de contenido multimedia multi-plataforma."""
    
    def __init__(self, config: Dict, logger: logging.Logger, scripts_twitter_path: str = None):
        self.config = config
        self.logger = logger
        self.download_base = config.get("content", {}).get("download_base_path", "Descargas")
        raw_download_emojis = config.get("content", {}).get("download_emojis", True)
        if isinstance(raw_download_emojis, str):
            self.download_emojis = raw_download_emojis.strip().lower() in ("1", "true", "yes", "on")
        else:
            self.download_emojis = bool(raw_download_emojis)
        # Permitir override del scripts_twitter_path desde config global
        if scripts_twitter_path:
            self.config.setdefault("content", {})["scripts_twitter_path"] = scripts_twitter_path
        self.state_file = os.path.join(self.download_base, "content_state.json")
        self.logger.info(f"Descarga de emojis habilitada: {self.download_emojis}")
        
        # Cargar módulo de Twitter dinámicamente
        self.scripts_path = self._resolve_scripts_path()
        self.tweet_scraper_class = self._load_twitter_scraper_class()
        self.bluesky_scraper_class = self._load_scraper_class("bluesky_scraper", "BlueskyScraper")
        self.truth_scraper_class = self._load_scraper_class("truth_scraper", "TruthSocialScraper")
        
        # Asegurar directorio base
        os.makedirs(self.download_base, exist_ok=True)
        
        # Estado actual {url: tweet_id}
        self.state = self._load_state()

    def _resolve_scripts_path(self) -> Optional[str]:
        scripts_path = self.config.get("content", {}).get("scripts_twitter_path")

        if not scripts_path or not os.path.exists(scripts_path):
            local_scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ScriptsTwitter")
            if os.path.exists(local_scripts):
                self.logger.warning(f"Ruta config no valida ({scripts_path}), usando local: {local_scripts}")
                scripts_path = local_scripts
            else:
                self.logger.error(f"Ruta de scripts Twitter no valida y no hallada localmente: {scripts_path}")
                return None

        if scripts_path not in sys.path:
            sys.path.append(scripts_path)
        return scripts_path

    def _load_scraper_class(self, module_name: str, class_name: str):
        if not self.scripts_path:
            return None
        try:
            module = __import__(module_name, fromlist=[class_name])
            return getattr(module, class_name)
        except Exception as e:
            self.logger.error(f"Error importando {class_name} desde {module_name}: {e}")
            return None

    def _load_twitter_scraper_class(self):
        """Carga la clase TweetScraper desde la ruta configurada."""
        scripts_path = self.scripts_path
        
        # Fallback: intentar buscar ScriptsTwitter en el directorio actual si la config falla
        if not scripts_path or not os.path.exists(scripts_path):
            local_scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ScriptsTwitter")
            if os.path.exists(local_scripts):
                self.logger.warning(f"Ruta config no válida ({scripts_path}), usando local: {local_scripts}")
                scripts_path = local_scripts
            else:
                self.logger.error(f"Ruta de scripts Twitter no válida y no hallada localmente: {scripts_path}")
                return None
            
        sys.path.append(scripts_path)
        try:
            if scripts_path not in sys.path:
                sys.path.append(scripts_path)
            
            import scrape_tweet_api
            print(f"[OK] Motor de descarga Twitter cargado correctamente.")
            
            # Definir la clase personalizada heredando de la importada
            class CustomTweetScraper(scrape_tweet_api.TweetScraper):
                def __init__(self, output_dir: str, download_emojis: bool = True):
                    """Inicializa sin crear directorios aún (se crean por tweet)."""
                    self.download_emojis = download_emojis
                    super().__init__(output_dir)
                    # No llamar a _setup_directories() aquí para evitar crear
                    # carpetas innecesarias en la raíz base
                
                def _setup_directories(self):
                    """Crea directorios base, opcionalmente la carpeta de emojis."""
                    os.makedirs(self.output_dir, exist_ok=True)
                    os.makedirs(self.temp_folder_video, exist_ok=True)
                    if self.download_emojis:
                        os.makedirs(self.emojis_dir, exist_ok=True)

                def get_tweet_data(self, tweet_id: str) -> Dict:
                    """
                    Fuerza la solicitud del campo note_tweet para obtener texto completo
                    en tweets largos (evita truncado en data.text).
                    """
                    url = f"https://api.twitter.com/2/tweets/{tweet_id}"
                    params = {
                        "expansions": "author_id,attachments.media_keys",
                        "tweet.fields": "created_at,text,note_tweet",
                        "user.fields": "name,username,profile_image_url",
                        "media.fields": "url,type"
                    }
                    headers = {"Authorization": f"Bearer {self.bearer_token}"}
                    response = requests.get(url, params=params, headers=headers)
                    if response.status_code != 200:
                        raise Exception(f"Error {response.status_code}: {response.text}")
                    return response.json()

                def extract_relevant_data(self, json_data: Dict) -> Dict:
                    """
                    Mantiene la logica base, pero prioriza note_tweet.text cuando existe.
                    """
                    data = super().extract_relevant_data(json_data)
                    tweet = json_data.get("data", {})
                    note_tweet = tweet.get("note_tweet", {})
                    full_text = note_tweet.get("text") if isinstance(note_tweet, dict) else ""

                    if full_text:
                        text = full_text.strip()
                        text = re.sub(r'^(?:@\w+\s*)+', '', text).strip()
                        text = re.sub(r'https://t\.co/\S+', '', text).strip()
                        text, texto_traducido = self.traducir_texto(text)
                        data["text"] = text
                        data["text_traducido"] = texto_traducido

                    return data

                def _parse_fps(self, value: str) -> Optional[float]:
                    """Convierte un valor de fps tipo '30000/1001' a float."""
                    if not value:
                        return None
                    try:
                        if "/" in value:
                            num, den = value.split("/", 1)
                            den_f = float(den)
                            if den_f == 0:
                                return None
                            return float(num) / den_f
                        return float(value)
                    except (ValueError, TypeError):
                        return None

                def _probe_video(self, input_path: str) -> Tuple[Optional[float], str]:
                    """Obtiene fps y formato contenedor usando ffprobe."""
                    try:
                        result = subprocess.run(
                            [
                                "ffprobe",
                                "-v", "error",
                                "-select_streams", "v:0",
                                "-show_entries", "stream=avg_frame_rate,r_frame_rate",
                                "-show_entries", "format=format_name",
                                "-of", "json",
                                input_path
                            ],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        payload = json.loads(result.stdout or "{}")
                        stream = (payload.get("streams") or [{}])[0]
                        format_name = (payload.get("format") or {}).get("format_name", "")
                        fps_expr = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""
                        fps = self._parse_fps(fps_expr)
                        return fps, format_name
                    except Exception as e:
                        print(f"[i] No se pudo analizar video con ffprobe ({input_path}): {e}")
                        return None, ""

                def convertir_a_25fps(self, input_path: str, output_path: str) -> bool:
                    """
                    Convierte el video a 25 fps solo si es necesario.
                    Si ya está en MP4 a 25 fps, copia el archivo directamente.
                    """
                    try:
                        subprocess.run(
                            ["ffmpeg", "-version"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=True
                        )

                        fps, format_name = self._probe_video(input_path)
                        is_mp4 = input_path.lower().endswith(".mp4") or ("mp4" in (format_name or "").lower())
                        if fps is not None and abs(fps - 25.0) < 0.05 and is_mp4:
                            if os.path.abspath(input_path) != os.path.abspath(output_path):
                                shutil.copy2(input_path, output_path)
                            print("[i] Video ya está en MP4 a 25 fps; se omite conversión.")
                            return True

                        subprocess.run(
                            ["ffmpeg", "-i", input_path, "-r", "25", "-y", output_path],
                            check=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        print("[OK] Video convertido a 25 fps.")
                        return True
                    except FileNotFoundError:
                        print("[X] ffmpeg no encontrado en PATH.")
                        return False
                    except Exception as e:
                        print(f"[X] Error al convertir video a 25 fps: {e}")
                        return False

                def run(self, tweet_url: str):
                    """Sobrescribe run para personalizar paths y JSON."""
                    tweet_id = self.extract_tweet_id(tweet_url)
                    if not tweet_id:
                        print(f"[X] No se pudo extraer ID")
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
                                if self.convertir_a_25fps(full_downloaded_path, video_final_path) and os.path.exists(video_final_path):
                                    data["tweet_video"] = abs_video
                                    print(f"[OK] Video guardado: {abs_video}")
                                else:
                                    print(f"[X] No se pudo preparar el video final: {video_final_path}")

                        # Eliminar has_video si no se quiere en JSON final o dejarlo
                        if "has_video" in data: del data["has_video"]

                        # Emojis (Lógica igual, rutas relativas dentro de carpeta tweet)
                        if self.download_emojis:
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
                        print(f"[OK] JSON guardado en: {json_path}")
                        
                        # Limpiar temp video
                        try: shutil.rmtree(self.temp_folder_video)
                        except: pass

                        # FINALMENTE: Asegurar permisos para todos los archivos generados
                        self._grant_permissions(tweet_dir)

                    except Exception as e:
                        print(f"[X] Error procesando tweet {tweet_id}: {e}")
                        import traceback
                        traceback.print_exc()

                def _grant_permissions(self, path: str):
                    """Otorga control total a Everyone/Todos sobre la carpeta y su contenido."""
                    try:
                        # Intentar grupo en Inglés
                        subprocess.run(['icacls', path, '/grant', 'Everyone:F', '/t', '/c', '/q'], 
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        # Intentar grupo en Español
                        subprocess.run(['icacls', path, '/grant', 'Todos:F', '/t', '/c', '/q'], 
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception as e:
                        print(f"⚠️ Warning: No se pudieron establecer permisos explícitos: {e}")

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

    def _detect_platform(self, url: str) -> Optional[str]:
        domain = urlparse(url).netloc.lower()
        if "x.com" in domain or "twitter.com" in domain:
            return "twitter"
        if "bsky.app" in domain:
            return "bluesky"
        if "truthsocial.com" in domain:
            return "truth"
        return None

    @staticmethod
    def _safe_id(value: str) -> str:
        return re.sub(r'[^A-Za-z0-9_.-]+', '_', value or "")

    def _extract_content_id(self, url: str, platform: str) -> Optional[str]:
        if platform == "twitter":
            match = re.search(r'/status/(\d+)', url)
            return match.group(1) if match else None

        if platform == "bluesky":
            match = re.search(r'bsky\.app/profile/([^/]+)/post/([^/?#]+)', url, re.IGNORECASE)
            if not match:
                return None
            handle = self._safe_id(match.group(1))
            post_id = self._safe_id(match.group(2))
            return f"bsky_{handle}_{post_id}"

        if platform == "truth":
            match = re.search(r'truthsocial\.com/@[^/]+/posts/(\d+)', url, re.IGNORECASE)
            return f"truth_{match.group(1)}" if match else None

        return None

    def _get_json_path_for_id(self, content_id: str) -> str:
        return os.path.join(self.download_base, content_id, "tweet_api.json")

    def sync_content(self, current_urls: List[str], clean: bool = True):
        """Sincroniza el contenido: descarga nuevos, borra obsoletos si clean=True."""
        current_set = set(current_urls)
        known_set = set(self.state.keys())

        # Identificar nuevos y obsoletos
        new_urls = current_set - known_set
        obsolete_urls = known_set - current_set

        # Procesar NUEVOS
        if new_urls:
            self.logger.info(f"Detectadas {len(new_urls)} URLs nuevas para descargar.")
            
            for url in new_urls:
                try:
                    platform = self._detect_platform(url)
                    if not platform:
                        self.logger.warning(f"URL con dominio no soportado: {url}")
                        continue

                    content_id = self._extract_content_id(url, platform)
                    if not content_id:
                        self.logger.warning(f"URL inválida (no se pudo extraer ID): {url}")
                        continue
                    self.logger.info(f"Descargando contenido para: {url}")
                    if platform == "twitter":
                        if not self.tweet_scraper_class:
                            self.logger.error("Scraper de Twitter no cargado.")
                            continue
                        scraper = self.tweet_scraper_class(
                            output_dir=self.download_base,
                            download_emojis=self.download_emojis
                        )
                        scraper.run(url)
                    elif platform == "bluesky":
                        if not self.bluesky_scraper_class:
                            self.logger.error("Scraper de Bluesky no cargado.")
                            continue
                        target_dir = os.path.join(self.download_base, content_id)
                        scraper = self.bluesky_scraper_class(output_dir=target_dir)
                        scraper.run(url)
                    else:
                        if not self.truth_scraper_class:
                            self.logger.error("Scraper de Truth Social no cargado.")
                            continue
                        target_dir = os.path.join(self.download_base, content_id)
                        scraper = self.truth_scraper_class(output_dir=target_dir)
                        scraper.run(url)

                    if os.path.exists(self._get_json_path_for_id(content_id)):
                        self.state[url] = content_id
                        self._save_state()
                    else:
                        self.logger.warning(f"No se generó tweet_api.json para {url} (id={content_id})")
                except Exception as e:
                    self.logger.error(f"Error descargando {url}: {e}")

        # Procesar OBSOLETOS (Sólo si clean es True)
        if clean and obsolete_urls:
            self.logger.info(f"Detectadas {len(obsolete_urls)} URLs obsoletas. Limpiando...")
            for url in obsolete_urls:
                tweet_id = self.state.get(url)
                if tweet_id:
                    folder_path = os.path.join(self.download_base, tweet_id)
                    if os.path.exists(folder_path):
                        try:
                            self.logger.info(f"Eliminando carpeta obsoleta: {folder_path}")
                            if not _robust_rmtree(folder_path, self.logger):
                                self.logger.error(f"No se pudo eliminar carpeta {folder_path}")
                        except Exception as e:
                            self.logger.error(f"Error eliminando carpeta {folder_path}: {e}")
                
                del self.state[url]
                self._save_state()
        elif obsolete_urls:
            self.logger.info(f"Detectadas {len(obsolete_urls)} URLs obsoletas (Limpieza PENDIENTE).")
        
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
                        # Usar el directorio padre (carpeta del tweet) en lugar del archivo json
                        abs_folder_path = os.path.dirname(abs_json_path)
                        writer.writerow([url, abs_folder_path])
            
            self.logger.info(f"Índice maestro actualizado: {index_file}")
        except Exception as e:
            self.logger.error(f"Error actualizando índice maestro: {e}")


class RundownWatcher:
    """
    Gestiona el estado y monitoreo de UN minutado específico.
    Cada watcher tiene su propia conexión FTP para permitir procesamiento en paralelo.
    """
    def __init__(self, name: str, config: Dict, inews_config: Dict):
        self.name = name
        self.path = config.get("rundown_path")
        self.interval = config.get("interval_seconds", 30)
        self.ap_filter = config.get("ap_filter", "")
        raw_debug = config.get("debug_parser")
        if raw_debug is None:
            raw_debug = os.getenv("INEWS_DEBUG_PARSER", "0")
        if isinstance(raw_debug, str):
            self.debug_parser = raw_debug.strip().lower() in ("1", "true", "yes", "on")
        else:
            self.debug_parser = bool(raw_debug)
        
        # Cada watcher tiene su propia conexión FTP independiente
        self.connection = INewsConnection(
            host=inews_config["host"],
            user=inews_config["user"],
            password=inews_config["password"]
        )
        
        self.last_run_time = 0
        self.last_entries: Dict[str, str] = {}  # entry_name -> hash
        self.active_urls: List[str] = [] # URLs encontradas en la última pasada exitosa
        self.has_run = False # Indica si el watcher ha completado al menos una ejecución
        self.logger = logging.getLogger(f"Watcher_{name}")
        self._lock = threading.Lock()  # Protege acceso concurrente al estado del watcher

    def is_due(self) -> bool:
        """Verifica si es hora de ejecutar este monitor."""
        return (time.time() - self.last_run_time) >= self.interval

    def disconnect(self):
        """Cierra la conexión FTP de este watcher."""
        self.connection.disconnect()

    def process(self) -> List[Dict]:
        """
        Ejecuta la revisión de este minutado.
        Retorna la lista de entradas filtradas (nuevas/modificadas).
        Actualiza self.active_urls con TODAS las URLs vigentes en el minutado.
        
        Cada watcher navega con su propia conexión, permitiendo ejecución en paralelo.
        """
        self.logger.info(f"Ejecutando revisión para {self.name}...")
        self.last_run_time = time.time()
        
        # Asegurar conexión y navegar al directorio correcto
        if not self.connection.ensure_connected():
            self.logger.error(f"No se pudo conectar a iNews para {self.name}")
            return []
        
        if not self.connection.navigate_to(self.path):
            self.logger.error(f"Fallo navegando a {self.path}")
            return []
        
        story_names = self.connection.list_story_names(self.path)
        if not story_names:
            self.logger.warning(f"No se encontraron stories o error al listar {self.path}")
            # Si falla, no limpiamos active_urls para evitar borrar contenido por error de red
            return []
        
        if self.debug_parser:
            preview = ", ".join(story_names[:15])
            self.logger.info(
                f"[DEBUG_PARSER] stories_listadas={len(story_names)} "
                f"primeras={preview if preview else '-'}"
            )
        
        filtered_results = []
        current_urls = []
        scanned_count = 0
        matched_count = 0
        
        # Nombres especiales de iNews que no son stories válidas
        INVALID_STORY_NAMES = {'ibc', 'data', 'metadata', 'locator', 'info'}
        
        def is_valid_story_name(name: str) -> bool:
            """Verifica si un nombre parece ser una story válida de iNews."""
            # Nombres vacíos o muy cortos (1-2 caracteres como 't', 'f', 'a')
            if not name:
                return False
            
            # Nombres que empiezan por '.'
            if name.startswith('.'):
                return False
            
            # Nombres conocidos del sistema
            if name.lower() in INVALID_STORY_NAMES:
                return False
            
            # Nombres con / o \ (rutas como 'a/b')
            if '/' in name or '\\' in name:
                return False
            
            # Patrones linX (lin1, lin2, etc.)
            if re.match(r'^lin\d+$', name.lower()):
                return False
            
            # Nombres con caracteres no alfanuméricos (como '???')
            # Las stories válidas suelen ser alfanuméricas con guiones/underscores/dos puntos
            if not re.search(r'[A-Za-z0-9]', name):
                return False
            
            
            
            return True
        
        for entry_name in story_names:
            if not entry_name:
                continue
            scanned_count += 1
            
            # Filtrar entradas que no son stories válidas
            if not is_valid_story_name(entry_name):
                continue
            
            content = self.connection.read_story(entry_name)
            if not content:
                continue
            
            # Filtros
            if not StoryParser.matches_ap_filter(content, self.ap_filter):
                continue
            matched_count += 1
                
            story_info = StoryParser.extract_story_info(content)
            if self.debug_parser:
                urls = story_info.get("urls", [])
                preview = ", ".join(urls[:6]) if urls else "-"
                self.logger.info(
                    f"[DEBUG_PARSER] {entry_name} ap_tags={len(story_info.get('ap_tags', []))} "
                    f"rotulos={len(story_info.get('rotulos', []))} "
                    f"rotulos_filtrados={len(story_info.get('rotulos_filtrados', []))} "
                    f"urls={len(urls)} -> {preview}"
                )
            
            # Recolectar URLs (de todas las historias válidas)
            current_urls.extend(story_info.get('urls', []))
            
            # Detectar cambios
            content_hash = hash(content)
            previous_hash = self.last_entries.get(entry_name)
            
            if previous_hash != content_hash:
                self.last_entries[entry_name] = content_hash
                
                result = {
                    "entry_name": entry_name,
                    "content": content,
                    "info": story_info,
                    "timestamp": datetime.now().isoformat(),
                    "watcher_name": self.name
                }
                filtered_results.append(result)

        if self.debug_parser:
            self.logger.info(
                f"[DEBUG_PARSER] resumen stories_escaneadas={scanned_count} "
                f"stories_con_match={matched_count} urls_totales={len(current_urls)}"
            )
        
        self.active_urls = current_urls
        self.has_run = True
        return filtered_results


class ProfileRunner:
    """
    Ejecuta la monitorización de UN perfil (programa de TV).
    Cada perfil tiene sus propios watchers, ContentManager y tipos de rótulo.
    Múltiples ProfileRunners pueden ejecutarse en paralelo.
    """
    
    def __init__(self, profile_name: str, profile_config: Dict, inews_config: Dict, 
                 scripts_twitter_path: str, logger: logging.Logger):
        self.profile_name = profile_name
        self.display_name = profile_config.get("name", profile_name)
        self.profile_config = profile_config
        self.inews_config = inews_config
        self.logger = logging.getLogger(f"Profile_{profile_name}")
        
        # Tipos de rótulo específicos de este perfil
        self.tipos_validos = profile_config.get("monitor", {}).get(
            "tipos_rotulo_validos", ["X_Total", "X_Faldon"]
        )
        
        # Paralelismo configurable por perfil
        self.max_workers = profile_config.get("monitor", {}).get("max_workers", 5)
        
        # ContentManager independiente para este perfil
        self.content_manager = ContentManager(
            profile_config, self.logger, 
            scripts_twitter_path=scripts_twitter_path
        )
        
        # Watchers de este perfil (solo los activos)
        self.watchers: List[RundownWatcher] = []
        self._initialize_watchers()
        
        # Limpieza
        self.cleaning_interval = profile_config.get("content", {}).get(
            "cleaning_interval_seconds", 3600
        )
        self.last_clean_time = 0
        
        # Lock para impresión
        self._print_lock = threading.Lock()
    
    def _initialize_watchers(self):
        """Inicializa solo los monitores con active=true."""
        monitors = self.profile_config.get("monitors", [])
        ap_filter = self.profile_config.get("monitor", {}).get("ap_filter", "")
        
        active_count = 0
        inactive_count = 0
        
        for i, m_conf in enumerate(monitors):
            # Solo crear watchers para monitores activos
            if not m_conf.get("active", True):
                inactive_count += 1
                continue
            
            name = m_conf.get("name", f"MONITOR_{i+1}")
            merged_conf = m_conf.copy()
            if "ap_filter" not in merged_conf:
                merged_conf["ap_filter"] = ap_filter
            if "debug_parser" not in merged_conf:
                merged_conf["debug_parser"] = self.profile_config.get("monitor", {}).get("debug_parser", False)
            
            # Nombre del watcher incluye el perfil para distinguir en logs
            watcher_name = f"{self.profile_name}/{name}"
            self.watchers.append(RundownWatcher(watcher_name, merged_conf, self.inews_config))
            active_count += 1
        
        self.logger.info(
            f"Perfil {self.display_name}: {active_count} monitores activos, "
            f"{inactive_count} inactivos (max_workers={self.max_workers})"
        )
    
    def _process_watcher(self, watcher: RundownWatcher) -> List[Dict]:
        """Procesa un watcher con los tipos de rótulo de este perfil."""
        try:
            # Aplicar tipos de rótulo específicos de este perfil
            # (cada perfil puede tener distintos tipos_rotulo_validos)
            original_tipos = StoryParser.TIPOS_VALIDOS
            StoryParser.TIPOS_VALIDOS = self.tipos_validos
            
            results = watcher.process()
            
            StoryParser.TIPOS_VALIDOS = original_tipos
            
            if results:
                with self._print_lock:
                    self._print_results(results, watcher.name)
            return results
        except Exception as e:
            self.logger.error(f"Error procesando watcher {watcher.name}: {e}", exc_info=True)
            return []
    
    def run_once(self):
        """Ejecuta una pasada de todos los watchers pendientes de este perfil."""
        due_watchers = [w for w in self.watchers if w.is_due()]
        
        if not due_watchers:
            return []
        
        all_new_results = []
        any_processed = False
        
        effective_workers = min(self.max_workers, len(due_watchers))
        
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            future_to_watcher = {
                executor.submit(self._process_watcher, w): w
                for w in due_watchers
            }
            
            for future in as_completed(future_to_watcher):
                watcher = future_to_watcher[future]
                try:
                    results = future.result()
                    if results:
                        all_new_results.extend(results)
                    any_processed = True
                except Exception as e:
                    self.logger.error(f"Excepción en watcher {watcher.name}: {e}", exc_info=True)
        
        if any_processed:
            # Sincronización de contenido
            total_urls = set()
            all_watchers_ready = True
            
            for w in self.watchers:
                total_urls.update(w.active_urls)
                if not w.has_run:
                    all_watchers_ready = False
            
            should_clean = False
            current_time = time.time()
            
            if all_watchers_ready:
                if current_time - self.last_clean_time >= self.cleaning_interval:
                    should_clean = True
                    self.last_clean_time = current_time
            
            self.content_manager.sync_content(list(total_urls), clean=should_clean)
        
        return all_new_results
    
    def disconnect_all(self):
        """Desconecta todas las conexiones FTP."""
        for w in self.watchers:
            try:
                w.disconnect()
            except Exception:
                pass
    
    def _print_results(self, results, source_name):
        for result in results:
            urls = result['info'].get('urls', [])
            rotulos = result['info'].get('rotulos_filtrados', [])
            
            print("\n" + "="*60)
            print(f"[{self.display_name}] FUENTE: {source_name}")
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


class INewsMonitor:
    """
    Servicio de monitoreo de MÚLTIPLES programas de TV.
    Cada programa (perfil) se ejecuta de forma independiente con sus propios
    watchers, ContentManager y configuración.
    Soporta ejecución simultánea de múltiples perfiles.
    
    Estructura:
        config.json → credenciales + active_profiles + logging
        profiles/*.json → configuración por programa (monitores, rutas, etc.)
    """
    
    def __init__(self, config_path: str = "config.json", reload_check_interval_seconds: int = 2):
        self.config_path = os.path.abspath(config_path)
        self.reload_check_interval = max(1, int(reload_check_interval_seconds))
        self.running = False

        self._config_mtime: Optional[float] = None
        self._profile_mtimes: Dict[str, Optional[float]] = {}
        self._last_reload_check = 0.0

        self.config = self._load_config(fail_fast=True) or {}
        self._setup_logging()

        self.logger = logging.getLogger(self.__class__.__name__)

        self.scripts_twitter_path = self._resolve_scripts_twitter_path(self.config)
        self.profile_runners: List[ProfileRunner] = self._build_profile_runners(
            self.config, self.scripts_twitter_path
        )
        self._capture_runtime_fingerprints()

    def _load_config(self, fail_fast: bool = True) -> Optional[Dict]:
        last_error = None
        for _ in range(3):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                last_error = e
                time.sleep(0.1)

        if fail_fast:
            print(f"ERROR cargando config: {last_error}")
            sys.exit(1)

        logger = logging.getLogger(self.__class__.__name__)
        logger.warning(f"No se pudo recargar config (se mantiene la actual): {last_error}")
        return None

    def _resolve_scripts_twitter_path(self, config: Dict) -> str:
        scripts_twitter_path = config.get("scripts_twitter_path", "ScriptsTwitter")
        if not os.path.isabs(scripts_twitter_path):
            base_dir = os.path.dirname(self.config_path)
            scripts_twitter_path = os.path.join(base_dir, scripts_twitter_path)
        return scripts_twitter_path

    def _resolve_profiles_dir(self, config: Dict) -> str:
        profiles_dir = config.get("profiles_dir", "profiles")
        if not os.path.isabs(profiles_dir):
            base_dir = os.path.dirname(self.config_path)
            profiles_dir = os.path.join(base_dir, profiles_dir)
        return profiles_dir

    @staticmethod
    def _get_mtime(path: str) -> Optional[float]:
        try:
            return os.path.getmtime(path)
        except OSError:
            return None
    
    def _setup_logging(self):
        log_config = self.config.get("logging", {})
        log_level = getattr(logging, log_config.get("level", "INFO"))
        log_file = log_config.get("file", "inews_monitor.log")
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        root = logging.getLogger()
        root.setLevel(log_level)
        if not root.handlers:
            root.addHandler(file_handler)
            root.addHandler(console_handler)
    
    def _build_profile_runners(self, config: Dict, scripts_twitter_path: str) -> List[ProfileRunner]:
        """Construye los runners a partir de la configuración actual en disco."""
        active_names = config.get("active_profiles", [])
        profiles_dir = self._resolve_profiles_dir(config)
        runners: List[ProfileRunner] = []

        if not os.path.isdir(profiles_dir):
            self.logger.error(f"Directorio de perfiles no encontrado: {profiles_dir}")
            return runners

        inews_config = config.get("inews")
        if not isinstance(inews_config, dict):
            self.logger.error("Config inválida: falta sección 'inews'")
            return runners

        # Compatibilidad: si no hay active_profiles pero hay monitors en config.json (legacy)
        if not active_names and "monitors" in config:
            self.logger.info("Modo legacy: usando monitors de config.json directamente")
            runner = ProfileRunner(
                "LEGACY", config, inews_config,
                scripts_twitter_path, self.logger
            )
            runners.append(runner)
            return runners

        for profile_name in active_names:
            profile_path = os.path.join(profiles_dir, f"{profile_name}.json")

            if not os.path.isfile(profile_path):
                self.logger.error(f"Perfil no encontrado: {profile_path}")
                continue

            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile_config = json.load(f)

                runner = ProfileRunner(
                    profile_name, profile_config, inews_config,
                    scripts_twitter_path, self.logger
                )
                runners.append(runner)
                self.logger.info(f"Perfil cargado: {profile_name} ({runner.display_name})")

            except Exception as e:
                self.logger.error(f"Error cargando perfil {profile_name}: {e}")

        total_watchers = sum(len(r.watchers) for r in runners)
        self.logger.info(
            f"Cargados {len(runners)} perfiles con "
            f"{total_watchers} watchers activos en total"
        )
        return runners

    def _capture_runtime_fingerprints(self):
        """Guarda huellas de archivos para detectar cambios en caliente."""
        self._config_mtime = self._get_mtime(self.config_path)
        profiles_dir = self._resolve_profiles_dir(self.config)
        active_names = self.config.get("active_profiles", [])

        profile_mtimes: Dict[str, Optional[float]] = {}
        for profile_name in active_names:
            profile_path = os.path.join(profiles_dir, f"{profile_name}.json")
            profile_mtimes[profile_name] = self._get_mtime(profile_path)

        self._profile_mtimes = profile_mtimes
        self._last_reload_check = time.time()

    def _detect_runtime_changes(self) -> Optional[str]:
        now = time.time()
        if now - self._last_reload_check < self.reload_check_interval:
            return None
        self._last_reload_check = now

        current_config_mtime = self._get_mtime(self.config_path)
        if current_config_mtime != self._config_mtime:
            return "config.json actualizado"

        profiles_dir = self._resolve_profiles_dir(self.config)
        active_names = self.config.get("active_profiles", [])
        for profile_name in active_names:
            profile_path = os.path.join(profiles_dir, f"{profile_name}.json")
            current_profile_mtime = self._get_mtime(profile_path)
            if self._profile_mtimes.get(profile_name) != current_profile_mtime:
                return f"perfil {profile_name}.json actualizado"

        return None

    def _reload_runtime_if_needed(self):
        reason = self._detect_runtime_changes()
        if not reason:
            return

        new_config = self._load_config(fail_fast=False)
        if not new_config:
            return

        new_scripts_path = self._resolve_scripts_twitter_path(new_config)
        new_runners = self._build_profile_runners(new_config, new_scripts_path)
        old_runners = self.profile_runners

        self.config = new_config
        self.scripts_twitter_path = new_scripts_path
        self.profile_runners = new_runners
        self._capture_runtime_fingerprints()

        for runner in old_runners:
            try:
                runner.disconnect_all()
            except Exception:
                pass

        profile_names = [r.display_name for r in self.profile_runners]
        self.logger.info(
            f"Recarga en caliente aplicada ({reason}). "
            f"Perfiles activos: {profile_names}"
        )

    def run_once(self):
        """Ejecuta una pasada de todos los perfiles."""
        self._reload_runtime_if_needed()

        all_results = []
        for runner in self.profile_runners:
            try:
                results = runner.run_once()
                if results:
                    all_results.extend(results)
            except Exception as e:
                self.logger.error(f"Error en perfil {runner.profile_name}: {e}", exc_info=True)
        return all_results
    
    def _disconnect_all(self):
        """Desconecta todas las conexiones de todos los perfiles."""
        for runner in self.profile_runners:
            runner.disconnect_all()

    def stop(self):
        """Solicita parada limpia del monitor."""
        self.running = False
    
    def run(self):
        self.running = True
        profile_names = [r.display_name for r in self.profile_runners]
        total_watchers = sum(len(r.watchers) for r in self.profile_runners)
        self.logger.info(
            f"Iniciando monitoreo multi-perfil: {profile_names} "
            f"({total_watchers} watchers activos)"
        )
        
        try:
            while self.running:
                self.run_once()
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Deteniendo...")
        finally:
            self._disconnect_all()


def main():
    parser = argparse.ArgumentParser(description='Monitor iNews Multi-Perfil')
    parser.add_argument('--config', '-c', default='config.json', help='Config file')
    parser.add_argument('--once', '-o', action='store_true', help='Ejecutar una vez y salir')
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    monitor = INewsMonitor(config_path=args.config)
    
    if args.once:
        monitor.run_once()
    else:
        monitor.run()


if __name__ == "__main__":
    main()
