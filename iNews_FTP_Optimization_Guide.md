# Guia para optimizar accesos FTP a iNews

Este documento resume los cambios aplicados en este proyecto para reducir el numero de sesiones FTP abiertas contra iNews y mantener una lectura suficientemente rapida de los minutados. La idea es que sirva como referencia para implementar el mismo patron en otros proyectos.

## Problema detectado

El monitor original creaba una conexion FTP por cada watcher o monitor de rundown y la mantenia abierta entre pasadas. Esto era rapido, pero podia ocupar demasiados accesos simultaneos al servidor iNews, bloqueando a otros usuarios.

El objetivo de la solucion es:

- Limitar de forma estricta cuantas sesiones FTP puede abrir la aplicacion.
- Repartir lecturas entre servidor principal y secundario cuando existan.
- Evitar lecturas duplicadas.
- Reducir operaciones `RETR` cuando una story no ha cambiado.
- Cerrar conexiones ociosas.
- Evitar picos de conexiones simultaneas.

## Diseno aplicado

### 1. Pool global de conexiones FTP

Se anadio una clase compartida `INewsConnectionPool`.

Antes:

- Cada `RundownWatcher` tenia su propia instancia de `INewsConnection`.
- Si habia 10 watchers activos, potencialmente habia 10 sesiones FTP abiertas.

Ahora:

- Los watchers piden una conexion prestada al pool.
- El pool reutiliza conexiones abiertas si puede.
- El pool nunca supera los limites configurados.
- Al terminar una lectura, el watcher devuelve la conexion al pool.

Esto permite mantener rendimiento sin dejar que el numero de sesiones crezca con el numero de watchers.

### 2. Reparto entre principal y secundario sin duplicar lecturas

La aplicacion no lee el mismo rundown en ambos servidores. En lugar de duplicar trabajo, cada watcher se asigna a un solo host.

Ejemplo con dos hosts:

```text
Watcher 1 -> servidor principal
Watcher 2 -> servidor secundario
Watcher 3 -> servidor principal
Watcher 4 -> servidor secundario
```

La asignacion se hace por round-robin global al crear los watchers. Si un watcher tiene configurado explicitamente `inews_host` o `host`, se respeta esa configuracion.

El `index.csv` sigue siendo completo porque no depende del servidor usado para leer. Se genera al final con la union de `active_urls` de todos los watchers activos, igual que antes.

### 3. Cierre de conexiones ociosas

Cada conexion registra su ultimo uso (`last_used`). El pool cierra conexiones que llevan mas de `idle_ttl_seconds` sin actividad.

Esto evita dejar sesiones abiertas durante largos periodos en los que no hay trabajo real.

### 4. Escalonado de watchers

Cuando varios watchers estan pendientes a la vez, se introduce una pequena pausa entre lanzamientos (`stagger_seconds`). Esto reduce picos bruscos de acceso FTP.

No cambia que datos se leen; solo reparte mejor el momento de acceso.

### 5. Cache de stories por metadata

Para evitar descargar todas las stories en cada pasada, se anadio una cache por watcher.

Flujo:

1. Se lista el directorio del rundown.
2. Se obtiene una firma de metadata por story.
3. Si la firma no ha cambiado desde la pasada anterior, no se hace `RETR`.
4. Se reutilizan las URLs ya extraidas de esa story.
5. Si la firma cambio o no hay cache, se lee la story completa y se recalculan URLs.

En este servidor iNews se probo que:

```text
MDTM -> 500 MDTM not recognized.
SIZE -> 502 SIZE command not implemented.
```

Por tanto, no se puede depender de `MDTM` ni `SIZE`.

La alternativa implementada usa la salida de `LIST`, que si devuelve informacion util:

```text
-f-------- 1 1     0 Jun 25 11:01  3E1C04F1:0058B5D6:6A3CEE73 .
```

Esa linea completa se usa como firma estable. Si cambia la fecha, hora, tamano o nombre, se considera que la story puede haber cambiado.

### 6. Polling adaptativo

Si un watcher pasa varias rondas sin detectar cambios, aumenta temporalmente su intervalo de lectura hasta `max_interval_seconds`.

Cuando detecta actividad, vuelve al intervalo base (`interval_seconds`).

Esto reduce carga en momentos tranquilos sin penalizar mucho cuando vuelve a haber cambios.

## Configuracion recomendada

El bloque `inews` puede quedar asi:

```json
{
  "inews": {
    "host": "172.28.158.11",
    "hosts": [
      "172.28.158.11",
      "IP_DEL_SERVIDOR_SECUNDARIO"
    ],
    "max_connections_total": 4,
    "max_connections_per_host": 2,
    "idle_ttl_seconds": 60,
    "acquire_timeout_seconds": 20,
    "user": "USUARIO",
    "password": "PASSWORD"
  }
}
```

Si aun no hay servidor secundario, se puede dejar:

```json
"hosts": [
  "172.28.158.11"
]
```

Valores sugeridos para empezar:

- `max_connections_total`: `4`
- `max_connections_per_host`: `2`
- `idle_ttl_seconds`: `60`
- `acquire_timeout_seconds`: `20`
- `stagger_seconds`: `0.5`

Si iNews sigue reportando saturacion, bajar primero `max_connections_total` a `2`.

## Configuracion opcional por watcher

Cada watcher puede forzar un servidor concreto:

```json
{
  "name": "TRD",
  "rundown_path": "INF-DIGITAL/.TR_DIG/.MINUTADO",
  "interval_seconds": 20,
  "inews_host": "172.28.158.11",
  "active": true
}
```

Tambien se pueden desactivar optimizaciones concretas:

```json
{
  "metadata_cache": false,
  "adaptive_polling": false,
  "max_interval_seconds": 60
}
```

## Piezas de codigo a replicar

En el otro proyecto, buscar una estructura similar a:

- Una clase que encapsula la conexion FTP.
- Una clase watcher/monitor que lee un rundown.
- Un punto donde se instancian todos los watchers.
- Un punto final donde se sincroniza el contenido o se genera el indice.

Cambios principales a trasladar:

1. Anadir `INewsConnectionPool`.
2. Hacer que los watchers reciban el pool en el constructor.
3. Sustituir conexiones persistentes por:

```python
with self.ftp_pool.acquire(self.assigned_host) as connection:
    # leer listado y stories usando esta conexion
```

4. Generar `assigned_host` por round-robin o respetar `inews_host` si viene configurado.
5. Usar `LIST` como metadata por story.
6. Mantener cache de URLs por story para no perder contenido vigente en el indice.
7. Cerrar conexiones ociosas al final de cada pasada.
8. Apagar el pool en parada o recarga de configuracion.

## Punto importante sobre el indice

Para que el indice final no pierda contenido, no basta con saltarse una story no modificada. Hay que reutilizar sus URLs cacheadas.

La cache debe guardar, como minimo:

```python
{
    "metadata": metadata,
    "matched": True,
    "urls": story_urls,
    "content_hash": content_hash
}
```

Cuando una story no cambia:

```python
if metadata == cached["metadata"]:
    current_urls.extend(cached["urls"])
    continue
```

Asi el `index.csv` sigue representando todo lo que esta activo en el rundown aunque no se haya vuelto a descargar cada story.

## Validaciones recomendadas

Antes de desplegar:

1. Compilar o ejecutar una comprobacion de sintaxis.
2. Probar una unica conexion al servidor principal.
3. Confirmar si existen `MDTM` y `SIZE`.
4. Si no existen, confirmar que `LIST` devuelve fecha/tamano/nombre.
5. Ejecutar una pasada real con un solo perfil activo.
6. Revisar logs para ver cuantos watchers se asignan a cada host.
7. Confirmar con iNews que el numero de sesiones abiertas baja.

## Resultado esperado

Con estos cambios, el sistema deberia:

- Abrir muchas menos sesiones FTP.
- No superar el limite configurado.
- Repartir carga entre principal y secundario si ambos estan configurados.
- Mantener un `index.csv` completo.
- Reducir lecturas completas de stories no modificadas.
- Ser mas amable con el servidor sin perder demasiada velocidad.
