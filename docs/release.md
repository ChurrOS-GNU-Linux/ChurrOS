# Release

Este documento describe el proceso oficial para generar una nueva versión de ChurrOS.

El objetivo es garantizar que todas las versiones publicadas sean reproducibles, estables y correctamente documentadas.

---

# Objetivo

Antes de publicar una nueva versión se debe comprobar que:

- La ISO se construye correctamente.
- El sistema Live inicia sin errores.
- El branding es consistente.
- La documentación está actualizada.
- No existen cambios sin confirmar.

---

# Flujo de publicación

El proceso recomendado es el siguiente:

```
Actualizar código

↓

Actualizar documentación

↓

Compilar la ISO

↓

Probar en máquina virtual

↓

Crear versión

↓

Crear Release

↓

Publicar
```

---

# 1. Actualizar el repositorio

Antes de comenzar verifica que el repositorio esté actualizado.

```bash
git pull
```

---

# 2. Verificar el estado

Comprueba que no existan cambios pendientes.

```bash
git status
```

El resultado esperado es:

```
working tree clean
```

---

# 3. Compilar

Construye una nueva ISO.

```bash
./churros build
```

La compilación debe finalizar sin errores.

---

# 4. Probar

Ejecuta la ISO.

```bash
./churros run
```

Verifica:

- Arranque correcto.
- Inicio de sesión.
- Branding.
- Fastfetch.
- Servicios principales.
- Ausencia de errores críticos.

---

# 5. Actualizar la versión

El número de versión vive en `VERSION`. Lo muestran `./churros version`, `./churros info`, el footer de welcome, Ajustes y el `os-release` de la ISO. Debe coincidir con el tag de GitHub cuando exista.

La versión actual es **1.3**. El esquema previsto es Semantic Versioning (`MAJOR.MINOR.PATCH`); algunas ISO y tags omiten el parche (`v0.6`, `v0.7`).

Ejemplo:

```
1.2

↓

1.3
```

---

# 6. Crear el commit

Registrar todos los cambios.

```bash
git add .
git commit -m "release: preparar versión 1.3"
```

---

# 7. Crear un tag

Marcar la versión publicada.

```bash
git tag v1.3
```

Enviar el tag.

```bash
git push origin v1.3
```

---

# 8. Publicar

Subir los cambios al repositorio.

```bash
git push
```

Posteriormente publicar la ISO y el torrent en download.churroslinux.org. También puede crearse un GitHub Release.

---

# Archivos de la versión

Cada versión oficial de ChurrOS se compone de:

1. **Imagen ISO de instalación:**
   - Archivo `.iso` generado por `./churros build`.
   - Sumas de verificación `SHA256SUMS`.
   - Archivo `.torrent` para distribución P2P en download.churroslinux.org.

2. **Bundle de actualización OTA (Over-The-Air):**
   - Paquete de utilidades `churros-utils-<version>.tar.zst` generado con:
     ```bash
     ./scripts/build-churros-release.sh
     ```
   - Manifiesto `updates.json` que contiene:
     ```json
     {
       "version": "1.3",
       "date": "2026-10-12",
       "file": "churros-utils-1.3-x86_64.tar.zst",
       "sha256": "<hash_sha256>"
     }
     ```
   - Al publicar ambos archivos en `https://download.churroslinux.org/churros/`, los sistemas ya instalados reciben automáticamente las nuevas versiones de las apps Rust (`churros-settings`, `churros-welcome`, `churros-popup`, `churros-control-center`), scripts del sistema y assets sin necesidad de reinstalar la distribución.

---

# Versionado

ChurrOS seguirá el esquema Semantic Versioning.

```
MAJOR.MINOR.PATCH
```

Ejemplos:

```
0.4.0

0.6

0.7

1.0.0
```

---

# Checklist

Antes de publicar verificar:

- [ ] La ISO compila correctamente.
- [ ] La máquina virtual inicia.
- [ ] El branding es correcto.
- [ ] La documentación está actualizada.
- [ ] No existen errores conocidos críticos.
- [ ] El repositorio está limpio.
- [ ] La versión fue etiquetada correctamente.

---

# Futuro

En futuras versiones este proceso será automatizado mediante la CLI de ChurrOS.

El objetivo es que un único comando permita generar una nueva versión oficial de la distribución, incluyendo la compilación, verificación, creación de checksums y preparación del Release.