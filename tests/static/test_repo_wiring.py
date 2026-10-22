"""Guardas sobre las guardas: que ninguna prueba se apague en silencio.

Un cambio hecho por una IA puede dejar el CI en verde sin probar nada: un
`if true` en lugar de la llamada a un test, un `continue-on-error`, un
`exit 0` antes del resumen, un script de prueba que nadie lanza, o un
AGENTS.md que describe comprobaciones que ya no existen (y que la siguiente
IA se cree). Este módulo comprueba:

- el despachador `./churros`: cada comando público tiene script y sale en la
  ayuda; lo demás de scripts/cli/ es un helper documentado;
- el cableado: cada punto de entrada de prueba (scripts/test-*, tests/**,
  tests #[ignore] de Rust) se ejecuta desde un workflow, directamente o a
  través de check.sh;
- que check.sh y los workflows no neutralizan esas llamadas;
- higiene de los workflows (permisos, timeout, concurrency, versiones);
- que AGENTS.md y la documentación del instalador dicen la verdad;
- el formato de tests/known_issues.toml y, si existe, CODEOWNERS.

Los hallazgos reales que hoy no se arreglan van a tests/known_issues.toml
con las categorías `wiring`, `workflow` y `docs`.
"""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from functools import lru_cache
from pathlib import Path
import re
import shlex
import unittest

from tests import testlib

ROOT = testlib.ROOT
THIS_FILE = Path(__file__).resolve()
CHECK_SH = "scripts/cli/check.sh"
WORKFLOWS_DIR = ROOT / ".github/workflows"

# Ficheros de scripts/cli/ que no son comandos públicos: qué son y por qué
# no salen en `./churros help`. Uno nuevo se documenta aquí.
CLI_HELPERS = {
    "apps-dev-stub.sh": "stub que `./churros apps` (scripts/cli/apps.sh) enlaza como "
                        "nmcli/gsettings/systemctl para no tocar el host",
}

# Acciones cuyo ref no es una versión por diseño. dtolnay/rust-toolchain usa
# el nombre de la rama como selector del toolchain (@stable, @nightly,
# @1.89.0) y no publica tags vN (README de la acción).
ACTION_REF_EXCEPTIONS = {
    "dtolnay/rust-toolchain": r"stable|beta|nightly|1\.\d+(?:\.\d+)?",
}

# Pasos que construyen una ISO o una imagen de contenedor, o arrancan QEMU:
# minutos u horas de runner. En un PR, sin concurrency cada push los apila.
HEAVY_RE = re.compile(
    r"\./churros\s+(?:build|run|rust)\b|--container\b|container_ensure_image|mkarchiso"
    r"|qemu-system|\b(?:docker|podman)\s+build\b|docker/build-push-action"
)

# Documentos que describen la secuencia de Calamares.
INSTALLER_DOCS = ("AGENTS.md", "installer/README.md", "docs/installer.md", "docs/boot.md")

# Palabras que convierten una mención en una negación ("There is no
# shellprocess@x", "ya no existe"): esas líneas no afirman que exista.
NEGATION_RE = re.compile(
    r"\*\*no\*\*|\b(?:no|not|never|sin|ya no|removed|eliminad[oa]s?|retirad[oa]s?|deprecated|obsolet[oa]s?)\b",
    re.IGNORECASE,
)


# ------------------------------------------------------------ lectura de shell

def read(rel_path: str) -> str:
    return testlib.read_text(ROOT / rel_path)


@dataclass(frozen=True)
class Stmt:
    """Línea lógica de shell (con las continuaciones `\\` unidas) que empieza
    fuera de comillas y de heredocs. Sin el comentario final."""
    lineno: int
    text: str

    @property
    def column0(self) -> bool:
        return bool(self.text) and not self.text[0].isspace()


def shell_statements(text: str) -> list[Stmt]:
    """Sentencias de un script: lo que bash ejecuta, no lo que es texto.

    Un mini-lexer sigue comillas simples/dobles y heredocs entre líneas, así
    un `exit 0` dentro de un programa awk o de un stub escrito con heredoc no
    cuenta como sentencia del script.
    """
    stmts: list[Stmt] = []
    state = None            # None | "'" | '"'
    heredocs: list[tuple[str, bool]] = []
    in_heredoc: tuple[str, bool] | None = None
    pending: list[str] = []
    start_line = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        if in_heredoc:
            word, strip_tabs = in_heredoc
            if (raw.lstrip("\t") if strip_tabs else raw) == word:
                in_heredoc = heredocs.pop(0) if heredocs else None
            continue
        starts_clean = state is None and not pending
        out, i = [], 0
        while i < len(raw):
            ch = raw[i]
            if state is None:
                if ch == "#" and (i == 0 or raw[i - 1].isspace()):
                    break
                if ch == "\\" and i + 1 < len(raw):
                    out.append(raw[i:i + 2])
                    i += 2
                    continue
                if ch in "'\"":
                    state = ch
                elif raw.startswith("<<", i) and not raw.startswith("<<<", i):
                    match = re.match(r"<<(-?)\s*(['\"]?)([\w.-]+)\2", raw[i:])
                    if match:
                        heredocs.append((match.group(3), bool(match.group(1))))
                        out.append(match.group(0))
                        i += len(match.group(0))
                        continue
            elif state == "'":
                if ch == "'":
                    state = None
            else:
                if ch == "\\" and i + 1 < len(raw):
                    out.append(raw[i:i + 2])
                    i += 2
                    continue
                if ch == '"':
                    state = None
            out.append(ch)
            i += 1
        line = "".join(out).rstrip()
        if starts_clean:
            start_line = lineno
        if state is None and line.endswith("\\") and not line.endswith("\\\\"):
            pending.append(line[:-1])
            continue
        if starts_clean or pending:
            pending.append(line)
            joined = " ".join(part.strip() if k else part for k, part in enumerate(pending))
            if joined.strip():
                stmts.append(Stmt(start_line, joined))
            pending = []
        if heredocs and in_heredoc is None and state is None:
            in_heredoc = heredocs.pop(0)
    return stmts


def strip_messages(line: str) -> str:
    """Vacía las cadenas entre comillas que son texto (llevan espacios y no
    `$(`): así `pass "... (scripts/test-x.py)"` no cuenta como llamada."""
    out, i = [], 0
    while i < len(line):
        ch = line[i]
        if ch not in "'\"":
            out.append(ch)
            i += 1
            continue
        j = i + 1
        while j < len(line) and line[j] != ch:
            j += 2 if ch == '"' and line[j] == "\\" else 1
        if j >= len(line):
            out.append(line[i:])
            break
        body = line[i + 1:j]
        if re.search(r"\s", body) and "$(" not in body and not line[:i].rstrip().endswith("-c"):
            out.append(ch + ch)
        else:
            out.append(line[i:j + 1])
        i = j + 1
    return "".join(out)


def code_lines(text: str) -> list[str]:
    """Líneas sin comentarios ni mensajes, para buscar invocaciones. Incluye
    los heredocs (pueden ser scripts que se ejecutan): mejor un falso
    'cableado' que un falso 'sin cablear'."""
    lines, pending = [], ""
    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        raw = re.sub(r"(?<=\s)#.*$", "", raw)
        if raw.rstrip().endswith("\\"):
            pending += raw.rstrip()[:-1] + " "
            continue
        lines.append(strip_messages(pending + raw))
        pending = ""
    if pending:
        lines.append(strip_messages(pending))
    return lines


PATH_RE = re.compile(r"""(?P<pre>["']?(?:\$\{?\w+\}?["']?/)?(?:\./)?)(?P<path>(?:scripts|tests)/[\w.*/-]*[\w*])""")
CHURROS_RE = re.compile(r"""(?P<pre>["']?(?:\$\{?\w+\}?["']?/)?(?:\./)?)churros["']?[ \t]+(?P<cmd>[a-z][\w-]*)""")
DISCOVER_RE = re.compile(r"-m\s+unittest(?P<args>(?:\s+[^;&|)`\s]+)*)")
COMMAND_WORDS = {"", "then", "do", "else", "if", "elif", "!", "--", "time", "exec", "sudo",
                 "env", "nohup", "command", "timeout", "xargs", "setsid"}
INTERPRETERS = {"python", "python3", "node", "bash", "sh", "zsh", "dash", "source", "."}


def in_command_position(before: str) -> bool:
    """¿Lo que sigue a `before` se ejecuta (comando o script de un intérprete)?"""
    tokens = before.split()
    for token in reversed(tokens):  # dentro de [ ... ] o test es un argumento
        if token in {"[", "[[", "test"}:
            return False
        if token in {"then", "do", "else", "if", "elif"} or re.search(r"[;&|(`]$", token):
            break
    while tokens and ((tokens[-1].startswith("-") and tokens[-1] != "--")
                      or re.fullmatch(r"\d+[smhd]?", tokens[-1])):
        tokens.pop()
    if not tokens:
        return True
    part = re.split(r"[;&|(`=]", tokens[-1])[-1]
    if re.fullmatch(r"[\"']+", part):
        return False  # fin de un argumento entre comillas (o cadena vaciada)
    last = part.strip("[]\"',")
    return last in COMMAND_WORDS or last in INTERPRETERS


@dataclass(frozen=True)
class Discover:
    start: str          # relativo a ROOT
    pattern: str
    modules: tuple[str, ...] = ()   # `python3 -m unittest mod1 mod2`


def parse_unittest(line: str) -> list[Discover]:
    """`python3 -m unittest [discover] ...` -> qué carga unittest."""
    found = []
    for match in DISCOVER_RE.finditer(line):
        try:
            args = shlex.split(match.group("args"))
        except ValueError:
            args = match.group("args").split()
        args = [a for a in args if not re.match(r"\d?>", a)]
        if "discover" not in args[:1]:
            modules = tuple(a for a in args if not a.startswith("-"))
            found.append(Discover("", "", modules) if modules else Discover(".", "test*.py"))
            continue
        args = args[1:]
        start, pattern, positional, index = ".", "test*.py", [], 0
        while index < len(args):
            arg = args[index]
            if arg in {"-s", "--start-directory"} and index + 1 < len(args):
                start, index = args[index + 1], index + 2
            elif arg in {"-p", "--pattern"} and index + 1 < len(args):
                pattern, index = args[index + 1], index + 2
            elif arg in {"-t", "--top-level-directory", "-k"} and index + 1 < len(args):
                index += 2
            elif arg.startswith("-"):
                index += 1
            else:
                positional.append(arg)
                index += 1
        start = (positional[0] if positional else start).rstrip("/") or "."
        pattern = positional[1] if len(positional) > 1 else pattern
        found.append(Discover(start[2:] if start.startswith("./") else start, pattern))
    return found


def discovered_files(item: Discover) -> set[str]:
    """Ficheros que unittest importa para `item` (como hace TestLoader:
    solo paquetes con __init__.py, nombre de módulo válido y patrón)."""
    if item.modules:
        files = set()
        for module in item.modules:
            path = ROOT / (module.replace(".", "/") + ".py")
            if path.is_file():
                files.add(testlib.rel(path))
        return files
    start = (ROOT / item.start).resolve()
    files = set()
    for path in testlib.repo_files():
        if path.suffix != ".py" or not re.fullmatch(r"[_a-z]\w*\.py", path.name, re.IGNORECASE):
            continue
        try:
            inner = path.relative_to(start)
        except ValueError:
            continue
        if not fnmatch.fnmatch(path.name, item.pattern):
            continue
        if all((start / Path(*inner.parts[:k]) / "__init__.py").exists() for k in range(1, len(inner.parts))):
            files.add(testlib.rel(path))
    return files


def public_commands() -> list[str]:
    text = read("churros")
    match = re.search(r"^PUBLIC_COMMANDS=\((.*?)^\)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    return [word for line in match.group(1).splitlines()
            for word in line.split("#", 1)[0].split()]


def is_shell(path: Path) -> bool:
    return path.suffix == ".sh" or path.name == "churros" or testlib.shebang(path) in testlib.SHEBANG_SHELLS


def edges_from_text(text: str, *, python: bool = False) -> set[str]:
    """Ficheros del repo que ejecuta este texto (shell o Python)."""
    targets: set[str] = set()
    public = set(public_commands())
    if python:
        # Solo líneas que lanzan un proceso: una mención en un docstring no cuenta.
        call = re.compile(r"\b(?:run|Popen|check_output|check_call|call)\(|subprocess\.")
        for line in filter(call.search, text.splitlines()):
            for match in re.finditer(r"""["'](?:\./)?((?:scripts|tests)/[\w./-]+)["']""", line):
                if (ROOT / match.group(1)).is_file():
                    targets.add(match.group(1))
            for item in parse_unittest(line):
                targets |= discovered_files(item)
        return targets
    for line in code_lines(text):
        for match in PATH_RE.finditer(line):
            if not in_command_position(line[:match.start("pre")]):
                continue
            path = match.group("path")
            if "*" in path:
                targets.update(testlib.rel(p) for p in ROOT.glob(path) if p.is_file())
            elif (ROOT / path).is_file():
                targets.add(path)
        for match in CHURROS_RE.finditer(line):
            before = line[:match.start("pre")]
            if before and not before[-1].isspace() and before[-1] not in ";&|(`":
                continue
            if in_command_position(before) and match.group("cmd") in public:
                targets.add(f"scripts/cli/{match.group('cmd')}.sh")
        for item in parse_unittest(line):
            targets |= discovered_files(item)
    return targets


@lru_cache(maxsize=None)
def file_edges(rel_path: str) -> frozenset[str]:
    path = ROOT / rel_path
    if not path.is_file() or path.resolve() == THIS_FILE:
        return frozenset()
    if path.suffix == ".py":
        return frozenset(edges_from_text(testlib.read_text(path), python=True))
    if is_shell(path):
        return frozenset(edges_from_text(testlib.read_text(path)))
    return frozenset()


def reach(text: str) -> set[str]:
    """Cierre transitivo: todo lo que acaba ejecutando un paso de workflow."""
    seen: set[str] = set()
    queue = list(edges_from_text(text))
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(file_edges(current) - seen)
    return seen


def reach_from_file(rel_path: str) -> set[str]:
    seen = {rel_path}
    queue = list(file_edges(rel_path))
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(file_edges(current) - seen)
    return seen


# ------------------------------------------------------------------- workflows

def yaml_strict_loader(yaml):
    """SafeLoader que rechaza claves repetidas, como el parser de GitHub
    Actions ("'run' is already defined"); PyYAML se quedaría con la última."""
    class Loader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        loader.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"clave repetida {key!r}", key_node.start_mark)
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
    return Loader


@dataclass(frozen=True)
class Step:
    workflow: str
    job_id: str
    index: int
    data: dict

    @property
    def run(self) -> str:
        value = self.data.get("run")
        return value if isinstance(value, str) else ""

    @property
    def label(self) -> str:
        return f"{self.workflow}:{self.job_id}:{self.data.get('name') or self.index}"


@lru_cache(maxsize=None)
def workflows() -> tuple[tuple[str, dict], ...]:
    import yaml
    loader = yaml_strict_loader(yaml)
    found = []
    for path in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        try:
            data = yaml.load(testlib.read_text(path), Loader=loader)
        except yaml.YAMLError as error:
            raise AssertionError(f"{testlib.rel(path)} no es un workflow válido: {error}")
        if not isinstance(data, dict):
            raise AssertionError(f"{testlib.rel(path)} no es un mapa YAML")
        found.append((path.name, data))
    return tuple(found)


def jobs(data: dict) -> dict:
    value = data.get("jobs")
    return value if isinstance(value, dict) else {}


def triggers(data: dict) -> dict:
    """`on:` normalizado a {evento: config}. PyYAML (YAML 1.1) lee `on` como True."""
    value = data.get("on", data.get(True))
    if isinstance(value, str):
        return {value: None}
    if isinstance(value, list):
        return {item: None for item in value}
    return value if isinstance(value, dict) else {}


def steps() -> list[Step]:
    found = []
    for name, data in workflows():
        for job_id, job in jobs(data).items():
            for index, step in enumerate(job.get("steps") or [], 1):
                if isinstance(step, dict):
                    found.append(Step(name, job_id, index, step))
    return found


@lru_cache(maxsize=None)
def step_reach(workflow: str, job_id: str, index: int) -> frozenset[str]:
    for step in steps():
        if (step.workflow, step.job_id, step.index) == (workflow, job_id, index):
            return frozenset(reach(step.run))
    return frozenset()


def reached(step: Step) -> frozenset[str]:
    return step_reach(step.workflow, step.job_id, step.index)


@lru_cache(maxsize=None)
def entry_points() -> frozenset[str]:
    """Puntos de entrada de prueba: scripts/test-*, tests/**/test_*.py|sh y
    los scripts de tests/ que se ejecutan solos (`if __name__ == "__main__"`,
    p. ej. tests/iso/check_iso.py)."""
    names = set()
    for path in testlib.repo_files():
        rel = testlib.rel(path)
        if re.fullmatch(r"scripts/test-[^/]+", rel):
            names.add(rel)
        elif rel.startswith("tests/") and re.fullmatch(r"test[_-][\w-]*\.(?:py|sh)", path.name):
            names.add(rel)
        elif (rel.startswith("tests/") and not rel.startswith("tests/static/") and path.suffix == ".py"
              and re.search(r"^if __name__ == [\"']__main__[\"']", testlib.read_text(path), re.MULTILINE)):
            names.add(rel)
    return frozenset(names)


def runs_cargo_test(rel_path: str) -> bool:
    return any(re.search(r"\bcargo\s+test\b", line) for line in code_lines(read(rel_path)))


def is_test_step(step: Step) -> bool:
    text = "\n".join(code_lines(step.run))
    if re.search(r"\bcargo\s+test\b|-m\s+unittest\b|scripts/test-", text):
        return True
    hit = reached(step)
    return bool(hit & (entry_points() | {CHECK_SH})) or any(
        runs_cargo_test(p) for p in hit if is_shell(ROOT / p))


# ---------------------------------------------------------------- comprobaciones

class DispatcherTest(unittest.TestCase):
    """`./churros`: superficie pública, ayuda y helpers."""

    def test_public_commands_have_scripts(self):
        commands = public_commands()
        self.assertTrue(commands, "no encuentro PUBLIC_COMMANDS=( ... ) en churros")
        missing = [c for c in commands if not (ROOT / f"scripts/cli/{c}.sh").is_file()]
        self.assertFalse(missing, f"comandos públicos sin scripts/cli/<cmd>.sh: {missing}")

    def test_help_lists_exactly_public_commands(self):
        result = testlib.run(["bash", "churros", "--help"], timeout=30)
        self.assertEqual(result.returncode, 0, f"./churros --help falla:\n{result.stdout}")
        listed = set(re.findall(r"^  ([a-z][\w-]*) {2,}\S", result.stdout, re.MULTILINE))
        public = set(public_commands())
        self.assertFalse(public - listed, f"comandos públicos que ./churros --help no lista: {sorted(public - listed)}")
        self.assertFalse(listed - public, f"./churros --help lista comandos que no son públicos: {sorted(listed - public)}")

    def test_unknown_command_fails(self):
        result = testlib.run(["bash", "churros", "no-existe-este-comando"], timeout=30)
        self.assertNotEqual(result.returncode, 0,
                            "./churros <comando desconocido> sale con 0: un typo en el CI pasaría en verde")

    def test_cli_scripts_are_commands_or_documented_helpers(self):
        public = set(public_commands())
        problems = []
        for path in sorted((ROOT / "scripts/cli").glob("*.sh")):
            if path.stem in public:
                continue
            if path.name not in CLI_HELPERS:
                problems.append(f"{testlib.rel(path)} no es un comando público ni un helper de CLI_HELPERS "
                                "(añádelo a PUBLIC_COMMANDS y a la ayuda, o documenta por qué no lo es)")
        callers = [ROOT / "churros", *sorted((ROOT / "scripts/cli").glob("*.sh"))]
        for helper in CLI_HELPERS:
            if not (ROOT / "scripts/cli" / helper).is_file():
                problems.append(f"CLI_HELPERS nombra scripts/cli/{helper}, que ya no existe")
            elif not any(helper in testlib.read_text(p) for p in callers if p.name != helper):
                problems.append(f"scripts/cli/{helper} no lo usa ningún comando: entrada vieja en CLI_HELPERS")
        self.assertFalse(problems, "\n".join(problems))


class WiringTest(unittest.TestCase):
    """Cada punto de entrada de prueba corre solo, desde un workflow."""

    def setUp(self):
        testlib.require_module(self, "yaml")

    def all_reached(self) -> set[str]:
        hit: set[str] = set()
        for step in steps():
            hit |= reached(step)
        return hit

    def test_test_scripts_run_automatically(self):
        hit = self.all_reached()
        findings = {}
        for name in sorted(entry_points()):
            if name.startswith("tests/static/"):
                continue  # los cubre test_check_sh_runs_static_suite
            if name not in hit:
                category = "test-script" if name.startswith("scripts/") else "test-module"
                findings[f"wiring:{category}:{name}"] = (
                    f"{name} no lo ejecuta ningún workflow (ni check.sh ni ./churros <cmd> desde .github/workflows)")
        testlib.assert_findings(self, "wiring:test-script",
                                {k: v for k, v in findings.items() if k.startswith("wiring:test-script:")})
        testlib.assert_findings(self, "wiring:test-module",
                                {k: v for k, v in findings.items() if k.startswith("wiring:test-module:")})

    def test_ignored_rust_tests_have_wired_runner(self):
        hit = self.all_reached()
        candidates = [p for p in testlib.repo_files()
                      if (p.suffix in {".py", ".sh"} or is_shell(p))
                      and testlib.rel(p).startswith(("scripts/", "tests/")) and p.resolve() != THIS_FILE]
        findings = {}
        for crate in testlib.crates():
            for source in sorted(crate.directory.rglob("*.rs")):
                text = testlib.read_text(source)
                for match in re.finditer(r"#\[ignore\b[^\]]*\]\s*(?:#\[[^\]]*\]\s*)*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", text):
                    function = match.group(1)
                    runners = []
                    for runner in candidates:
                        body = testlib.read_text(runner)
                        if not re.search(r"--(?:include-)?ignored\b", body):
                            continue
                        if crate.name in body or function in body or "--workspace" in body:
                            runners.append(testlib.rel(runner))
                    if not any(r in hit for r in runners):
                        why = (f"su runner ({', '.join(runners)}) no lo lanza ningún workflow" if runners
                               else "ningún script de scripts/ o tests/ lo ejecuta con --include-ignored")
                        findings[f"wiring:ignored-rust:{crate.name}:{function}"] = (
                            f"el test #[ignore] {crate.name}::{function} ({testlib.rel(source)}) no corre nunca: {why}")
        testlib.assert_findings(self, "wiring:ignored-rust", findings)

    def test_rust_tests_run_in_ci(self):
        tested = {c.name for c in testlib.crates()
                  if any("#[test]" in testlib.read_text(s) for s in c.directory.rglob("*.rs"))}
        covered, workspace = set(), False
        for rel in self.all_reached():
            path = ROOT / rel
            if not is_shell(path):
                continue
            text = "\n".join(code_lines(testlib.read_text(path)))
            if not re.search(r"\bcargo\s+test\b", text):
                continue
            workspace |= "--workspace" in text
            covered |= set(re.findall(r"cargo\s+test\b[^\n]*?-p\s+([\w-]+)", text))
        for step in steps():
            text = "\n".join(code_lines(step.run))
            if re.search(r"\bcargo\s+test\b", text):
                workspace |= "--workspace" in text
                covered |= set(re.findall(r"cargo\s+test\b[^\n]*?-p\s+([\w-]+)", text))
        missing = set() if workspace else tested - covered
        self.assertFalse(missing, f"crates con #[test] que ningún workflow prueba con cargo test: {sorted(missing)}")

    def test_static_modules_are_discoverable(self):
        loader = unittest.TestLoader()
        suite = loader.discover(str(ROOT / "tests/static"), pattern=self.static_pattern(), top_level_dir=str(ROOT))
        counts: dict[str, int] = {}
        problems = []

        def walk(item):
            for test in item:
                if isinstance(test, unittest.TestSuite):
                    walk(test)
                elif type(test).__name__ == "_FailedTest":
                    problems.append(f"{test._testMethodName} no se puede importar (unittest lo marca como error)")
                elif type(test).__name__ == "ModuleSkipped":
                    problems.append(f"{test.id()} lanza SkipTest al importar y se salta entero: usa "
                                    "testlib.require_tool/require_module dentro de cada prueba")
                else:
                    counts[type(test).__module__] = counts.get(type(test).__module__, 0) + 1
        walk(suite)
        for path in sorted(testlib.repo_files()):
            rel = testlib.rel(path)
            if not rel.startswith("tests/static/") or path.suffix != ".py" or path.name == "__init__.py":
                continue
            module = rel[:-3].replace("/", ".")
            defines_tests = re.search(r"^class\s+\w+\(.*TestCase\)", testlib.read_text(path), re.MULTILINE)
            if fnmatch.fnmatch(path.name, self.static_pattern()):
                if module not in counts and not any(module in p for p in problems):
                    problems.append(f"{rel} no tiene ninguna prueba que unittest descubra (sin TestCase o sin __init__.py)")
            elif defines_tests:
                problems.append(f"{rel} define un TestCase pero su nombre no casa con '{self.static_pattern()}': "
                                "unittest discover no lo ejecuta nunca")
        self.assertFalse(problems, "\n".join(problems))

    @staticmethod
    def static_suite_runs() -> list[tuple[Stmt, Discover]]:
        runs = []
        for stmt in shell_statements(read(CHECK_SH)):
            for item in parse_unittest(strip_messages(stmt.text)):
                start = (ROOT / item.start).resolve() if item.start else None
                if start and (start == ROOT / "tests/static" or (ROOT / "tests/static").is_relative_to(start)):
                    runs.append((stmt, item))
        return runs

    def static_pattern(self) -> str:
        runs = self.static_suite_runs()
        return runs[0][1].pattern if runs else "test*.py"

    def test_check_sh_runs_static_suite(self):
        runs = self.static_suite_runs()
        self.assertTrue(runs, f"{CHECK_SH} no lanza `python3 -m unittest discover -s tests/static`: "
                              "las pruebas de tests/static no corren en ./churros check ni en el CI")
        found = set()
        for _, item in runs:
            found |= discovered_files(item)
        modules = {testlib.rel(p) for p in testlib.repo_files()
                   if testlib.rel(p).startswith("tests/static/") and p.name.startswith("test") and p.suffix == ".py"}
        self.assertFalse(modules - found, f"módulos de tests/static que el discover de check.sh no encuentra: "
                                          f"{sorted(modules - found)}")

    def test_check_runs_on_every_pull_request(self):
        ok = []
        for step in steps():
            if CHECK_SH not in reached(step):
                continue
            data = dict(workflows())[step.workflow]
            event = triggers(data)
            if "pull_request" not in event:
                continue
            config = event["pull_request"] or {}
            if isinstance(config, dict) and (config.get("paths") or config.get("paths-ignore")):
                continue
            ok.append(step.label)
        self.assertTrue(ok, f"ningún workflow con `pull_request` (sin filtro de paths) ejecuta {CHECK_SH}: "
                            "un PR podría fusionarse sin pasar ./churros check")

    def test_no_disabled_python_tests(self):
        pattern = re.compile(r"@(?:unittest\.)?skip\(|@(?:unittest\.)?expectedFailure\b"
                             r"|skipIf\(\s*True\b|skipUnless\(\s*False\b")
        problems = []
        for path in testlib.repo_files():
            rel = testlib.rel(path)
            if path.suffix != ".py" or path.resolve() == THIS_FILE:
                continue
            if not (rel.startswith("tests/") or rel.startswith("scripts/test-")):
                continue
            for lineno, line in enumerate(testlib.read_text(path).splitlines(), 1):
                if pattern.search(line) and not line.lstrip().startswith("#"):
                    problems.append(f"{rel}:{lineno}: {line.strip()}")
        self.assertFalse(problems, "pruebas desactivadas sin condición (skip/expectedFailure); usa un skip "
                                   "condicionado o testlib.require_tool:\n" + "\n".join(problems))


class AntiWeakeningTest(unittest.TestCase):
    """check.sh y los workflows no pueden convertir un fallo en verde."""

    def is_test_call(self, text: str) -> bool:
        line = strip_messages(text)
        if re.search(r"-m\s+unittest\b|\bcargo\s+test\b|\./churros\s+(?:check|test|rust)\b", line):
            return True
        runners = ("scripts/test-", "tests/", "scripts/cli/check.sh", "scripts/cli/test.sh", "scripts/cli/rust.sh")
        return any(in_command_position(line[:m.start("pre")]) and m.group("path").startswith(runners)
                   for m in PATH_RE.finditer(line))

    def setUp(self):
        self.stmts = shell_statements(read(CHECK_SH))

    @staticmethod
    def count_if(text: str) -> int:
        return len(re.findall(r"(?:^|[;&|]\s*|\bthen\s+|\belse\s+|\bdo\s+)if\s", text.strip()))

    @staticmethod
    def count_fi(text: str) -> int:
        return len(re.findall(r"(?:^|;)\s*fi\b", text.strip()))

    def branches(self, k: int) -> tuple[bool, bool]:
        """(¿fail en la rama then?, ¿fail en else/elif?) del if que abre stmts[k]."""
        depth, branch, found = 0, "then", {"then": False, "else": False}
        for stmt in self.stmts[k + 1:]:
            text = stmt.text.strip()
            if depth == 0 and re.match(r"(?:else|elif)\b", text):
                branch = "else"
            if depth == 0 and re.match(r"fi\b", text):
                break
            if re.search(r"(?:^|[;&|{]\s*|\bthen\s+|\belse\s+)fail\b", text):
                found[branch] = True
            depth += self.count_if(text) - self.count_fi(text)
        return found["then"], found["else"]

    def guarded(self, k: int) -> bool:
        text = self.stmts[k].text
        if re.search(r"\|\|\s*\{?\s*fail\b", text):
            return True
        match = re.match(r"\s*(?:if|elif)\s+(!\s*)?(.*?);\s*then\b(.*)$", text)
        if match:
            negated, rest = bool(match.group(1)), match.group(3)
            if re.search(r"\bfi\s*$", rest):
                then_part, _, else_part = rest.partition("else")
                return bool(re.search(r"\bfail\b", then_part if negated else else_part))
            then_fail, else_fail = self.branches(k)
            return then_fail if negated else else_fail
        # Invocación suelta (`out=$(...)`, `rc=$?`): vale si el if siguiente
        # mira $? o esa variable y alguna rama llama a fail.
        names = set(re.findall(r"(\w+)=", text))
        for j in range(k + 1, min(k + 4, len(self.stmts))):
            following = self.stmts[j].text
            names |= set(re.findall(r"(\w+)=\$\?", following))
            if re.match(r"\s*if\b", following) and (
                    "$?" in following or any(f"${n}" in following or f"${{{n}" in following for n in names)):
                then_fail, else_fail = self.branches(j)
                single = re.search(r"\bfail\b", following)
                return then_fail or else_fail or bool(single)
        return False

    def test_check_sh_test_invocations_reach_fail(self):
        problems = []
        for k, stmt in enumerate(self.stmts):
            if self.is_test_call(stmt.text) and not self.guarded(k):
                problems.append(f"{CHECK_SH}:{stmt.lineno}: {stmt.text.strip()}")
        self.assertFalse(problems, "llamadas a pruebas cuyo fallo no llega a fail() (se ignoran en silencio):\n"
                                   + "\n".join(problems))

    def test_check_sh_has_no_neutralisers(self):
        problems = []
        tail_start = self.summary_index()
        fail_defs = [s for s in self.stmts if re.match(r"\s*(?:function\s+)?fail\s*(?:\(\s*\))?\s*\{", s.text)]
        if len(fail_defs) != 1:
            problems.append(f"fail() se define {len(fail_defs)} veces (debe ser una): "
                            + ", ".join(str(s.lineno) for s in fail_defs))
        first_init = next((s for s in self.stmts if re.fullmatch(r"FAILURES=0\s*", s.text)), None)
        for index, stmt in enumerate(self.stmts):
            text = stmt.text
            where = f"{CHECK_SH}:{stmt.lineno}: {text.strip()}"
            if re.search(r"(?:^|[;&|]\s*|\bthen\s+|\belse\s+|\bdo\s+)(?:if|elif)\s+(?:true|:|!\s*false)\s*;", text.strip()):
                problems.append(f"condición constante (`if true`): {where}")
            if self.is_test_call(text) and re.search(r"\|\|\s*(?:true|:|exit\s+0|return\s+0)\b", text):
                problems.append(f"`|| true` tras una prueba: {where}")
            if re.search(r"\balias\s+fail=", text):
                problems.append(f"alias de fail: {where}")
            if (re.search(r"\bFAILURES\s*[-+]?=|\(\(\s*FAILURES|\blet\s+FAILURES|\bunset\s+FAILURES", text)
                    and stmt is not first_init and stmt not in fail_defs):
                problems.append(f"FAILURES se toca fuera de su inicialización y de fail(): {where}")
            if tail_start is not None and index < tail_start and stmt.column0 and re.match(r"exit(?:\s+0)?\s*(?:;|$)", text):
                problems.append(f"`exit` antes del resumen final: {where}")
        self.assertFalse(problems, "check.sh tiene construcciones que anulan comprobaciones:\n" + "\n".join(problems))

    def summary_index(self) -> int | None:
        tops = [i for i, s in enumerate(self.stmts) if s.column0 and re.match(r"if\b", s.text)]
        return tops[-1] if tops else None

    def test_check_sh_exit_status(self):
        lines = read(CHECK_SH).splitlines()
        index = self.summary_index()
        self.assertIsNotNone(index, "check.sh no termina en un if de resumen")
        start = self.stmts[index]
        self.assertIn("FAILURES", start.text, f"el último if de nivel superior de {CHECK_SH} "
                                              f"(línea {start.lineno}) no mira FAILURES: el código de salida no depende de los fallos")
        tail = "\n".join(lines[start.lineno - 1:])
        fail_def = next((s.text for s in self.stmts if re.match(r"(?:function\s+)?fail\s*(?:\(\s*\))?\s*\{", s.text)), "")
        if fail_def and not fail_def.rstrip().endswith("}"):
            first = next(s.lineno for s in self.stmts if s.text == fail_def)
            end = next(i for i in range(first, len(lines)) if lines[i].startswith("}"))
            fail_def = "\n".join(lines[first - 1:end + 1])
        self.assertTrue(fail_def, f"{CHECK_SH} no define fail()")
        results = {}
        for calls in (0, 1, 3):
            script = "set -uo pipefail\n" + fail_def + "\nFAILURES=0\nNOTICES=0\n" + \
                     "".join("fail 'prueba' >/dev/null\n" for _ in range(calls)) + tail + "\n"
            results[calls] = testlib.run(["bash", "-c", script], timeout=30).returncode
        self.assertEqual(results[0], 0, f"{CHECK_SH} sale con {results[0]} sin ningún fallo")
        self.assertNotEqual(results[1], 0, f"{CHECK_SH} sale con 0 tras un fail(): el CI no vería el fallo")
        self.assertNotEqual(results[3], 0, f"{CHECK_SH} sale con 0 tras tres fail()")

    def test_workflows_do_not_mask_tests(self):
        testlib.require_module(self, "yaml")
        problems = []
        test_jobs = {(s.workflow, s.job_id) for s in steps() if is_test_step(s)}
        for name, data in workflows():
            for job_id, job in jobs(data).items():
                if (name, job_id) in test_jobs:
                    if job.get("continue-on-error") not in (None, False):
                        problems.append(f"{name}:{job_id}: continue-on-error en un job que ejecuta pruebas")
                    if constant_false(job.get("if")):
                        problems.append(f"{name}:{job_id}: `if: {job.get('if')}` desactiva un job de pruebas")
        for step in steps():
            if not is_test_step(step):
                continue
            if step.data.get("continue-on-error") not in (None, False):
                problems.append(f"{step.label}: continue-on-error en un paso que ejecuta pruebas")
            if constant_false(step.data.get("if")):
                problems.append(f"{step.label}: `if: {step.data.get('if')}` desactiva el paso")
            for line in code_lines(step.run):
                if self.is_test_call(line) or re.search(r"\./churros\s+(?:check|test|rust)\b", line):
                    if re.search(r"\|\|\s*(?:true|:|exit\s+0)\b", line):
                        problems.append(f"{step.label}: `|| true` tras una prueba: {line.strip()}")
        # Los scripts que lanzan pruebas (test.sh, rust.sh...): mismas trampas
        # que en check.sh, que tiene su propia prueba más estricta.
        runners = {p for s in steps() for p in reached(s) if p != CHECK_SH and is_shell(ROOT / p)}
        for rel in sorted(runners):
            stmts = shell_statements(read(rel))
            if not any(self.is_test_call(s.text) for s in stmts):
                continue
            for stmt in stmts:
                if self.is_test_call(stmt.text) and re.search(r"\|\|\s*(?:true|:|exit\s+0)\b", stmt.text):
                    problems.append(f"{rel}:{stmt.lineno}: `|| true` tras una prueba: {stmt.text.strip()}")
                if re.match(r"\s*(?:if|elif)\s+(?:true|:|!\s*false)\s*;", stmt.text):
                    problems.append(f"{rel}:{stmt.lineno}: condición constante: {stmt.text.strip()}")
        self.assertFalse(problems, "workflows o scripts que ocultan el fallo de una prueba:\n" + "\n".join(problems))

    def test_strict_mode_not_disabled(self):
        testlib.require_module(self, "yaml")
        problems = []

        def check_env(where: str, env) -> None:
            if not isinstance(env, dict):
                return
            for key, value in env.items():
                text = str(value).strip().lower() if value is not None else ""
                if key == "CHURROS_STRICT" and text != "1":
                    problems.append(f"{where}: env CHURROS_STRICT={value!r} (tiene que ser 1)")
                if key == "CI" and text != "true":
                    problems.append(f"{where}: env CI={value!r} (GitHub pone true; no se pisa)")

        def check_text(where: str, text: str) -> None:
            for line in code_lines(text):
                for var, value in re.findall(r"(?<![\w${])(CHURROS_STRICT|CI)=(\S*)", line):
                    value = value.strip("'\";")
                    if value.startswith("$"):
                        continue
                    if (var == "CHURROS_STRICT" and value != "1") or (var == "CI" and value.lower() != "true"):
                        problems.append(f"{where}: {line.strip()}")
                if re.search(r"\bunset\b[^;&|]*\b(?:CI|CHURROS_STRICT)\b|\benv\s+(?:-\S+\s+)*-u\s*(?:CI|CHURROS_STRICT)\b", line):
                    problems.append(f"{where}: {line.strip()}")

        runners: set[str] = set()
        for name, data in workflows():
            check_env(name, data.get("env"))
            for job_id, job in jobs(data).items():
                check_env(f"{name}:{job_id}", job.get("env"))
                if isinstance(job.get("container"), dict):
                    check_env(f"{name}:{job_id}:container", job["container"].get("env"))
        for step in steps():
            check_env(step.label, step.data.get("env"))
            check_text(step.label, step.run)
            runners |= {p for p in reached(step) if is_shell(ROOT / p)}
        for rel in sorted(runners):
            check_text(rel, read(rel))
        # Las pruebas de contenedor no heredan CI=true del runner: si un
        # workflow las lanza a través de scripts/lib/container.sh, el modo
        # estricto tiene que entrar en el contenedor.
        def runs_container_suite(rel: str) -> bool:
            return any(item.start.startswith("tests/container") for line in code_lines(read(rel))
                       for item in parse_unittest(line))

        for step in steps():
            hit = reached(step)
            shells = [rel for rel in hit if is_shell(ROOT / rel)]
            if "scripts/lib/container.sh" in hit and any(map(runs_container_suite, shells)):
                forwards = any(re.search(r"container_run\b.*\bCHURROS_STRICT\b", line)
                               or (rel == "scripts/lib/container.sh" and "CHURROS_STRICT" in line)
                               for rel in shells for line in code_lines(read(rel)))
                if not forwards:
                    problems.append(f"{step.label}: lanza tests/container en el contenedor sin pasarle CHURROS_STRICT "
                                    "(container_run -e CHURROS_STRICT=1): una herramienta que falte sería un SKIP")
        self.assertFalse(problems, "el modo estricto se desactiva en el CI:\n" + "\n".join(problems))


def constant_false(value) -> bool:
    if value is False or value == 0:
        return True
    if isinstance(value, str):
        return re.fullmatch(r"\s*(?:\$\{\{\s*)?(?:false|0)(?:\s*\}\})?\s*", value) is not None
    return False


class WorkflowHygieneTest(unittest.TestCase):
    """Permisos, timeouts, concurrency y versiones de las acciones."""

    def setUp(self):
        testlib.require_module(self, "yaml")

    def test_permissions(self):
        findings = {}
        for name, data in workflows():
            every_job = jobs(data) and all("permissions" in job for job in jobs(data).values())
            if "permissions" not in data and not every_job:
                findings[f"workflow:permissions:{name}"] = (
                    f"{name} no declara `permissions:`: el GITHUB_TOKEN recibe los permisos por defecto del repo")
        testlib.assert_findings(self, "workflow:permissions", findings)

    def test_timeouts(self):
        findings = {}
        for name, data in workflows():
            for job_id, job in jobs(data).items():
                if "uses" in job:
                    continue  # un workflow reutilizable no admite timeout-minutes
                if "timeout-minutes" not in job:
                    findings[f"workflow:timeout:{name}:{job_id}"] = (
                        f"{name}: el job '{job_id}' no tiene timeout-minutes (GitHub corta a las 6 h)")
        testlib.assert_findings(self, "workflow:timeout", findings)

    def test_heavy_pr_jobs_have_concurrency(self):
        findings = {}
        for name, data in workflows():
            if not {"pull_request", "pull_request_target"} & set(triggers(data)):
                continue
            for job_id, job in jobs(data).items():
                texts = [s.get("run", "") or "" for s in job.get("steps") or [] if isinstance(s, dict)]
                texts += [s.get("uses", "") or "" for s in job.get("steps") or [] if isinstance(s, dict)]
                heavy = any(HEAVY_RE.search("\n".join(code_lines(t))) for t in texts)
                if heavy and "concurrency" not in data and "concurrency" not in job:
                    findings[f"workflow:concurrency:{name}:{job_id}"] = (
                        f"{name}: el job pesado '{job_id}' corre en PR sin `concurrency`: cada push apila otra ejecución")
        testlib.assert_findings(self, "workflow:concurrency", findings)

    def test_action_refs(self):
        findings = {}
        for name, data in workflows():
            uses = [job.get("uses") for job in jobs(data).values()]
            for job in jobs(data).values():
                uses += [s.get("uses") for s in job.get("steps") or [] if isinstance(s, dict)]
            for ref in filter(None, uses):
                problem = action_ref_problem(str(ref))
                if problem:
                    findings[f"workflow:action-ref:{name}:{ref}"] = f"{name}: `uses: {ref}`: {problem}"
        testlib.assert_findings(self, "workflow:action-ref", findings)


def action_ref_problem(uses: str) -> str | None:
    if uses.startswith("./"):
        return None
    if uses.startswith("docker://"):
        image = uses[len("docker://"):]
        last = image.rsplit("/", 1)[-1]
        if "@sha256:" in image or (":" in last and not last.endswith(":latest")):
            return None
        return "imagen docker sin etiqueta fija"
    action, _, ref = uses.partition("@")
    if not ref:
        return "sin versión (@vN o SHA)"
    if re.fullmatch(r"[0-9a-f]{40}|v\d+(?:\.\d+){0,2}", ref):
        return None
    allowed = ACTION_REF_EXCEPTIONS.get(action)
    if allowed and re.fullmatch(allowed, ref):
        return None
    return f"'{ref}' no es una versión (vN, vN.M.P) ni un SHA: la acción cambia sin que nadie lo revise"


# ----------------------------------------------------------------------- docs

def fenced_lines(text: str) -> list[str]:
    return [line for block in re.findall(r"^```[^\n]*\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
            for line in block.splitlines()]


def sentences(text: str) -> list[str]:
    text = re.sub(r"^```.*?^```", "\n\n", text, flags=re.MULTILINE | re.DOTALL)
    found = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        found.extend(re.split(r"(?<=[.!?])\s+(?=[A-Z¿¡`(])", paragraph))
    return found


def doc_files() -> list[Path]:
    """Markdown del repo, sin el diario (habla de ficheros que ya no existen
    a propósito)."""
    return [p for p in testlib.repo_files() if p.suffix == ".md" and "devlog" not in p.name.lower()]


@lru_cache(maxsize=None)
def calamares_settings() -> dict:
    import yaml
    return yaml.safe_load(read("installer/calamares/settings.conf")) or {}


def calamares_instances() -> set[str]:
    return {str(item.get("id")) for item in calamares_settings().get("instances") or [] if isinstance(item, dict)}


def calamares_sequence() -> set[str]:
    modules = set()
    for step in calamares_settings().get("sequence") or []:
        for names in (step or {}).values():
            modules.update(str(n) for n in names or [])
    return modules


def accepted_editions() -> set[str]:
    """Ediciones de testlib.EDITIONS más las que valida build.sh."""
    names = {item.name for item in testlib.EDITIONS}
    for line in read("scripts/cli/build.sh").splitlines():
        if re.fullmatch(r'\s*if\s+(?:\[\s+"\$EDITION"\s+!=\s+"?\w+"?\s+\]\s*(?:&&\s*)?)+;\s*then\s*', line):
            names |= set(re.findall(r'"\$EDITION"\s+!=\s+"?(\w+)"?', line))
            break
    return names


def check_sh_mentions(word: str) -> bool:
    return any(word in line for line in code_lines(read(CHECK_SH)))


def rust_has_tests() -> bool:
    return any("#[test]" in testlib.read_text(s) for c in testlib.crates() for s in c.directory.rglob("*.rs"))


def customize_runs_at_build() -> bool:
    # build.sh deja el script en airootfs/root/ y mkarchiso lo ejecuta en
    # arch-chroot al construir y lo borra (_make_customize_airootfs).
    return "archiso/airootfs/root/customize_airootfs.sh" in "\n".join(code_lines(read("scripts/cli/build.sh")))


# Afirmaciones que fueron ciertas y dejaron de serlo. Cada entrada:
# (id, regex de la línea, condición que la hace falsa, por qué). Una
# afirmación falsa nueva se añade aquí.
FALSE_CLAIMS = (
    ("no-unit-tests", r"There are no unit tests yet", rust_has_tests,
     "rust/ tiene #[test] (y tests/ pruebas unittest)"),
    ("customize-live-boot", r"(?i)customize_airootfs\.sh.*\b(?:at live boot|arranque (?:del )?live)\b"
                            r"|\b(?:at live boot|arranque (?:del )?live)\b.*customize_airootfs\.sh",
     customize_runs_at_build,
     "mkarchiso lo ejecuta en arch-chroot al construir la ISO y lo borra; no corre al arrancar el Live"),
    ("netinstall-check", r"(?i)(?:AUR extras|extras AUR|paquetes de `?scripts/build-aur\.sh`?).{0,80}`?netinstall\.yaml",
     lambda: not check_sh_mentions("netinstall"),
     "check.sh ya no comprueba netinstall.yaml"),
    ("netinstall-resolves", r"(?i)`?netinstall`?\s+resolves",
     lambda: "netinstall" not in calamares_sequence(),
     "netinstall no está en la secuencia de settings.conf"),
    ("grub-theme-live-boot", r"(?i)deployed to `?/usr/share/churros/grub-theme/?`?\)? at live boot",
     lambda: customize_runs_at_build() and "/usr/share/churros/grub-theme" in read("branding/customize_airootfs.sh"),
     "customize_airootfs.sh lo copia a /usr/share/churros/grub-theme/ al construir la ISO, no al arrancar"),
)


class DocsDriftTest(unittest.TestCase):
    """AGENTS.md lo lee cada agente: lo que dice tiene que ser verdad."""

    def test_agents_md_lists_public_commands(self):
        listed = {m.group(1) for line in fenced_lines(read("AGENTS.md"))
                  for m in [re.match(r"\s*\./churros\s+([a-z][\w-]*)", line)] if m}
        findings = {f"docs:agents-command:{c}": f"AGENTS.md no lista `./churros {c}` en sus bloques de comandos"
                    for c in public_commands() if c not in listed}
        testlib.assert_findings(self, "docs:agents-command", findings)

    def test_docs_name_only_public_commands(self):
        public = set(public_commands())
        findings = {}
        for rel in ("AGENTS.md", ".github/PULL_REQUEST_TEMPLATE.md"):
            if not (ROOT / rel).is_file():
                continue
            for command in set(re.findall(r"\./churros\s+([a-z][\w-]*)", read(rel))) - public:
                findings[f"docs:unknown-command:{rel}:{command}"] = (
                    f"{rel} nombra `./churros {command}`, que no está en PUBLIC_COMMANDS")
        testlib.assert_findings(self, "docs:unknown-command", findings)

    def test_pr_template_asks_for_static_checks(self):
        template = ROOT / ".github/PULL_REQUEST_TEMPLATE.md"
        if not template.is_file():
            self.skipTest("no hay .github/PULL_REQUEST_TEMPLATE.md")
        commands = set(re.findall(r"\./churros\s+([a-z][\w-]*)", testlib.read_text(template)))
        runs_check = [c for c in commands & set(public_commands())
                      if CHECK_SH in reach_from_file(f"scripts/cli/{c}.sh")]
        self.assertTrue(runs_check, "la plantilla de PR no pide ningún comando que ejecute scripts/cli/check.sh")

    def test_cli_md_documents_public_commands(self):
        headings = set(re.findall(r"^##\s+([a-z][\w-]*)\s*$", read("docs/cli.md"), re.MULTILINE))
        findings = {f"docs:cli-command:{c}": f"docs/cli.md no tiene sección `## {c}`"
                    for c in public_commands() if c not in headings}
        testlib.assert_findings(self, "docs:cli-command", findings)

    def test_docs_mention_every_edition(self):
        findings = {}
        for rel in ("AGENTS.md", "docs/cli.md"):
            text = read(rel)
            for name in sorted(accepted_editions()):
                pattern = rf"(?i)--edition[ =]{name}\b|\b{name} edition\b|edici[oó]n {name}\b"
                if not re.search(pattern, text):
                    findings[f"docs:edition:{rel}:{name}"] = (
                        f"{rel} no menciona la edición '{name}' que acepta build.sh (--edition {name})")
        testlib.assert_findings(self, "docs:edition", findings)

    def test_test_script_claims(self):
        testlib.require_module(self, "yaml")
        from_check = reach_from_file(CHECK_SH)
        findings = {}
        name_re = r"(?:scripts/test-[\w-]+\.(?:py|js|sh)|tests/[\w/]+\.py)\b"
        for path in doc_files():
            rel = testlib.rel(path)
            for name in sorted(set(re.findall(name_re, testlib.read_text(path)))):
                if not (ROOT / name).is_file():
                    findings[f"docs:test-claim:{rel}:{name}:missing"] = f"{rel} nombra {name}, que no existe"
        for sentence in sentences(read("AGENTS.md")):
            names = set(re.findall(name_re, sentence))
            if not names:
                continue
            claims_check = re.search(r"\./churros check\b|scripts/cli/check\.sh", sentence)
            claimed_workflows = {w for w in re.findall(r"`(?:\.github/workflows/)?([\w.-]+\.ya?ml)`", sentence)
                                 if (WORKFLOWS_DIR / w).is_file()}
            for name in sorted(names):
                sources = []
                if claims_check:
                    sources.append(name in from_check)
                for workflow in claimed_workflows:
                    sources.append(any(name in reached(s) for s in steps() if s.workflow == workflow))
                if sources and not any(sources):
                    where = "./churros check" if claims_check else ", ".join(sorted(claimed_workflows))
                    findings[f"docs:test-claim:AGENTS.md:{name}"] = (
                        f"AGENTS.md dice que {where} ejecuta {name}, pero no lo ejecuta")
        testlib.assert_findings(self, "docs:test-claim", findings)

    def test_known_false_claims(self):
        testlib.require_module(self, "yaml")
        findings = {}
        for claim_id, pattern, is_false, why in FALSE_CLAIMS:
            regex = re.compile(pattern)
            hits = [testlib.rel(p) for p in doc_files()
                    if any(regex.search(line) for line in testlib.read_text(p).splitlines())]
            if hits and is_false():
                for rel in hits:
                    findings[f"docs:false-claim:{claim_id}:{rel}"] = f"{rel} afirma algo falso ({claim_id}): {why}"
        testlib.assert_findings(self, "docs:false-claim", findings)

    def test_installer_docs_match_settings(self):
        testlib.require_module(self, "yaml")
        instances, sequence = calamares_instances(), calamares_sequence()
        self.assertTrue(instances, "no leo ninguna instancia en installer/calamares/settings.conf")
        configs = {p.stem for p in (ROOT / "installer/calamares/modules").rglob("shellprocess-*.conf")}
        findings = {}
        for rel in INSTALLER_DOCS:
            if not (ROOT / rel).is_file():
                continue
            text = read(rel)
            for line in text.splitlines():
                def affirmed(pattern):
                    # "There is **no** `shellprocess@x`": la negación justo antes no afirma que exista.
                    return [m.group(1) for m in re.finditer(pattern, line)
                            if not NEGATION_RE.search(line[max(0, m.start() - 30):m.start()])]
                for name in affirmed(r"shellprocess@([\w-]+)"):
                    if name not in instances:
                        findings[f"docs:installer:instance:{rel}:{name}"] = (
                            f"{rel} nombra shellprocess@{name}, que no está en instances: de settings.conf")
                for name in affirmed(r"`(shellprocess-[\w-]+?)(?:\.conf)?`"):
                    if name not in configs:
                        findings[f"docs:installer:config:{rel}:{name}"] = (
                            f"{rel} nombra {name}.conf, que no existe en installer/calamares/modules/")
                if "`instances:`" in line:
                    listed = set(re.findall(r"`([a-z][\w-]*)`", line.split("`instances:`", 1)[1]))
                    if listed and listed != instances:
                        findings[f"docs:installer:instances-list:{rel}"] = (
                            f"{rel} enumera las instancias {sorted(listed)}; settings.conf tiene {sorted(instances)}")
            for line in fenced_lines(text):
                match = re.match(r"\s*\d+\.\s+(.+?)\s+->", line)
                if not match:
                    continue
                for name in (n.strip() for n in match.group(1).split("/")):
                    if name and not name.startswith("shellprocess@") and name not in sequence:
                        findings[f"docs:installer:sequence:{rel}:{name}"] = (
                            f"{rel} pone '{name}' en la secuencia de instalación, pero no está en sequence: de settings.conf")
        testlib.assert_findings(self, "docs:installer", findings)


# -------------------------------------------------------------- known_issues

class KnownIssuesTest(unittest.TestCase):
    """tests/known_issues.toml: cada entrada se puede rastrear hasta una prueba."""

    def entries(self) -> list:
        if testlib.tomllib is None:
            self.skipTest("tomllib necesita Python >= 3.11")
        if not testlib.KNOWN_ISSUES_FILE.exists():
            return []
        try:
            data = testlib.tomllib.loads(testlib.read_text(testlib.KNOWN_ISSUES_FILE))
        except testlib.tomllib.TOMLDecodeError as error:
            self.fail(f"tests/known_issues.toml no es TOML válido: {error}")
        extra = set(data) - {"issue"}
        self.assertFalse(extra, f"tests/known_issues.toml solo admite [[issue]]; sobra: {sorted(extra)}")
        return data.get("issue", [])

    def test_entries_well_formed(self):
        problems, seen = [], set()
        for number, entry in enumerate(self.entries(), 1):
            key = entry.get("id") if isinstance(entry, dict) else None
            note = entry.get("note") if isinstance(entry, dict) else None
            if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*:\S.*", key):
                problems.append(f"entrada {number}: id {key!r} no es 'categoria:detalle'")
            if not isinstance(note, str) or not note.strip() or note.strip().upper() in {"TODO", "FIXME", "TBD", "XXX"}:
                problems.append(f"entrada {number} ({key}): falta `note` con qué falla y dónde")
            if key in seen:
                problems.append(f"id repetido: {key}")
            seen.add(key)
        self.assertFalse(problems, "\n".join(problems))

    def test_categories_have_a_test(self):
        used, prefixes = set(), set()
        for path in testlib.repo_files():
            rel = testlib.rel(path)
            if not rel.startswith("tests/") or path.suffix != ".py" or path.name == "testlib.py":
                continue
            text = testlib.read_text(path)
            used |= set(re.findall(r"assert_findings\(\s*[\w.]+\s*,\s*f?[\"']([a-z][a-z0-9-]*)", text))
            used |= set(re.findall(r"f?[\"']([a-z][a-z0-9-]*):", text))
            # category = "calamares-yaml"; assert_findings(self, category, ...)
            used |= set(re.findall(r"\bcategory\s*=\s*[\"']([a-z][a-z0-9-]*)[\"']", text))
            # category = f"iso-{edition}" (tests/iso, tests/vm): vale cualquier sufijo.
            prefixes |= set(re.findall(r"\bcategory\s*=\s*f[\"']([a-z][a-z0-9-]*-)\{", text))
        categories = {str(e.get("id", "")).split(":", 1)[0] for e in self.entries() if isinstance(e, dict)}
        orphans = sorted(c for c in categories - used if not c.startswith(tuple(prefixes)))
        self.assertFalse(orphans, f"categorías de tests/known_issues.toml que ninguna prueba de tests/ "
                                  f"produce (entradas que ya no silencian nada): {orphans}")


# ---------------------------------------------------------------- CODEOWNERS

def codeowners_regex(pattern: str):
    """Patrón de CODEOWNERS (sintaxis de .gitignore, sin `!`) a regex."""
    anchored = pattern.startswith("/") or "/" in pattern.strip("/")
    body = pattern.strip("/")
    directory = pattern.endswith("/")
    regex, index = "", 0
    while index < len(body):
        if body.startswith("**/", index):
            regex, index = regex + "(?:.*/)?", index + 3
        elif body.startswith("**", index):
            regex, index = regex + ".*", index + 2
        else:
            char = body[index]
            regex += "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
            index += 1
    last = body.rsplit("/", 1)[-1]
    suffix = "/.*" if directory else ("" if "*" in last else "(?:/.*)?")
    return re.compile(("" if anchored else "(?:.*/)?") + regex + suffix + r"\Z")


class CodeOwnersTest(unittest.TestCase):

    def test_codeowners_cover_guardrails(self):
        # GitHub busca CODEOWNERS en .github/, la raíz y docs/, en ese orden.
        found = next((ROOT / d / "CODEOWNERS" for d in (".github", ".", "docs")
                      if (ROOT / d / "CODEOWNERS").is_file()), None)
        if found is None:
            self.skipTest("no hay CODEOWNERS: nadie revisa por obligación los cambios en las pruebas")
        rules = []
        for line in testlib.read_text(found).splitlines():
            parts = line.split("#", 1)[0].split()
            if parts:
                rules.append((codeowners_regex(parts[0]), [p for p in parts[1:] if "@" in p]))
        guarded = {"scripts/cli/check.sh", "tests/known_issues.toml", "tests/testlib.py",
                   ".github/workflows/ci.yml", testlib.rel(found)}
        guarded |= {testlib.rel(p) for p in testlib.repo_files()
                    if testlib.rel(p).startswith(("tests/", "scripts/test-", ".github/"))}
        orphans = []
        for rel in sorted(guarded):
            owners = None
            for regex, names in rules:
                if regex.match(rel):
                    owners = names
            if not owners:
                orphans.append(rel)
        self.assertFalse(orphans, f"{testlib.rel(found)} no asigna dueño a: {orphans}")


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------ mutaciones

class MutationsTest(unittest.TestCase):
    """tests/mutations/mutations.toml sigue aplicándose al árbol actual.

    El job de mutaciones de ci.yml falla con 'OBSOLETA' si el texto que busca
    una mutación ya no está (o está dos veces). Aquí se ve en segundos y con
    el nombre de la mutación, en el mismo PR que movió ese texto.
    """

    def test_mutations_still_apply(self):
        from tests.mutations import run_mutations
        problems = []
        for mutation in run_mutations.load_mutations():
            _, error = run_mutations.mutated_text(mutation, testlib.ROOT)
            if error:
                problems.append(f"{mutation['name']}: {error}")
        self.assertFalse(problems, "mutaciones obsoletas: el texto que buscan cambió. Actualiza su "
                                   "`find`/`find_re` en tests/mutations/mutations.toml para que siga "
                                   "describiendo la misma regresión:\n  " + "\n  ".join(problems))
