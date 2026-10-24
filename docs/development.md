# Development

Este documento describe el flujo de trabajo recomendado para desarrollar ChurrOS.

Su objetivo es mantener un proceso de desarrollo consistente, organizado y fácil de seguir.

---

# Filosofía

El desarrollo de ChurrOS se basa en cuatro principios fundamentales:

- Simplicidad.
- Organización.
- Automatización.
- Documentación.

Todo cambio importante debe estar documentado y ser fácilmente reproducible.

---

# Flujo de trabajo

El ciclo de desarrollo recomendado es el siguiente:

Crear una rama desde `origin/main`

↓

Modificar código

↓

```bash
./churros check
```

↓

```bash
./churros build
```

↓

```bash
./churros run
```

↓

Verificar funcionamiento

↓

Commit (un cambio coherente)

↓

Pull request hacia `main`

No se trabaja ni se empuja directo a `main`.

---

# Organización del proyecto

Antes de agregar nuevos archivos, verifica que pertenezcan al directorio correcto.

Apps oficiales (Rust)

```
rust/
```

Documentación

```
docs/
```

Identidad visual y script live

```
branding/
```

Calamares

```
installer/
```

Scripts y CLI

```
scripts/
```

Perfil del sistema Live

```
archiso/
```

---

# Commits

Los commits deben ser pequeños y representar una única modificación lógica.

Prefijo corto en inglés y el resto en español:

```
feat: añadir branding de Fastfetch

fix: corregir el script de build

docs: actualizar la guía de branding

refactor: simplificar la CLI
```

Evita commits con varios cambios no relacionados.

---

# Documentación

Toda nueva funcionalidad debe incluir su documentación correspondiente.

| Cambio | Documento |
|--------|-----------|
| Nuevo comando CLI | `docs/cli.md` |
| Proceso de compilación | `docs/build-system.md` |
| App oficial | `docs/apps.md` (y el doc dedicado si existe) |
| Identidad visual | `docs/branding.md` |

---

# Pruebas

Antes de un commit de código:

```bash
./churros test
```

Si el cambio toca el escritorio, el instalador o el build:

```bash
./churros build
./churros test --iso --boot
./churros run
```

Las capas, qué cubre cada una y las reglas para no debilitarlas están en [Pruebas](testing.md).

Para iterar una app Rust sin reconstruir la ISO:

```bash
cargo build --release --manifest-path rust/Cargo.toml
```

El binario queda en `rust/target/release/<nombre>`.

---

# Buenas prácticas

- Utilizar nombres descriptivos.
- Evitar duplicar código.
- Mantener la estructura del proyecto organizada.
- Escribir comentarios únicamente cuando aporten valor.
- Mantener la documentación actualizada.

---

# Ramas

`main` es la rama estable. Cada cambio va en su propia rama (`fix/…`, `feat/…`, `docs/…`) y entra por pull request.

No reutilizar ramas ya fusionadas. Partir siempre de `origin/main` actualizado.

---

# Objetivo

El objetivo del flujo de desarrollo es mantener un proyecto limpio, organizado y fácil de mantener conforme ChurrOS continúe creciendo.
