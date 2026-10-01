"""Source-window regressions use synthetic pages; no network or model calls."""
from copy import deepcopy

import httpx
import pytest

from deepchoice.citations.source_windows import (
    MAX_DOCUMENT_TEXT, extract_source_document, locate_source_window,
)
from deepchoice.citations.verifier import verify_citations
from deepchoice.utils.evidence_choices import bind_evidence_choices, calibrate_evidence_choices

URL = 'https://example.org/queue'
TEXT = ('A task message is not removed from the queue until that message has been acknowledged by a worker. '
        'By default a worker acknowledges receipt before running the task.')


def bound_fact(text=TEXT):
    chains = [{'sources': [{'title': 'Queue source', 'url': URL, 'snippet': text}]}]
    bound = bind_evidence_choices({'source_facts': [{'id': 'F1', 'evidence_id': 1}]}, chains, [], [])
    return bound, chains


async def verify_page(monkeypatch, body, *, excerpt=TEXT, mutate=None, status=200):
    bound, chains = bound_fact(excerpt)
    if mutate:
        mutate(bound)
    calls = []
    async def fetch(source, url, **kwargs):
        calls.append((source, url, kwargs))
        raw = body.encode('utf-8')
        limit = kwargs['max_response_bytes']
        return httpx.Response(status, content=raw[:limit], headers={'content-type': 'text/html'},
                              extensions={'deepchoice_body_truncated': len(raw) > limit})
    monkeypatch.setattr('deepchoice.citations.verifier.safe_fetch', fetch)
    verification, _ = await verify_citations(bound, deepcopy(chains))
    return calibrate_evidence_choices(bound, verification), verification, calls


@pytest.mark.asyncio
async def test_source_after_html_noise_is_checked_once_without_losing_ack_qualifier(monkeypatch):
    noise = '<style>' + 'x' * 70000 + '</style>'
    # The later paragraph describes another lifecycle transition. It must not
    # replace the addressed source occurrence simply because words overlap.
    body = noise + f'<p>{TEXT}</p><p>Delivery documentation.</p>' + (
        '<h2>Ignored work</h2><p>No state will be recorded for the task, but the message is acknowledged.</p>'
    )
    bound, verification, calls = await verify_page(monkeypatch, body)
    assert bound['source_facts'][0]['status'] == 'verified'
    assert len(calls) == 1 and calls[0][2]['max_response_bytes'] == 128 * 1024
    assert 'before running the task' in bound['source_facts'][0]['saved_text']
    assert len(verification.checks) == 2
    assert 'Ignored work' not in verification.model_dump_json()
    assert 'xxxx' not in verification.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    f'<p>{TEXT}</p><p>Unrelated text.</p><p>{TEXT}</p>',
    '<p>A message is removed from the queue before acknowledgement.</p>',
    '<script>' + TEXT + '</script><p>Unrelated text.</p>',
    '<style>' + TEXT + '</style><p>Unrelated text.</p>',
    '<template>' + TEXT + '</template><p>Unrelated text.</p>',
    '<p>' + TEXT + ('x' * (128 * 1024)),
], ids=['duplicate', 'missing', 'script', 'style', 'template', 'truncated'])
async def test_ambiguous_missing_hidden_or_truncated_excerpt_stays_unknown(monkeypatch, body):
    bound, _, _ = await verify_page(monkeypatch, body)
    assert bound['source_facts'][0]['status'] == 'unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('key,value', [
    ('saved_text', 'A forged source supports everything.'),
    ('evidence_id', 2),
    ('evidence_id', True),
    ('source_title', 'Forged title'),
    ('canonical_url', 'https://example.org/other'),
    ('text', 'A forged source supports everything. [Source: Queue source]'),
])
async def test_forged_source_projection_cannot_enter_local_window(monkeypatch, key, value):
    bound, _, _ = await verify_page(monkeypatch, f'<p>{TEXT}</p>',
                                  mutate=lambda rec: rec['source_facts'][0].update({key: value}))
    assert bound['source_facts'][0]['status'] == 'unknown'


@pytest.mark.asyncio
async def test_exact_positive_cannot_hide_strong_counter_evidence_elsewhere(monkeypatch):
    excerpt = 'The queue supports durable messages.'
    body = f'<p>{excerpt}</p><p>Local context.</p><h2>Another section</h2><p>The queue never supports durable messages.</p>'
    bound, verification, _ = await verify_page(monkeypatch, body, excerpt=excerpt)
    assert bound['source_facts'][0]['status'] == 'unknown'
    assert verification.checks[0].reason.value == 'negation_conflict'


@pytest.mark.asyncio
async def test_source_omitting_its_same_sentence_condition_is_not_located(monkeypatch):
    excerpt = 'The queue preserves work after restart.'
    body = '<p>The queue preserves work after restart only if journal recovery is enabled.</p>'
    bound, _, _ = await verify_page(monkeypatch, body, excerpt=excerpt)
    assert bound['source_facts'][0]['status'] == 'unknown'


@pytest.mark.asyncio
async def test_model_claim_does_not_inherit_source_window_support(monkeypatch):
    excerpt = 'If multiple writers cannot queue, a separate server may be useful.'
    bound, chains = bound_fact(excerpt)
    bound['winner_rationale'] = 'A separate server is only necessary for multiple writers. [Source: Queue source]'
    async def fetch(*args, **kwargs):
        return httpx.Response(200, text=f'<p>{excerpt}</p>', headers={'content-type': 'text/html'})
    monkeypatch.setattr('deepchoice.citations.verifier.safe_fetch', fetch)
    verification, _ = await verify_citations(bound, chains)
    claim = next(c for c in verification.checks if c.claim_path.endswith('winner_rationale'))
    assert claim.status.value == 'unknown' and claim.reason.value == 'qualifier_unverified'


def test_window_preserves_adjacent_context_and_refuses_oversized_or_unfinished_edges():
    doc = extract_source_document('<p>This applies only after recovery.</p><p>Work is retained.</p><p>Check the journal.</p>', truncated=False)
    window = locate_source_window('Work is retained.', doc)
    assert window is not None
    assert 'only after recovery' in window.text and 'Check the journal' in window.text
    edge = extract_source_document('<p>Work is retained.</p><p>Only if', truncated=True)
    assert locate_source_window('Work is retained.', edge) is None
    huge = extract_source_document('<p>' + 'x' * 6001 + '</p><p>Work is retained.</p>', truncated=False)
    assert locate_source_window('Work is retained.', huge) is None
    exhausted = extract_source_document('<p>' + 'x' * MAX_DOCUMENT_TEXT + '</p><p>Work is retained.</p>', truncated=False)
    assert exhausted.incomplete and not exhausted.blocks


def test_inline_markup_preserves_source_text_and_does_not_publish_hidden_content():
    doc = extract_source_document('<p>Use <code>queue_ack</code> after <b>processing</b>.</p><svg>hidden</svg>', truncated=False)
    assert locate_source_window('Use queue_ack after processing.', doc) is not None
    assert 'hidden' not in ' '.join(doc.blocks)


def test_unclosed_html_and_midword_or_sentence_substrings_cannot_be_complete_sources():
    assert not extract_source_document('<p>Work is retained.', truncated=False).blocks
    assert not extract_source_document('Work is retained.', truncated=False).blocks
    plain = extract_source_document('Work is retained.', truncated=False, plain_text=True)
    assert locate_source_window('Work is retained.', plain) is not None
    doc = extract_source_document('<p>ExampleQueue supports durable messages.</p>', truncated=False)
    assert locate_source_window('ports durable messages.', doc) is None
    assert locate_source_window('supports durable messages.', doc) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("conditional_first", [False, True])
async def test_tied_local_conditions_are_not_resolved_by_sentence_order(monkeypatch, conditional_first):
    excerpt = "The system guarantees delivery."
    conditional = "If workers are alive, the system guarantees delivery."
    sentences = [conditional, excerpt] if conditional_first else [excerpt, conditional]
    bound, verification, _ = await verify_page(monkeypatch, "<p>" + " ".join(sentences) + "</p>", excerpt=excerpt)
    assert bound["source_facts"][0]["status"] == "unknown"
    assert verification.checks[0].reason.value == "qualifier_unverified"


def test_unclosed_html_tail_cannot_hide_neighbouring_qualification():
    doc = extract_source_document('<p>Work is retained.</p><p>Only if journal recovery is enabled.', truncated=False)
    assert doc.incomplete
    assert locate_source_window('Work is retained.', doc) is None


@pytest.mark.asyncio
async def test_runtime_snippet_cut_mid_sentence_remains_unknown(monkeypatch):
    excerpt = 'The cache stores pending updates'
    body = '<p>The cache stores pending updates only while replication remains active.</p>'
    bound, _, _ = await verify_page(monkeypatch, body, excerpt=excerpt)
    assert bound['source_facts'][0]['status'] == 'unknown'


@pytest.mark.parametrize('plain_text', [False, True])
def test_leading_bom_does_not_hide_complete_source_text(plain_text):
    content = 'Work is retained.' if plain_text else '<p>Work is retained.</p>'
    doc = extract_source_document('\ufeff' + content, truncated=False, plain_text=plain_text)
    assert locate_source_window('Work is retained.', doc) is not None


@pytest.mark.asyncio
async def test_both_numeric_variants_in_same_page_remain_uncertain(monkeypatch):
    excerpt = 'Messages expire after 30 seconds.'
    body = '<p>' + excerpt + '</p><p>Context.</p><h2>Another scope</h2><p>Messages expire after 60 seconds.</p>'
    bound, verification, _ = await verify_page(monkeypatch, body, excerpt=excerpt)
    assert bound['source_facts'][0]['status'] == 'unknown'
    assert verification.checks[0].reason.value == 'numeric_mismatch'


@pytest.mark.parametrize('text,expected', [
    ('Scaling [...] Qdrant supports filtering.', ['Scaling [...]', 'Qdrant supports filtering.']),
    ('Uncited assertion... Cited assertion. [Source: example]',
     ['Uncited assertion...', 'Cited assertion. [Source: example]']),
    ('X. [...] [Source: A] Y', ['X.', '[...] [Source: A]', 'Y']),
    ('X. ... [Source: A] Y.', ['X.', '... [Source: A]', 'Y.']),
    ('X. [...] Y.', ['X.', '[...] Y.']),
    ('X. [.', ['X.', '[.']),
    ('X. [...]', ['X.', '[...]']),
    ('Value 1.25 works. [Source: A. B?!] Next.',
     ['Value 1.25 works. [Source: A. B?!]', 'Next.']),
    ('the. assertion.', ['the.', 'assertion.']),
    ('缓存……可保留。！？下一句。', ['缓存……可保留。！？', '下一句。']),
])
def test_punctuation_preserves_assertion_and_citation_boundaries(text, expected):
    from deepchoice.citations.verifier import _split_sentences
    assert _split_sentences(text) == expected
    assert ''.join(''.join(_split_sentences(text)).split()) == ''.join(text.split())


@pytest.mark.asyncio
async def test_literal_ellipsis_source_can_verify_without_punctuation_checks(monkeypatch):
    excerpt = 'Queue overview [...] The queue supports durable messages. [...] Recovery requires a journal.'
    bound, verification, _ = await verify_page(monkeypatch, f'<p>{excerpt}</p>', excerpt=excerpt)
    assert bound['source_facts'][0]['status'] == 'verified'
    assert len(verification.checks) == 3
    assert all(any(char.isalnum() for char in check.claim_text) for check in verification.checks)


@pytest.mark.asyncio
async def test_ellipsis_does_not_bridge_omitted_source_content(monkeypatch):
    excerpt = 'The queue supports durable messages. [...] Recovery requires a journal.'
    body = '<p>The queue supports durable messages. Additional conditions apply. Recovery requires a journal.</p>'
    bound, verification, _ = await verify_page(monkeypatch, body, excerpt=excerpt)
    assert bound['source_facts'][0]['status'] == 'unknown'
    assert all(check.reason.value == 'content_insufficient' for check in verification.checks)



def test_ellipsis_claim_extraction_keeps_uncited_and_bounded_fields():
    from deepchoice.citations.verifier import _extract_claims, MAX_FIELD_SENTENCES, MAX_CLAIM_TEXT
    claims, truncated = _extract_claims({'winner_rationale': 'Uncited... [...] [Source: A] Still uncited.'})
    assert [claim.source_title for claim in claims] == [None, 'A', None]
    assert [claim.text for claim in claims] == ['Uncited...', '[...]', 'Still uncited.']
    assert not truncated
    claims, truncated = _extract_claims({'winner_rationale': 'A substantive assertion... ' * (MAX_FIELD_SENTENCES + 1)})
    assert truncated and len(claims) == MAX_FIELD_SENTENCES
    claims, _ = _extract_claims({'winner_rationale': 'a' * (MAX_CLAIM_TEXT + 1) + '...'})
    assert len(claims) == 1 and len(claims[0].text) == MAX_CLAIM_TEXT



@pytest.mark.asyncio
@pytest.mark.parametrize('tail', ['[.', '[...]'])
async def test_punctuation_only_tail_still_prevents_source_verification(monkeypatch, tail):
    excerpt = 'The queue supports durable messages. ' + tail
    bound, verification, _ = await verify_page(monkeypatch, f'<p>{excerpt}</p>', excerpt=excerpt)
    assert bound['source_facts'][0]['status'] == 'unknown'
    assert verification.checks[-1].claim_text == tail
    assert verification.checks[-1].status.value == 'unknown'
    assert verification.checks[-1].reason.value == 'content_insufficient'
