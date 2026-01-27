# iNews Monitor e Identificador de Contenido Twitter

Servicio automatizado para monitorear rundowns de iNews y descargar contenido multimedia de Twitter asociado a rótulos específicos.

## Funcionalidades

- **Monitoreo iNews**: Conexión FTP para leer archivos NSML.
- **Filtrado**: Detecta rótulos con etiquetas `<ap>` del tipo `X_Total` o `X_Faldon`.
- **Integración Twitter**: Extrae URLs de los rótulos y descarga imágenes/vídeos.
- **Gestión Inteligente**:
  - Carpetas por Tweet ID.
  - Limpieza automática de contenido obsoleto.
  - Generación de JSON con rutas locales para integración con gráficos.

## Requisitos

- Windows
- Python 3.8+ (Entorno virtual incluido/autogenerado)
- Acceso a servidor iNews
- Token de API de Twitter (Bearer Token)

## Configuración

1. Renombrar `config.example.json` a `config.json` y editar credenciales.
2. Configurar el `.env` en `ScriptsTwitter` con `TWITTER_BEARER_TOKEN`.

## Uso

Ejecutar `run_monitor.bat` para iniciar el servicio.

```cmd
run_monitor.bat
```
