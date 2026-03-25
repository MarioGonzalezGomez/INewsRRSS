#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
iNews Monitor - Panel de Control Web
=====================================
Servidor web ligero para gestionar perfiles y monitores.
Sin dependencias externas (usa http.server de Python).

Uso:
    python control_panel.py                  # Puerto 8080
    python control_panel.py --port 9090      # Puerto personalizado
"""

import json
import os
import sys
import glob
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


# ─────────────────────────────────────────────────────────
# Utilidades de configuración
# ─────────────────────────────────────────────────────────

def get_base_dir():
    return os.path.dirname(os.path.abspath(__file__))

def load_config():
    config_path = os.path.join(get_base_dir(), "panel_state.json")
    if not os.path.exists(config_path):
        return {"profiles_dir": "profiles", "active_profiles": []}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"profiles_dir": "profiles", "active_profiles": []}

def save_config(config):
    config_path = os.path.join(get_base_dir(), "panel_state.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def get_profiles_dir():
    config = load_config()
    profiles_dir = config.get("profiles_dir", "profiles")
    if not os.path.isabs(profiles_dir):
        profiles_dir = os.path.join(get_base_dir(), profiles_dir)
    return profiles_dir

def load_profile(profile_name):
    path = os.path.join(get_profiles_dir(), f"{profile_name}.json")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_profile(profile_name, data):
    path = os.path.join(get_profiles_dir(), f"{profile_name}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def list_all_profiles():
    """Lista todos los perfiles disponibles con su estado."""
    config = load_config()
    active_profiles = config.get("active_profiles", [])
    profiles_dir = get_profiles_dir()
    
    result = []
    if not os.path.isdir(profiles_dir):
        return result
    
    for filepath in sorted(glob.glob(os.path.join(profiles_dir, "*.json"))):
        filename = os.path.splitext(os.path.basename(filepath))[0]
        try:
            profile_data = load_profile(filename)
            monitors = profile_data.get("monitors", [])
            active_monitors = sum(1 for m in monitors if m.get("active", True))
            total_monitors = len(monitors)
            
            result.append({
                "id": filename,
                "name": profile_data.get("name", filename),
                "active": filename in active_profiles,
                "monitors": monitors,
                "active_monitors": active_monitors,
                "total_monitors": total_monitors,
                "download_path": profile_data.get("content", {}).get("download_base_path", ""),
                "max_workers": profile_data.get("monitor", {}).get("max_workers", 5),
                "tipos_rotulo": profile_data.get("monitor", {}).get("tipos_rotulo_validos", [])
            })
        except Exception as e:
            result.append({
                "id": filename,
                "name": filename,
                "active": filename in active_profiles,
                "error": str(e)
            })
    
    return result


# ─────────────────────────────────────────────────────────
# HTML/CSS/JS del Panel de Control
# ─────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>iNews Monitor - Panel de Control</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0f1117;
            --bg-secondary: #1a1d27;
            --bg-card: #21242f;
            --bg-card-hover: #282c3a;
            --accent: #6366f1;
            --accent-hover: #818cf8;
            --accent-glow: rgba(99, 102, 241, 0.15);
            --green: #22c55e;
            --green-bg: rgba(34, 197, 94, 0.12);
            --red: #ef4444;
            --red-bg: rgba(239, 68, 68, 0.12);
            --yellow: #eab308;
            --yellow-bg: rgba(234, 179, 8, 0.12);
            --text-primary: #e2e8f0;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --border: #2d3348;
            --border-light: #374151;
            --radius: 12px;
            --radius-sm: 8px;
            --shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Inter', -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
        }

        .header {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            padding: 20px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 100;
            backdrop-filter: blur(12px);
        }

        .header h1 {
            font-size: 1.3rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .header h1 .dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--green);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .header-actions {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .btn {
            padding: 8px 16px;
            border-radius: var(--radius-sm);
            border: 1px solid var(--border);
            background: var(--bg-card);
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .btn:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-light);
        }

        .btn-primary {
            background: var(--accent);
            border-color: var(--accent);
            color: #fff;
        }

        .btn-primary:hover {
            background: var(--accent-hover);
            border-color: var(--accent-hover);
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 32px;
        }

        .status-bar {
            display: flex;
            gap: 24px;
            margin-bottom: 28px;
            flex-wrap: wrap;
        }

        .stat-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px 24px;
            flex: 1;
            min-width: 160px;
        }

        .stat-card .label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            margin-bottom: 6px;
        }

        .stat-card .value {
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--text-primary);
        }

        .stat-card .value.green { color: var(--green); }
        .stat-card .value.accent { color: var(--accent); }

        .profile-grid {
            display: grid;
            gap: 20px;
        }

        .profile-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
            transition: all 0.3s;
        }

        .profile-card:hover {
            border-color: var(--border-light);
            box-shadow: var(--shadow);
        }

        .profile-card.active {
            border-color: var(--accent);
            box-shadow: 0 0 0 1px var(--accent), 0 4px 24px var(--accent-glow);
        }

        .profile-header {
            padding: 20px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border);
        }

        .profile-info {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .profile-icon {
            width: 42px;
            height: 42px;
            border-radius: var(--radius-sm);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.9rem;
            font-weight: 700;
            background: var(--accent-glow);
            color: var(--accent);
            text-align: center;
        }

        .profile-card.active .profile-icon {
            background: var(--accent);
            color: #fff;
        }

        .profile-name {
            font-size: 1.1rem;
            font-weight: 600;
        }

        .profile-id {
            font-size: 0.78rem;
            color: var(--text-muted);
            font-family: 'Courier New', monospace;
        }

        .profile-meta {
            display: flex;
            gap: 16px;
            align-items: center;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .badge-active {
            background: var(--green-bg);
            color: var(--green);
        }

        .badge-inactive {
            background: var(--red-bg);
            color: var(--red);
        }

        .badge-monitors {
            background: var(--bg-secondary);
            color: var(--text-secondary);
        }

        /* Toggle switch */
        .toggle {
            position: relative;
            width: 44px;
            height: 24px;
            cursor: pointer;
        }

        .toggle input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            inset: 0;
            background: var(--border);
            border-radius: 24px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .toggle-slider::before {
            content: '';
            position: absolute;
            width: 18px;
            height: 18px;
            left: 3px;
            bottom: 3px;
            background: var(--text-secondary);
            border-radius: 50%;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .toggle input:checked + .toggle-slider {
            background: var(--accent);
        }

        .toggle input:checked + .toggle-slider::before {
            transform: translateX(20px);
            background: #fff;
        }

        .monitors-section {
            padding: 16px 24px 20px;
        }

        .monitors-title {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .monitors-actions {
            display: flex;
            gap: 8px;
        }

        .monitors-actions .btn {
            padding: 4px 10px;
            font-size: 0.72rem;
        }

        .monitors-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 8px;
        }

        .monitor-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 14px;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            transition: all 0.2s;
        }

        .monitor-item:hover {
            border-color: var(--border-light);
        }

        .monitor-item.active-monitor {
            border-left: 3px solid var(--green);
        }

        .monitor-item.inactive-monitor {
            border-left: 3px solid var(--text-muted);
            opacity: 0.6;
        }

        .monitor-name {
            font-size: 0.82rem;
            font-weight: 500;
        }

        .monitor-interval {
            font-size: 0.7rem;
            color: var(--text-muted);
        }

        .profile-details {
            padding: 0 24px 16px;
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
        }

        .detail-item {
            font-size: 0.78rem;
            color: var(--text-secondary);
        }

        .detail-item strong {
            color: var(--text-muted);
            font-weight: 500;
        }

        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 12px 20px;
            font-size: 0.85rem;
            box-shadow: var(--shadow);
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 1000;
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        .toast.success { border-left: 3px solid var(--green); }
        .toast.error { border-left: 3px solid var(--red); }

        .interval-input {
            width: 52px;
            padding: 2px 6px;
            background: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 4px;
            color: var(--text-secondary);
            font-family: 'Courier New', monospace;
            font-size: 0.72rem;
            text-align: center;
            transition: all 0.2s;
            -moz-appearance: textfield;
        }

        .interval-input::-webkit-outer-spin-button,
        .interval-input::-webkit-inner-spin-button {
            -webkit-appearance: none;
            margin: 0;
        }

        .interval-input:focus {
            outline: none;
            border-color: var(--accent);
            color: var(--text-primary);
            box-shadow: 0 0 0 2px var(--accent-glow);
        }

        .interval-input:hover { border-color: var(--border-light); }

        .interval-suffix {
            font-size: 0.68rem;
            color: var(--text-muted);
            margin-left: 2px;
        }

        .tags-editor {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
        }

        .tag {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 8px 3px 10px;
            background: var(--accent-glow);
            border: 1px solid rgba(99, 102, 241, 0.25);
            border-radius: 16px;
            font-size: 0.72rem;
            font-weight: 500;
            color: var(--accent-hover);
            transition: all 0.2s;
        }

        .tag:hover {
            background: rgba(99, 102, 241, 0.22);
            border-color: var(--accent);
        }

        .tag-remove {
            cursor: pointer;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.6rem;
            color: var(--text-muted);
            transition: all 0.2s;
            background: transparent;
            border: none;
            line-height: 1;
            padding: 0;
        }

        .tag-remove:hover {
            background: var(--red-bg);
            color: var(--red);
        }

        .tag-add-form {
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .tag-input {
            width: 110px;
            padding: 3px 8px;
            background: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 16px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.72rem;
            transition: all 0.2s;
        }

        .tag-input:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 2px var(--accent-glow);
        }

        .tag-input::placeholder { color: var(--text-muted); }

        .tag-add-btn {
            padding: 3px 8px;
            background: var(--accent-glow);
            border: 1px solid rgba(99, 102, 241, 0.25);
            border-radius: 16px;
            color: var(--accent);
            cursor: pointer;
            font-size: 0.72rem;
            font-weight: 600;
            transition: all 0.2s;
        }

        .tag-add-btn:hover {
            background: var(--accent);
            color: #fff;
        }

        .detail-block {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .detail-label {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--text-muted);
            font-weight: 500;
        }

        .worker-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .worker-input {
            width: 52px;
            padding: 4px 8px;
            background: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-primary);
            font-family: 'Courier New', monospace;
            font-size: 0.85rem;
            font-weight: 600;
            text-align: center;
            transition: all 0.2s;
            -moz-appearance: textfield;
        }

        .worker-input::-webkit-outer-spin-button,
        .worker-input::-webkit-inner-spin-button {
            -webkit-appearance: none;
            margin: 0;
        }

        .worker-input:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 2px var(--accent-glow);
        }

        .worker-hint {
            font-size: 0.7rem;
            padding: 3px 8px;
            background: var(--yellow-bg);
            color: var(--yellow);
            border-radius: 10px;
            font-weight: 500;
        }

        @media (max-width: 768px) {
            .container { padding: 16px; }
            .header { padding: 16px; }
            .monitors-grid { grid-template-columns: 1fr; }
            .profile-meta { flex-wrap: wrap; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>
            <span class="dot"></span>
            iNews Monitor — Panel de Control
        </h1>
        <div class="header-actions">
            <button class="btn" onclick="loadProfiles()">⟳ Refrescar</button>
        </div>
    </div>

    <div class="container">
        <div class="status-bar" id="statusBar"></div>
        <div class="profile-grid" id="profileGrid"></div>

        <div class="logs-container" style="margin-top: 40px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: var(--radius);">
            <div style="padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;">
                <h3 style="font-size: 1rem; font-weight: 600; display: flex; align-items: center; gap: 8px;">
                    ▶ Terminal de Errores y Logs en Vivo
                </h3>
                <button class="btn" onclick="fetchLogs()">⟳ Refrescar Logs</button>
            </div>
            <div id="logsView" style="padding: 16px; font-family: 'Courier New', monospace; font-size: 0.8rem; height: 300px; overflow-y: auto; background: #0a0a0f; color: #a3b8cc; line-height: 1.4;">
                Cargando logs...
            </div>
        </div>
    </div>

    <div class="toast" id="toast"></div>

    <script>
        let profiles = [];

        async function api(method, path, body = null) {
            const opts = { method, headers: { 'Content-Type': 'application/json' } };
            if (body) opts.body = JSON.stringify(body);
            const res = await fetch('/api' + path, opts);
            return res.json();
        }

        function showToast(msg, type = 'success') {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.className = 'toast show ' + type;
            setTimeout(() => toast.className = 'toast', 3000);
        }

        async function loadProfiles() {
            try {
                const data = await api('GET', '/profiles');
                profiles = data.profiles || [];
                renderAll();
            } catch (e) {
                showToast('Error cargando perfiles: ' + e.message, 'error');
            }
        }

        function renderAll() {
            renderStats();
            renderProfiles();
        }

        function renderStats() {
            const activeProfiles = profiles.filter(p => p.active).length;
            const totalMonitors = profiles.reduce((sum, p) => sum + (p.total_monitors || 0), 0);
            const activeMonitors = profiles.reduce((sum, p) => p.active ? sum + (p.active_monitors || 0) : sum, 0);

            document.getElementById('statusBar').innerHTML = `
                <div class="stat-card">
                    <div class="label">Perfiles activos</div>
                    <div class="value green">${activeProfiles}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Perfiles totales</div>
                    <div class="value">${profiles.length}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Monitores activos</div>
                    <div class="value accent">${activeMonitors}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Monitores totales</div>
                    <div class="value">${totalMonitors}</div>
                </div>
            `;
        }

        function renderProfiles() {
            const grid = document.getElementById('profileGrid');
            grid.innerHTML = profiles.map(p => {
                const initialsMap = {'24H':'24H', 'TD':'TD', 'Especiales':'E', 'Terri':'T'};
                const initial = initialsMap[p.id] || (p.name || p.id)[0].toUpperCase();
                const monitors = (p.monitors || []).map((m, idx) => {
                    const isActive = m.active !== false;
                    return `
                        <div class="monitor-item ${isActive ? 'active-monitor' : 'inactive-monitor'}">
                            <div>
                                <div class="monitor-name">${m.name || 'Monitor ' + (idx+1)}</div>
                                <div class="monitor-interval">
                                    <input type="number" class="interval-input" value="${m.interval_seconds || 30}" min="5" max="3600"
                                        onchange="updateInterval('${p.id}', ${idx}, this.value)"
                                        title="Intervalo de refresco en segundos"><span class="interval-suffix">seg</span>
                                </div>
                            </div>
                            <label class="toggle" title="${isActive ? 'Desactivar' : 'Activar'} monitor">
                                <input type="checkbox" ${isActive ? 'checked' : ''}
                                    onchange="toggleMonitor('${p.id}', ${idx}, this.checked)">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                    `;
                }).join('');

                const tipos = (p.tipos_rotulo || []).join(', ');

                return `
                    <div class="profile-card ${p.active ? 'active' : ''}">
                        <div class="profile-header">
                            <div class="profile-info">
                                <div class="profile-icon">${initial}</div>
                                <div>
                                    <div class="profile-name">${p.name || p.id}</div>
                                    <div class="profile-id">${p.id}.json</div>
                                </div>
                            </div>
                            <div class="profile-meta">
                                <span class="badge ${p.active ? 'badge-active' : 'badge-inactive'}">
                                    ${p.active ? '● Activo' : '○ Inactivo'}
                                </span>
                                <span class="badge badge-monitors">
                                    ${p.active_monitors || 0}/${p.total_monitors || 0} monitores
                                </span>
                                <label class="toggle" title="${p.active ? 'Desactivar' : 'Activar'} perfil">
                                    <input type="checkbox" ${p.active ? 'checked' : ''}
                                        onchange="toggleProfile('${p.id}', this.checked)">
                                    <span class="toggle-slider"></span>
                                </label>
                            </div>
                        </div>
                        <div class="profile-details">
                            <div class="detail-block">
                                <div class="detail-label">Ruta descarga</div>
                                <div class="detail-item">${p.download_path || '-'}</div>
                            </div>
                            <div class="detail-block">
                                <div class="detail-label">Workers</div>
                                <div class="worker-group">
                                    <input type="number" class="worker-input" value="${p.max_workers || 2}" min="1" max="20"
                                        onchange="updateWorkers('${p.id}', this.value)"
                                        title="Número de workers concurrentes">
                                    <span class="worker-hint">rec: ${getRecommendedWorkers(p)}</span>
                                </div>
                            </div>
                            <div class="detail-block" style="flex-basis: 100%;">
                                <div class="detail-label">Tipos de rótulo válidos</div>
                                <div class="tags-editor">
                                    ${(p.tipos_rotulo || []).map((t, i) => `
                                        <span class="tag">${t}<button class="tag-remove" onclick="removeTipoRotulo('${p.id}', ${i})" title="Eliminar">✕</button></span>
                                    `).join('')}
                                    <span class="tag-add-form">
                                        <input type="text" class="tag-input" id="tagInput_${p.id}" placeholder="Nuevo tipo..."
                                            onkeydown="if(event.key==='Enter'){addTipoRotulo('${p.id}')}">
                                        <button class="tag-add-btn" onclick="addTipoRotulo('${p.id}')" title="Añadir tipo">+ Añadir</button>
                                    </span>
                                </div>
                            </div>
                        </div>
                        <div class="monitors-section">
                            <div class="monitors-title">
                                <span>Monitores</span>
                                <div class="monitors-actions">
                                    <button class="btn" onclick="setAllMonitors('${p.id}', true)">Activar todos</button>
                                    <button class="btn" onclick="setAllMonitors('${p.id}', false)">Desactivar todos</button>
                                </div>
                            </div>
                            <div class="monitors-grid">${monitors}</div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function toggleProfile(profileId, active) {
            try {
                await api('POST', `/profiles/${profileId}/${active ? 'activate' : 'deactivate'}`);
                showToast(`Perfil ${profileId} ${active ? 'activado' : 'desactivado'}`);
                await loadProfiles();
            } catch (e) {
                showToast('Error: ' + e.message, 'error');
                await loadProfiles();
            }
        }

        async function toggleMonitor(profileId, monitorIdx, active) {
            try {
                await api('POST', `/profiles/${profileId}/monitors/${monitorIdx}/toggle`, { active });
                showToast(`Monitor ${active ? 'activado' : 'desactivado'}`);
                await loadProfiles();
            } catch (e) {
                showToast('Error: ' + e.message, 'error');
                await loadProfiles();
            }
        }

        async function setAllMonitors(profileId, active) {
            try {
                await api('POST', `/profiles/${profileId}/monitors/all`, { active });
                showToast(`Todos los monitores ${active ? 'activados' : 'desactivados'}`);
                await loadProfiles();
            } catch (e) {
                showToast('Error: ' + e.message, 'error');
                await loadProfiles();
            }
        }

        function getRecommendedWorkers(profile) {
            const active = (profile.monitors || []).filter(m => m.active !== false).length;
            return Math.max(2, Math.min(10, Math.ceil(active / 2)));
        }

        async function updateInterval(profileId, monitorIdx, value) {
            const seconds = parseInt(value);
            if (isNaN(seconds) || seconds < 5) {
                showToast('El intervalo mínimo es 5 segundos', 'error');
                await loadProfiles();
                return;
            }
            try {
                await api('POST', `/profiles/${profileId}/monitors/${monitorIdx}/interval`, { interval_seconds: seconds });
                showToast(`Intervalo actualizado a ${seconds}s`);
                await loadProfiles();
            } catch (e) {
                showToast('Error: ' + e.message, 'error');
                await loadProfiles();
            }
        }

        async function addTipoRotulo(profileId) {
            const input = document.getElementById('tagInput_' + profileId);
            const tipo = (input.value || '').trim();
            if (!tipo) { showToast('Escribe un tipo de rótulo', 'error'); return; }
            try {
                await api('POST', `/profiles/${profileId}/tipos_rotulo`, { action: 'add', tipo });
                showToast(`Tipo "${tipo}" añadido`);
                await loadProfiles();
            } catch (e) {
                showToast('Error: ' + e.message, 'error');
                await loadProfiles();
            }
        }

        async function removeTipoRotulo(profileId, index) {
            try {
                await api('POST', `/profiles/${profileId}/tipos_rotulo`, { action: 'remove', index });
                showToast('Tipo eliminado');
                await loadProfiles();
            } catch (e) {
                showToast('Error: ' + e.message, 'error');
                await loadProfiles();
            }
        }

        async function updateWorkers(profileId, value) {
            const workers = parseInt(value);
            if (isNaN(workers) || workers < 1) {
                showToast('Mínimo 1 worker', 'error');
                await loadProfiles();
                return;
            }
            try {
                await api('POST', `/profiles/${profileId}/workers`, { max_workers: workers });
                showToast(`Workers actualizado a ${workers}`);
                await loadProfiles();
            } catch (e) {
                showToast('Error: ' + e.message, 'error');
                await loadProfiles();
            }
        }

        async function fetchLogs() {
            try {
                const data = await api('GET', '/logs');
                const logsView = document.getElementById('logsView');
                if (data.logs && logsView) {
                    logsView.innerHTML = data.logs.map(line => {
                        let color = '#a3b8cc';
                        if (line.includes('ERROR') || line.includes('Exception') || line.includes('Traceback')) {
                            color = '#ef4444'; // Rojo claro
                        } else if (line.includes('WARNING') || line.includes('WARN')) {
                            color = '#eab308'; // Amarillo
                        } else if (line.includes('✅')) {
                            color = '#22c55e'; // Verde
                        }
                        
                        // Escapar HTML básico
                        const escapedLine = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                        return `<div style="color: ${color}; white-space: pre-wrap; margin-bottom: 2px;">${escapedLine}</div>`;
                    }).join('');
                    
                    // Auto-scroll al fondo
                    logsView.scrollTop = logsView.scrollHeight;
                }
            } catch (e) {
                console.error("Error fetching logs:", e);
            }
        }

        // Cargar al inicio
        loadProfiles();
        fetchLogs();

        // Auto-refrescar
        setInterval(loadProfiles, 30000);
        setInterval(fetchLogs, 5000);
    </script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────
# HTTP Handler
# ─────────────────────────────────────────────────────────

class ControlPanelHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Silenciar logs de peticiones HTTP por limpieza
        pass
    
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
    
    def _send_html(self, html):
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
    
    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        
        if path == '' or path == '/':
            self._send_html(HTML_PAGE)
        
        elif path == '/api/profiles':
            try:
                profiles = list_all_profiles()
                self._send_json({"profiles": profiles})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
                
        elif path == '/api/logs':
            try:
                log_filepath = os.path.join(get_base_dir(), "inews_monitor.log")
                if not os.path.exists(log_filepath):
                    self._send_json({"logs": ["Aún no hay archivos de log o inews_monitor.log no encontrado."]})
                    return 
                
                # Leemos las últimas 150 líneas
                with open(log_filepath, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
                    last_lines = [line.strip() for line in lines[-150:]]
                
                self._send_json({"logs": last_lines})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        
        else:
            self.send_error(404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        parts = path.split('/')
        
        try:
            # POST /api/profiles/<id>/activate
            # POST /api/profiles/<id>/deactivate
            if len(parts) == 4 and parts[1] == 'api' and parts[2] == 'profiles':
                profile_id = parts[3]
                # Estos se manejan abajo
                self.send_error(404)
                return
            
            if len(parts) == 5 and parts[1] == 'api' and parts[2] == 'profiles':
                profile_id = parts[3]
                action = parts[4]
                
                if action == 'activate':
                    config = load_config()
                    active = config.get("active_profiles", [])
                    if profile_id not in active:
                        active.append(profile_id)
                        config["active_profiles"] = active
                        save_config(config)
                    self._send_json({"ok": True, "active_profiles": active})
                    return
                
                elif action == 'deactivate':
                    config = load_config()
                    active = config.get("active_profiles", [])
                    if profile_id in active:
                        active.remove(profile_id)
                        config["active_profiles"] = active
                        save_config(config)
                    self._send_json({"ok": True, "active_profiles": active})
                    return
                
                elif action == 'tipos_rotulo':
                    body = self._read_body()
                    profile = load_profile(profile_id)
                    if "monitor" not in profile:
                        profile["monitor"] = {}
                    tipos = profile["monitor"].get("tipos_rotulo_validos", [])
                    
                    act = body.get("action")
                    if act == "add":
                        tipo = body.get("tipo", "").strip()
                        if tipo and tipo not in tipos:
                            tipos.append(tipo)
                    elif act == "remove":
                        idx = body.get("index", -1)
                        if 0 <= idx < len(tipos):
                            tipos.pop(idx)
                    
                    profile["monitor"]["tipos_rotulo_validos"] = tipos
                    save_profile(profile_id, profile)
                    self._send_json({"ok": True, "tipos_rotulo_validos": tipos})
                    return
                
                elif action == 'workers':
                    body = self._read_body()
                    workers = int(body.get("max_workers", 5))
                    profile = load_profile(profile_id)
                    if "monitor" not in profile:
                        profile["monitor"] = {}
                    profile["monitor"]["max_workers"] = workers
                    save_profile(profile_id, profile)
                    self._send_json({"ok": True, "max_workers": workers})
                    return
            
            # POST /api/profiles/<id>/monitors/<idx>/toggle
            if (len(parts) == 7 and parts[1] == 'api' and parts[2] == 'profiles' 
                    and parts[4] == 'monitors' and parts[6] == 'toggle'):
                profile_id = parts[3]
                monitor_idx = int(parts[5])
                body = self._read_body()
                active = body.get("active", True)
                
                profile = load_profile(profile_id)
                monitors = profile.get("monitors", [])
                if 0 <= monitor_idx < len(monitors):
                    monitors[monitor_idx]["active"] = active
                    save_profile(profile_id, profile)
                    self._send_json({"ok": True})
                else:
                    self._send_json({"error": "Monitor index out of range"}, 400)
                return
            
            # POST /api/profiles/<id>/monitors/<idx>/interval
            if (len(parts) == 7 and parts[1] == 'api' and parts[2] == 'profiles'
                    and parts[4] == 'monitors' and parts[6] == 'interval'):
                profile_id = parts[3]
                monitor_idx = int(parts[5])
                body = self._read_body()
                interval = int(body.get("interval_seconds", 30))
                
                profile = load_profile(profile_id)
                monitors = profile.get("monitors", [])
                if 0 <= monitor_idx < len(monitors):
                    monitors[monitor_idx]["interval_seconds"] = max(5, interval)
                    save_profile(profile_id, profile)
                    self._send_json({"ok": True})
                else:
                    self._send_json({"error": "Monitor index out of range"}, 400)
                return
            
            # POST /api/profiles/<id>/monitors/all
            if (len(parts) == 6 and parts[1] == 'api' and parts[2] == 'profiles'
                    and parts[4] == 'monitors' and parts[5] == 'all'):
                profile_id = parts[3]
                body = self._read_body()
                active = body.get("active", True)
                
                profile = load_profile(profile_id)
                for monitor in profile.get("monitors", []):
                    monitor["active"] = active
                save_profile(profile_id, profile)
                self._send_json({"ok": True})
                return
            
            self.send_error(404)
        
        except FileNotFoundError:
            self._send_json({"error": "Profile not found"}, 404)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


def main():
    parser = argparse.ArgumentParser(description='iNews Monitor - Panel de Control')
    parser.add_argument('--port', '-p', type=int, default=8080, help='Puerto (default: 8080)')
    args = parser.parse_args()
    
    # Cambiar al directorio del script
    os.chdir(get_base_dir())
    
    server = HTTPServer(('0.0.0.0', args.port), ControlPanelHandler)
    print(f"\n{'='*50}")
    print(f"  iNews Monitor - Panel de Control")
    print(f"  http://localhost:{args.port}")
    print(f"{'='*50}\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPanel de control detenido.")
        server.server_close()


if __name__ == "__main__":
    main()
