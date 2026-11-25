"""El pipeline de QA visual no puede distinguir "no visual" de "se rompió".

Contexto (auditoría, A7): las cuatro etapas de la QA visual llevan
`continue-on-error: true`. La intención es correcta (no bloquear el merge por
un pipeline que no es check requerido), pero no hay ningún paso que falle
cuando nadie llegó a decidir: un classify.py roto, una clave caducada o una
API caída producen exactamente el mismo resultado observable que "esta PR no
es visual" — cero capturas, cero comentario, todo en verde.

Lo que se exige aquí es que el workflow sepa decir que se degradó. Mientras
no se arregle, está en tests/known_issues.toml.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from tests import testlib

ROOT = Path(__file__).resolve().parents[2]
CLASSIFY = ROOT / ".github/workflows/visual-qa-classify.yml"
GATES = [
    ROOT / ".github/workflows/visual-qa-classify.yml",
    ROOT / ".github/workflows/visual-qa-iso.yml",
    ROOT / ".github/workflows/visual-qa-capture.yml",
    ROOT / ".github/workflows/visual-qa-report.yml",
]

RANKING = 2


class ClassifierFailureIsVisible(unittest.TestCase):
    def setUp(self) -> None:
        testlib.require_module(self, "yaml")

    def test_classify_reports_when_it_could_not_decide(self) -> None:
        """Si el clasificador no escribe `visual`, el job lo dice.

        `continue-on-error` mantiene el merge abierto; lo que no puede es
        dejar el mismo rastro que un diff no visual.
        """
        text = CLASSIFY.read_text(encoding="utf-8")
        findings = {}
        if "steps.classify.outputs.visual" not in text:
            findings["visual-qa:silent-failure:classify"] = (
                "visual-qa-classify.yml no comprueba steps.classify.outputs.visual: "
                "sin salida, el job termina en verde igual que un diff no visual")
        elif 'outputs.visual ==' not in text and "outputs.visual !=" not in text:
            findings["visual-qa:silent-failure:classify"] = (
                "visual-qa-classify.yml nombra la salida pero no la usa para decidir "
                "nada: falta un paso que falle si quedó vacía")
        testlib.assert_findings(self, "visual-qa:silent-failure", findings)

    def test_every_gate_declares_the_outcome_it_expects(self) -> None:
        """Cada gate con continue-on-error tiene un job que consume su salida."""
        findings = {}
        for path in GATES:
            body = path.read_text(encoding="utf-8")
            if "continue-on-error: true" not in body:
                continue
            if "needs." not in body and "outputs.visual" not in body:
                findings[f"visual-qa:silent-failure:{path.name}"] = (
                    f"{path.name} tiene continue-on-error y nadie consume su resultado: "
                    "un fallo del pipeline es indistinguible de 'no visual'")
        testlib.assert_findings(self, "visual-qa:silent-failure", findings)


if __name__ == "__main__":
    unittest.main()


class SilentFailureIsReported(unittest.TestCase):
    """El gate tiene que avisar cuando no llegó a decidir (A7).

    `continue-on-error` mantiene el merge abierto (correcto: no es check
    requerido). Lo que no puede es dejar el mismo rastro que un diff no
    visual: cero capturas, cero comentario, todo verde.
    """

    MARKER = "Report that the classifier could not decide"

    def test_each_gate_publishes_the_unknown_state(self) -> None:
        findings = {}
        for path in GATES:
            body = path.read_text(encoding="utf-8")
            if "continue-on-error: true" not in body:
                continue
            if self.MARKER not in body:
                findings[f"visual-qa:silent-failure:{path.name}"] = (
                    f"{path.name} lleva continue-on-error y no avisa cuando el "
                    "clasificador no decidió: un fallo del pipeline es "
                    "indistinguible de 'no visual'")
        testlib.assert_findings(self, "visual-qa:silent-failure", findings)

    def test_the_notice_reaches_the_step_summary(self) -> None:
        for path in GATES:
            body = path.read_text(encoding="utf-8")
            if self.MARKER not in body:
                continue
            chunk = body.split(self.MARKER, 1)[1].split("- name:", 1)[0]
            self.assertIn(
                "GITHUB_STEP_SUMMARY",
                chunk,
                f"[visual-qa:silent-failure:{path.name}] el aviso no llega al "
                "resumen del job: nadie lo vería",
            )
