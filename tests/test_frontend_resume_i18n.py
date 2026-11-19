"""M4 frontend resume UI: the 4-language copy must stay complete.

The frontend is a single Streamlit script, so importing it is not an option in the
main test env (Streamlit may be absent/broken there). These tests only parse the
translation table and source, plus compare the frontend reason mapping against the
backend's resume-policy constants — a drift guard that needs no Streamlit.

The rendered behavior itself is covered by tests/test_frontend_obs.py (skipped
where Streamlit cannot be imported; run it on the env that has Streamlit).
"""
from __future__ import annotations

import ast
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
LANGS = ("zh", "en", "ja", "ko")

RESUME_KEYS = (
    "research_state_failed",
    "research_state_cancelled",
    "research_state_interrupted",
    "research_state_unknown",
    "resume_btn",
    "resume_breakpoint",
    "resume_attempts",
    "resume_reason_disabled",
    "resume_reason_complete",
    "resume_reason_no_record",
    "resume_reason_schema",
    "resume_reason_exhausted",
    "resume_reason_no_checkpoint",
    "resume_reason_unknown",
    "resume_in_progress",
    "resume_confirm_required",
)


def _module_assign(name: str) -> ast.expr:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets:
                return node.value
    raise AssertionError(f"{name} assignment not found in frontend/app.py")


def _translations() -> dict:
    return ast.literal_eval(_module_assign("T"))


def _mapping(name: str) -> dict:
    return ast.literal_eval(_module_assign(name))


def test_all_four_languages_have_the_resume_copy():
    translations = _translations()
    assert set(translations) == set(LANGS)
    for lang in LANGS:
        missing = [key for key in RESUME_KEYS if not translations[lang].get(key)]
        assert not missing, f"{lang} is missing resume copy: {missing}"


def test_placeholder_keys_keep_their_placeholders():
    translations = _translations()
    for lang in LANGS:
        breakpoint = translations[lang]["resume_breakpoint"]
        attempts = translations[lang]["resume_attempts"]
        assert "{node}" in breakpoint and "{step}" in breakpoint, (lang, breakpoint)
        assert "{attempt}" in attempts and "{max}" in attempts, (lang, attempts)


def test_frontend_reason_mapping_covers_every_backend_reason():
    """The UI must explain every refusal reason the resume policy can return."""
    from deepchoice.server import resume as server_resume

    backend_reasons = {
        server_resume.REASON_FEATURE_DISABLED,
        server_resume.REASON_ALREADY_COMPLETE,
        server_resume.REASON_NO_RUN_RECORD,
        server_resume.REASON_SCHEMA_MISMATCH,
        server_resume.REASON_ATTEMPTS_EXHAUSTED,
        server_resume.REASON_NO_CHECKPOINT,
    }
    frontend_reasons = _mapping("_RESUME_REASON_KEYS")
    assert backend_reasons <= set(frontend_reasons)
    translations = _translations()
    for lang in LANGS:
        for reason, key in frontend_reasons.items():
            assert translations[lang].get(key), f"{lang}/{reason} -> missing key {key}"


def test_frontend_calls_the_confirmed_resume_endpoint():
    source = APP_PATH.read_text(encoding="utf-8")
    assert "/resume" in source
    assert '"confirm": True' in source
    # The failure view must not claim success on its own.
    assert "202" in source
