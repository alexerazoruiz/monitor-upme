#!/usr/bin/env python3
"""
================================================================================
MONITOR DE CONVOCATORIAS UPME - VERSIÓN GITHUB ACTIONS
================================================================================
Este script está adaptado para correr en GitHub Actions.
Las credenciales se leen de variables de entorno (secrets).
================================================================================
"""

import requests
from bs4 import BeautifulSoup
import hashlib
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging
import sys

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

URL_MONITOREAR = "https://www.upme.gov.co/home/convocatorias/convocatorias-de-transmision/?e-filter-b21e3d0-estado_convocatoria=abierta-oficialmente&e-filter-b21e3d0-ano_upme=2025"
ARCHIVO_ESTADO = "upme_state.json"

# Leer credenciales de variables de entorno (GitHub Secrets)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_ACTIVADO = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

EMAIL_REMITENTE = os.environ.get("EMAIL_SENDER", "")
EMAIL_CONTRASENA = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_DESTINATARIO = os.environ.get("EMAIL_RECIPIENT", "")
EMAIL_ACTIVADO = bool(EMAIL_REMITENTE and EMAIL_CONTRASENA and EMAIL_DESTINATARIO)


def obtener_pagina(url: str) -> str | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        logger.info(f"Página obtenida ({len(response.text)} caracteres)")
        return response.text
    except requests.RequestException as e:
        logger.error(f"Error al obtener página: {e}")
        return None


def extraer_convocatorias(html: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    convocatorias = []
    
    selectores = ['.e-loop-item', 'article', '.elementor-post', '.jet-listing-grid__item']
    items = []
    for selector in selectores:
        items = soup.select(selector)
        if items and len(items) > 1:
            break
    
    if not items or len(items) <= 1:
        main_content = soup.find('main') or soup.find('body')
        if main_content:
            texto = main_content.get_text(separator=' ', strip=True)
            convocatorias.append({'tipo': 'contenido_general', 'texto': texto[:5000]})
        return convocatorias
    
    for item in items:
        conv = {}
        titulo_elem = item.find(['h1', 'h2', 'h3', 'h4', 'a'])
        if titulo_elem:
            conv['titulo'] = titulo_elem.get_text(strip=True)[:200]
            if titulo_elem.name == 'a' and titulo_elem.get('href'):
                conv['enlace'] = titulo_elem.get('href')
        conv['texto'] = item.get_text(separator=' ', strip=True)[:500]
        if conv.get('titulo') or conv.get('texto'):
            convocatorias.append(conv)
    
    return convocatorias


def calcular_hash(datos: list) -> str:
    return hashlib.md5(json.dumps(datos, sort_keys=True).encode()).hexdigest()


def cargar_estado_anterior() -> dict | None:
    if not os.path.exists(ARCHIVO_ESTADO):
        return None
    try:
        with open(ARCHIVO_ESTADO, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None


def guardar_estado(convocatorias: list, hash_contenido: str):
    estado = {
        "timestamp": datetime.now().isoformat(),
        "hash": hash_contenido,
        "convocatorias": convocatorias,
    }
    with open(ARCHIVO_ESTADO, 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def detectar_cambios(actual: list, anterior: list) -> dict:
    cambios = {"nuevas": [], "eliminadas": [], "modificadas": []}
    
    def clave(c): return c.get('titulo', c.get('texto', '')[:50])
    
    mapa_actual = {clave(c): c for c in actual if clave(c) and c.get('tipo') != 'contenido_general'}
    mapa_anterior = {clave(c): c for c in anterior if clave(c) and c.get('tipo') != 'contenido_general'}
    
    for k, v in mapa_actual.items():
        if k not in mapa_anterior:
            cambios["nuevas"].append(v)
    
    for k, v in mapa_anterior.items():
        if k not in mapa_actual:
            cambios["eliminadas"].append(v)
    
    return cambios


def enviar_telegram(mensaje: str) -> bool:
    if not TELEGRAM_ACTIVADO:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML",
        }, timeout=10)
        response.raise_for_status()
        logger.info("✅ Telegram enviado")
        return True
    except Exception as e:
        logger.error(f"❌ Error Telegram: {e}")
        return False


def enviar_email(asunto: str, cuerpo: str) -> bool:
    if not EMAIL_ACTIVADO:
        return False
    try:
        msg = MIMEMultipart()
        msg['Subject'] = asunto
        msg['From'] = EMAIL_REMITENTE
        msg['To'] = EMAIL_DESTINATARIO
        msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
        
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_REMITENTE, EMAIL_CONTRASENA)
            server.sendmail(EMAIL_REMITENTE, EMAIL_DESTINATARIO, msg.as_string())
        logger.info("✅ Email enviado")
        return True
    except Exception as e:
        logger.error(f"❌ Error Email: {e}")
        return False


def formatear_telegram(cambios: dict, url: str) -> str:
    lineas = ["🔔 <b>CAMBIOS EN CONVOCATORIAS UPME</b>", f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    
    if cambios["nuevas"]:
        lineas.append(f"\n🆕 <b>Nuevas ({len(cambios['nuevas'])}):</b>")
        for c in cambios["nuevas"]:
            lineas.append(f"• {c.get('titulo', 'Sin título')[:100]}")
    
    if cambios["eliminadas"]:
        lineas.append(f"\n🗑️ <b>Cerradas ({len(cambios['eliminadas'])}):</b>")
        for c in cambios["eliminadas"]:
            lineas.append(f"• {c.get('titulo', 'Sin título')[:100]}")
    
    lineas.append(f"\n🔗 <a href='{url}'>Ver en UPME</a>")
    return "\n".join(lineas)


def main():
    logger.info("=" * 50)
    logger.info("🚀 MONITOR UPME - GitHub Actions")
    logger.info("=" * 50)
    logger.info(f"📱 Telegram: {'ACTIVADO' if TELEGRAM_ACTIVADO else 'DESACTIVADO'}")
    logger.info(f"📧 Email: {'ACTIVADO' if EMAIL_ACTIVADO else 'DESACTIVADO'}")
    
    html = obtener_pagina(URL_MONITOREAR)
    if not html:
        return 1
    
    convocatorias = extraer_convocatorias(html)
    logger.info(f"📋 {len(convocatorias)} elementos encontrados")
    
    hash_actual = calcular_hash(convocatorias)
    estado_anterior = cargar_estado_anterior()
    
    if estado_anterior is None:
        logger.info("📝 Primera ejecución - guardando estado")
        guardar_estado(convocatorias, hash_actual)
        return 0
    
    if hash_actual == estado_anterior.get("hash"):
        logger.info("✅ Sin cambios")
        return 0
    
    logger.info("⚠️ ¡Cambios detectados!")
    cambios = detectar_cambios(convocatorias, estado_anterior.get("convocatorias", []))
    
    total = len(cambios["nuevas"]) + len(cambios["eliminadas"])
    if total == 0:
        logger.info("Cambios menores, actualizando estado")
        guardar_estado(convocatorias, hash_actual)
        return 0
    
    mensaje = formatear_telegram(cambios, URL_MONITOREAR)
    enviar_telegram(mensaje)
    enviar_email("🔔 Cambios UPME", mensaje.replace("<b>", "").replace("</b>", "").replace("<a href='", "").replace("'>Ver en UPME</a>", ""))
    
    guardar_estado(convocatorias, hash_actual)
    logger.info("✅ Completado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
