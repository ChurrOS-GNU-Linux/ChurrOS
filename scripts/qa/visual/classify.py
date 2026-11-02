#!/usr/bin/env python3
"""Clasifica el diff de una pull request como visual o no.

Orden:

1. Reglas de ruta. Si alguna ruta es de interfaz, el diff es visual.
   Si todas son ajenas a la interfaz, no lo es. No hay llamada de red.
2. Lo que no casa con ninguna regla es ambiguo. Jev (TypeSafe, modelo
   System One) elige entre ``visual`` y ``not_visual`` y devuelve la
   probabilidad de cada opción. Se acepta su elección cuando la
   probabilidad más alta llega al umbral (por defecto 0.8).
3. Si esa probabilidad queda por debajo, o Jev falla, Claude Haiku
   responde sí o no.

Las claves ``TYPESAFE_API_KEY`` y ``ANTHROPIC_API_KEY`` solo salen en
las cabeceras HTTP. Ningún log imprime la clave ni el cuerpo de error.

La forma de la llamada a Jev está aislada en ``ask_jev`` y sigue
``POST https://api.typesafe.ai/v1/systemone`` (docs.typesafe.ai,
primitiva Choice): ``model``, ``state`` y ``questions.<id>`` con
``type=choice``, ``instructions`` y ``criteria``. La respuesta trae
``answers.<id>.choice``, ``probabilities`` y ``confidence``.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

JEV_URL = "https://api.typesafe.ai/v1/systemone"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
JEV_QUESTION = "appearance"
DEFAULT_JEV_MODEL = "jev-latest"
DEFAULT_HAIKU_MODEL = "claude-haiku-4-5"
DEFAULT_THRESHOLD = 0.8
STATE_LIMIT = 24_000

# Rutas que cambian lo que se ve. Se comparan contra la ruta normalizada
# del repositorio (también valen los trozos que viven bajo airootfs).
VISUAL_SUBSTRINGS = (
    "branding/",
    "installer/calamares/branding/",
    "etc/skel/.config/noctalia/",
    "etc/skel/.config/waybar/",
    "etc/skel/.config/wlogout/",
    "etc/skel/.config/niri/",
    "usr/share/churros/styles/",
    "usr/share/churros/defaults/",
    "usr/share/churros/pi/",
    "usr/share/plymouth/",
    "usr/share/color-schemes/",
    "grub-theme/",
)

# Prefijos que no cambian píxeles. Todo lo demás, si no es visual, es ambiguo.
NON_VISUAL_PREFIXES = (
    "docs/",
    "tests/",
    ".github/",
    "scripts/cli/",
    "scripts/lib/",
    "scripts/qa/",
    "scripts/test-",
)
NON_VISUAL_FILES = {
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "LICENSE",
    "COPYING",
    "MAINTAINERS",
    "AGENTS.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "README.md",
    "ARCHITECTURE.md",
}

SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|authorization)\b\s*[:=]\s*\S+"
)


class JevError(Exception):
    """Fallo de Jev con un código corto, sin cuerpo ni clave."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Decision:
    def __init__(
        self,
        visual: bool,
        decider: str,
        probability: float | None,
        model: str,
        *,
        reason: str = "",
        jev_probability: float | None = None,
        jev_choice: str | None = None,
        jev_model: str | None = None,
    ) -> None:
        self.visual = visual
        self.decider = decider
        self.probability = probability
        self.model = model
        self.reason = reason
        self.jev_probability = jev_probability
        self.jev_choice = jev_choice
        self.jev_model = jev_model

    def as_dict(self) -> dict:
        return {
            "visual": self.visual,
            "decider": self.decider,
            "probability": self.probability,
            "model": self.model,
            "reason": self.reason,
            "jev_probability": self.jev_probability,
            "jev_choice": self.jev_choice,
            "jev_model": self.jev_model,
        }


def normalize(path: str) -> str:
    text = path.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def is_visual_path(path: str) -> bool:
    """True si la ruta cae en una regla determinista de interfaz."""
    text = normalize(path)
    if not text:
        return False
    if any(marker in text or text.rstrip("/") == marker.rstrip("/") for marker in VISUAL_SUBSTRINGS):
        return True
    parts = [part for part in text.split("/") if part]
    if "icons" in parts:
        return True
    name = parts[-1] if parts else ""
    return name == "churros-theme" or name.startswith("churros-theme.")


def is_non_visual_path(path: str) -> bool:
    text = normalize(path)
    if text in NON_VISUAL_FILES or Path(text).name in NON_VISUAL_FILES and "/" not in text:
        return True
    return any(text.startswith(prefix) for prefix in NON_VISUAL_PREFIXES)


def split_paths(paths: list[str]) -> tuple[list[str], list[str], list[str]]:
    visual, non_visual, ambiguous = [], [], []
    for path in paths:
        text = normalize(path)
        if not text:
            continue
        if is_visual_path(text):
            visual.append(text)
        elif is_non_visual_path(text):
            non_visual.append(text)
        else:
            ambiguous.append(text)
    return visual, non_visual, ambiguous


def redact(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return SECRET_ASSIGNMENT.sub(r"\1=[redacted]", cleaned)


def read_threshold(value: str | None) -> float:
    if value is None or not str(value).strip():
        return DEFAULT_THRESHOLD
    number = float(str(value).strip())
    if not 0.0 <= number <= 1.0:
        raise ValueError("el umbral tiene que estar entre 0 y 1")
    return number


def env_model(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def jev_request_body(state: str, model: str) -> dict:
    """Cuerpo documentado de POST /v1/systemone para una Choice."""
    return {
        "model": model or DEFAULT_JEV_MODEL,
        "state": state,
        "questions": {
            JEV_QUESTION: {
                "type": "choice",
                "instructions": (
                    "Does this diff change something a person would see on screen "
                    "in ChurrOS? Visible means the desktop, bar, launcher, session "
                    "menu, icons, colors, typography, wallpapers, installer chrome, "
                    "Plymouth splash, or GRUB theme. Not visible means documentation, "
                    "tests, packaging, or code that leaves those surfaces unchanged."
                ),
                "criteria": {
                    "visual": (
                        "The diff changes a surface a person can see: layout, color, "
                        "type, icons, wallpaper, installer, boot splash, or GRUB theme."
                    ),
                    "not_visual": (
                        "The diff does not change a visible surface. Docs, tests, CI, "
                        "and behavior that stays off-screen belong here."
                    ),
                },
            },
        },
    }


def parse_jev_response(payload: dict) -> dict:
    """Lee choice, probabilities y confidence. JevError('shape') si no cuadra."""
    if not isinstance(payload, dict):
        raise JevError("shape")
    answers = payload.get("answers")
    if not isinstance(answers, dict) or JEV_QUESTION not in answers:
        raise JevError("shape")
    answer = answers[JEV_QUESTION]
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise JevError("shape")
    choice = answer.get("choice")
    probabilities = answer.get("probabilities")
    if choice not in ("visual", "not_visual") or not isinstance(probabilities, dict):
        raise JevError("shape")
    parsed: dict[str, float] = {}
    for key in ("visual", "not_visual"):
        if key not in probabilities:
            raise JevError("shape")
        try:
            parsed[key] = float(probabilities[key])
        except (TypeError, ValueError):
            raise JevError("shape") from None
    winner = max(parsed, key=parsed.get)
    if winner != choice:
        raise JevError("shape")
    confidence = answer.get("confidence")
    try:
        confidence_value = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence_value = None
    model = payload.get("model")
    return {
        "choice": choice,
        "probabilities": parsed,
        "top_probability": parsed[winner],
        "confidence": confidence_value,
        "model": model if isinstance(model, str) and model else "",
    }


def ask_jev(state: str, *, api_key: str, model: str, timeout: float = 45.0) -> dict:
    """POST /v1/systemone. El único sitio que habla con api.typesafe.ai.

    Authorization: Bearer, Content-Type JSON. No registra la petición ni
    el cuerpo de la respuesta: un 401 o un 422 solo producen ``http-<código>``.
    """
    if not api_key:
        raise JevError("no-key")
    raw = json.dumps(jev_request_body(state, model)).encode("utf-8")
    request = urllib.request.Request(
        JEV_URL,
        data=raw,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        try:
            exc.read()
        except Exception:
            pass
        raise JevError(f"http-{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise JevError("network") from None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise JevError("shape") from None
    return parse_jev_response(payload)


def parse_haiku_text(text: str) -> bool | None:
    """True/False si la primera palabra es yes o no. None si no se entiende."""
    token = re.split(r"[\s,.;:]+", text.strip().lower(), maxsplit=1)[0] if text.strip() else ""
    if token in {"yes", "y", "visual", "true"}:
        return True
    if token in {"no", "n", "not_visual", "false"}:
        return False
    return None


def ask_haiku(state: str, *, api_key: str, model: str, timeout: float = 45.0) -> bool:
    """POST /v1/messages. True si Haiku dice que el diff es visual.

    La clave va en ``x-api-key``. Un fallo o una respuesta que no es sí/no
    lanza ``JevError`` con un código corto (se reutiliza el tipo para no
    abrir otro canal de mensajes: el llamador lo trata como escalado fallido).
    """
    if not api_key:
        raise JevError("no-key")
    prompt = (
        "Answer with a single word, yes or no.\n"
        "Does this diff change something a person would see on screen in ChurrOS "
        "(desktop, bar, launcher, session menu, icons, colors, typography, "
        "wallpaper, installer, Plymouth, or GRUB theme)?\n\n"
        + state
    )
    raw = json.dumps({
        "model": model or DEFAULT_HAIKU_MODEL,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        ANTHROPIC_URL,
        data=raw,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        try:
            exc.read()
        except Exception:
            pass
        raise JevError(f"http-{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise JevError("network") from None
    try:
        payload = json.loads(body.decode("utf-8"))
        blocks = payload.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
    except (UnicodeError, json.JSONDecodeError, AttributeError):
        raise JevError("shape") from None
    parsed = parse_haiku_text(text)
    if parsed is None:
        raise JevError("shape")
    return parsed


def build_state(ambiguous: list[str], diff: str, secrets: list[str]) -> str:
    kept = []
    if diff.strip():
        current: list[str] = []
        current_path = ""
        for line in diff.splitlines():
            match = re.match(r"^diff --git a/(.+?) b/", line)
            if match:
                if current and current_path in ambiguous:
                    kept.extend(current)
                current = [line]
                current_path = normalize(match.group(1))
                continue
            current.append(line)
        if current and current_path in ambiguous:
            kept.extend(current)
    body = "paths:\n" + "\n".join(ambiguous)
    if kept:
        body += "\n\ndiff:\n" + "\n".join(kept)
    elif diff.strip():
        body += "\n\ndiff:\n" + diff
    body = redact(body, secrets)
    if len(body) > STATE_LIMIT:
        body = body[:STATE_LIMIT] + "\n\n[diff truncated]"
    return body


def _rules(visual: bool) -> Decision:
    return Decision(visual, "rules", 1.0, "rules", reason="path-rules")


def classify(
    paths: list[str],
    diff: str = "",
    *,
    threshold: float = DEFAULT_THRESHOLD,
    jev_model: str = DEFAULT_JEV_MODEL,
    haiku_model: str = DEFAULT_HAIKU_MODEL,
    typesafe_api_key: str = "",
    anthropic_api_key: str = "",
    jev=None,
    haiku=None,
    log=None,
) -> Decision:
    """Devuelve la decisión. ``jev`` y ``haiku`` sustituyen la red en las pruebas."""
    secrets = [typesafe_api_key, anthropic_api_key]
    write = log or (lambda message: print(redact(message, secrets), file=sys.stderr))
    visual_paths, _non_visual, ambiguous = split_paths(paths)
    if visual_paths:
        decision = _rules(True)
        write(
            f"visual-qa: decider=rules visual=true probability=1.0000 "
            f"paths={len(visual_paths)}"
        )
        return decision
    if not ambiguous:
        decision = _rules(False)
        write("visual-qa: decider=rules visual=false probability=1.0000")
        return decision

    state = build_state(ambiguous, diff, secrets)
    jev_call = jev or ask_jev
    haiku_call = haiku or ask_haiku
    try:
        answer = jev_call(state, api_key=typesafe_api_key, model=jev_model)
    except JevError as exc:
        write(f"visual-qa: jev error={exc.code}; escalating")
        return _escalate(state, haiku_call, haiku_model, anthropic_api_key, secrets, write, reason=exc.code)
    except Exception:
        write("visual-qa: jev error=unexpected; escalating")
        return _escalate(state, haiku_call, haiku_model, anthropic_api_key, secrets, write, reason="unexpected")

    top = float(answer["top_probability"])
    choice = answer["choice"]
    resolved = answer.get("model") or jev_model
    confidence = answer.get("confidence")
    confidence_text = "n/a" if confidence is None else f"{float(confidence):.4f}"
    escalate = top < threshold
    write(
        "visual-qa: jev "
        f"model={resolved} choice={choice} probability={top:.4f} "
        f"confidence={confidence_text} threshold={threshold:.4f} "
        f"escalate={'yes' if escalate else 'no'}"
    )
    if escalate:
        return _escalate(
            state, haiku_call, haiku_model, anthropic_api_key, secrets, write,
            reason="below-threshold", jev_probability=top, jev_choice=choice, jev_model=resolved,
        )
    decision = Decision(
        choice == "visual",
        "jev",
        top,
        resolved,
        reason="jev",
        jev_probability=top,
        jev_choice=choice,
        jev_model=resolved,
    )
    write(
        f"visual-qa: decider=jev visual={'true' if decision.visual else 'false'} "
        f"probability={top:.4f} model={resolved}"
    )
    return decision


def _escalate(state, haiku_call, haiku_model, api_key, secrets, write, *, reason, jev_probability=None, jev_choice=None, jev_model=None) -> Decision:
    try:
        visual = bool(haiku_call(state, api_key=api_key, model=haiku_model))
    except JevError as exc:
        write(f"visual-qa: haiku error={exc.code}; decider=unresolved visual=false")
        return Decision(
            False, "unresolved", None, haiku_model, reason=f"haiku-{exc.code}",
            jev_probability=jev_probability, jev_choice=jev_choice, jev_model=jev_model,
        )
    except Exception:
        write("visual-qa: haiku error=unexpected; decider=unresolved visual=false")
        return Decision(
            False, "unresolved", None, haiku_model, reason="haiku-unexpected",
            jev_probability=jev_probability, jev_choice=jev_choice, jev_model=jev_model,
        )
    write(
        f"visual-qa: decider=haiku model={haiku_model} "
        f"visual={'true' if visual else 'false'} probability=n/a reason={reason}"
    )
    return Decision(
        visual, "haiku", None, haiku_model, reason=reason,
        jev_probability=jev_probability, jev_choice=jev_choice, jev_model=jev_model,
    )


def format_probability(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def write_github_output(path: Path, decision: Decision) -> None:
    line = "\n".join([
        f"visual={'true' if decision.visual else 'false'}",
        f"decider={decision.decider}",
        f"model={decision.model}",
        f"probability={format_probability(decision.probability)}",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def load_paths(path: Path | None, extra: list[str]) -> list[str]:
    found = list(extra)
    if path is not None:
        found.extend(path.read_text(encoding="utf-8").splitlines())
    return [normalize(item) for item in found if normalize(item)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clasifica un diff como visual o no.")
    parser.add_argument("--paths-file", type=Path, help="Un path por línea")
    parser.add_argument("--diff-file", type=Path, help="Diff unificado, opcional")
    parser.add_argument("--github-output", type=Path, help="Fichero GITHUB_OUTPUT")
    parser.add_argument("--result", type=Path, help="JSON con la decisión")
    parser.add_argument("paths", nargs="*", help="Rutas sueltas")
    args = parser.parse_args(argv)
    if args.paths_file is None and not args.paths and sys.stdin.isatty():
        parser.error("indica rutas, --paths-file o entrándolas por stdin")
    try:
        threshold = read_threshold(os.environ.get("VISUAL_QA_JEV_THRESHOLD"))
    except ValueError as exc:
        print(f"visual-qa: {exc}", file=sys.stderr)
        return 2
    paths = load_paths(args.paths_file, args.paths)
    if args.paths_file is None and not args.paths:
        paths = [normalize(line) for line in sys.stdin.read().splitlines() if normalize(line)]
    diff = args.diff_file.read_text(encoding="utf-8", errors="replace") if args.diff_file else ""
    typesafe_key = os.environ.get("TYPESAFE_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    try:
        decision = classify(
            paths,
            diff,
            threshold=threshold,
            jev_model=env_model("VISUAL_QA_JEV_MODEL", DEFAULT_JEV_MODEL),
            haiku_model=env_model("VISUAL_QA_MODEL", DEFAULT_HAIKU_MODEL),
            typesafe_api_key=typesafe_key,
            anthropic_api_key=anthropic_key,
        )
    except Exception as exc:
        print(f"visual-qa: error=internal detail={redact(type(exc).__name__, [typesafe_key, anthropic_key])}", file=sys.stderr)
        return 1
    if args.github_output:
        write_github_output(args.github_output, decision)
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(decision.as_dict(), indent=2) + "\n", encoding="utf-8")
    print("true" if decision.visual else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
