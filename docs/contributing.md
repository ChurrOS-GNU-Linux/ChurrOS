# Contributing

¡Gracias por tu interés en contribuir a ChurrOS!

Actualmente el proyecto se encuentra en una etapa temprana de desarrollo y toda ayuda es bienvenida.

El objetivo de esta guía es mantener un flujo de trabajo organizado y consistente para todos los colaboradores.

---

# Antes de comenzar

Antes de realizar cualquier cambio se recomienda:

- Leer toda la documentación ubicada en `docs/`.
- Comprender la estructura del proyecto.
- Configurar correctamente el entorno de desarrollo.
- Generar una ISO de prueba utilizando la CLI.

Consulta `getting-started.md` si es tu primera vez colaborando.

---

# Flujo de trabajo

El flujo de desarrollo recomendado es el siguiente:

```
Fork (si aplica)

↓

Crear una rama

↓

Realizar cambios

↓

Compilar

↓

Probar

↓

Documentar

↓

Commit

↓

Push

↓

Pull Request
```

---

# Crear una rama

Cada nueva funcionalidad debe desarrollarse en una rama independiente.

Ejemplos:

```bash
git checkout -b feature/fastfetch
```

```bash
git checkout -b feature/installer
```

```bash
git checkout -b fix/build-system
```

No trabajar directamente sobre `main`. Cada cambio va en su rama y entra por pull request.

---

# Antes de hacer un commit

Verifica siempre que:

- Las comprobaciones automáticas pasan.
- La ISO compila correctamente.
- El sistema inicia sin errores.
- La documentación está actualizada.
- No existen archivos temporales innecesarios.

Ejecuta primero:

```bash
./churros check
```

Revisa sintaxis Bash y Python, paquetes duplicados, comandos del autostart de Niri, entradas `.desktop`, orden de Calamares, extras AUR en `netinstall.yaml` y que las traducciones compilen. Tarda unos segundos y no necesita construir la ISO. Es lo mismo que ejecuta el CI en cada Pull Request, así que si falla aquí, fallará allá.

Si el cambio toca el escritorio, el instalador o el build:

```bash
./churros build
```

y posteriormente:

```bash
./churros run
```

---

# Convención para commits

Se recomienda utilizar mensajes descriptivos.

Ejemplos:

```text
feat: añadir branding de Fastfetch

fix: corregir el script de build

docs: actualizar la guía de instalación

refactor: simplificar la CLI
```

Prefijo corto en inglés (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`) y el resto en español.

Evita mensajes como:

```
update

changes

fix

test
```

---

# Documentación

Toda funcionalidad nueva debe estar documentada.

Si agregas:

- un comando nuevo,
- una herramienta,
- una configuración,
- una característica,

actualiza el documento correspondiente dentro de `docs/`.

---

# Organización

Respeta la estructura del proyecto.

Ejemplo:

```
branding/
```

identidad visual y script live.

```
rust/
```

apps oficiales (gtk4-rs).

```
scripts/
```

CLI y scripts de build.

```
docs/
```

documentación.

Mantener una estructura limpia facilita el mantenimiento del proyecto.

---

# Código

Al escribir código intenta mantener estas reglas:

- Código legible.
- Nombres descriptivos.
- Evitar duplicación.
- Evitar scripts innecesariamente complejos.
- Priorizar la simplicidad.

---

# A quién dirigirse

El fichero [`MAINTAINERS`](https://github.com/ChurrOS-GNU-Linux/ChurrOS/blob/main/MAINTAINERS) indica qué persona responde por cada área del repositorio, para saber a quién preguntar antes de abrir un issue.

Las asignaciones se deducen del historial de commits; si algo está mal, se corrige en un pull request.

---

# Reportar errores

Si encuentras un problema, intenta incluir:

- Descripción del error.
- Pasos para reproducirlo.
- Resultado esperado.
- Resultado obtenido.
- Capturas de pantalla (si aplica).
- Registros relevantes.

Esto facilita encontrar la causa del problema.

---

# Sugerencias

Las nuevas ideas son bienvenidas.

Antes de implementar una característica grande, se recomienda abrir primero un Issue para discutirla.

De esta manera se evita desarrollar funcionalidades que puedan cambiar posteriormente.

---

# Filosofía

La prioridad de ChurrOS no es añadir la mayor cantidad posible de funciones.

La prioridad es construir una distribución estable, organizada y fácil de mantener.

Cada contribución debe seguir esta filosofía.

---

# Gracias

Cada contribución ayuda a mejorar ChurrOS.

Gracias por dedicar tu tiempo a este proyecto.