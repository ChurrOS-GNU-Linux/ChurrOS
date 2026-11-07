# shellcheck shell=bash
# Nombres de artefacto de la QA visual. Se carga con source.

visual_qa_pr_iso_name() {
  printf 'visual-qa-pr-%s-%s\n' "$1" "$2"
}

visual_qa_main_iso_name() {
  printf 'visual-qa-main-%s-%s\n' "$1" "$2"
}

visual_qa_before_name() {
  printf 'visual-qa-before-%s\n' "$1"
}

visual_qa_after_name() {
  printf 'visual-qa-after-%s\n' "$1"
}

visual_qa_report_name() {
  printf 'visual-qa-report-%s\n' "$1"
}
