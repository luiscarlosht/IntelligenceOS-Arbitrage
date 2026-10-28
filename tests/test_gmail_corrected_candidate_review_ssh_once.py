"""Corrected-workbook SSH helper: mocked send only; no real credentials or network."""
import hashlib
import json

import pytest

from ops import gmail_corrected_candidate_review_ssh_once as helper


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    workbook=tmp_path/'report.xlsx';workbook.write_bytes(b'synthetic workbook')
    config=tmp_path/'sender';config.write_text('export SMTP_USERNAME=fixture@gmail.com\n')
    monkeypatch.setattr(helper,'workbook',workbook)
    monkeypatch.setattr(helper,'SENDER_CONFIG',config)
    monkeypatch.setattr(helper,'check_report',lambda:(workbook.read_bytes(),hashlib.sha256(workbook.read_bytes()).hexdigest()))
    for attr,suffix in [('marker','.attempted'),('stages','.stages.jsonl'),('outcome_path','.outcome.json')]:
        monkeypatch.setattr(helper,attr,tmp_path/('ssh-1'+suffix))
    return tmp_path


def test_one_send_exact_content_attachment_no_replay(prepared,monkeypatch):
    old=prepared/'gmail-ebay-candidate-review-ssh-1.attempted';old.write_bytes(b'preserve')
    messages=[]
    def send(message,token_file,*,observe):
        messages.append(message)
        observe('message_submission','started')
        observe('message_submission','completed')
        observe('acceptance_validation','completed',acceptance_observed=True)
    monkeypatch.setattr(helper,'send_message',send)
    assert helper.execute()==0
    message=messages[0]
    assert str(message['To'])=='luiscarloshernandez@hotmail.com'
    assert str(message['Subject'])=='Corrected — eBay/Amazon proof-of-concept candidate review'
    assert message.get('Cc') is None and message.get('Bcc') is None
    body=message.get_body(preferencelist=('plain',)).get_content()
    for text in ('10 real eBay listings','10 ambiguous candidates; zero confirmed matches',
                 'Profitability unknown','not a purchase recommendation'):
        assert text in body
    attachments=list(message.iter_attachments())
    assert len(attachments)==1 and attachments[0].get_filename()=='Corrected-eBay-Amazon-Candidate-Review.xlsx'
    assert attachments[0].get_payload(decode=True)==b'synthetic workbook'
    assert json.loads(helper.outcome_path.read_text())['acceptance_observed']
    with pytest.raises(FileExistsError):helper.execute()
    assert len(messages)==1 and old.read_bytes()==b'preserve'


@pytest.mark.parametrize('submission',[False,True])
def test_failure_never_retried_and_classifies_uncertainty(prepared,monkeypatch,submission):
    calls=[]
    def send(*args,observe,**kwargs):
        calls.append(1)
        if submission:observe('message_submission','started')
        raise RuntimeError('synthetic secret must never be logged')
    monkeypatch.setattr(helper,'send_message',send)
    assert helper.execute()==1 and len(calls)==1
    result=json.loads(helper.outcome_path.read_text())
    assert result['status']==('submission_uncertain' if submission else 'failed_before_submission')
    assert result['acceptance_observed'] is False
    assert 'synthetic secret' not in helper.outcome_path.read_text()


def test_check_has_no_send_or_credential_access(prepared,monkeypatch):
    monkeypatch.setattr('sys.argv',['helper','--check'])
    monkeypatch.setattr(helper,'send_message',lambda *a,**k:pytest.fail('Send'))
    assert helper.main()==0
    assert not helper.marker.exists() and not helper.outcome_path.exists()


def test_send_cli_requires_interactive_terminal(prepared,monkeypatch):
    monkeypatch.setattr('sys.argv',['helper','--send'])
    monkeypatch.setattr(helper.sys.stdin,'isatty',lambda:False)
    monkeypatch.setattr(helper,'execute',lambda:pytest.fail('Send'))
    assert helper.main()==1
    assert not helper.marker.exists()


def test_distinct_corrected_workbook_and_attempt_paths():
    # The earlier helper is intentionally absent from this PR's clean checkout.
    # Pin its historical paths without importing operational delivery code.
    original_workbook=helper.base/(helper.stem+'.xlsx')
    assert helper.workbook==helper.base/(helper.stem+'-corrected.xlsx')
    assert helper.workbook!=original_workbook
    assert helper.EXPECTED_WORKBOOK_SHA256=='23138171a64294d9e3353a5cfecd32d303030ca181ff59dbc8cbd0fac396dd47'
    for key,suffix in (('marker','.attempted'),('stages','.stages.jsonl'),('outcome_path','.outcome.json')):
        original_path=helper.root/('var/diagnostics/gmail-ebay-candidate-review-ssh-1'+suffix)
        corrected_path=helper.root/('var/diagnostics/gmail-ebay-candidate-review-corrected-ssh-1'+suffix)
        assert getattr(helper,key)==corrected_path
        assert getattr(helper,key)!=original_path


def test_hash_mismatch_blocks_before_sender_credentials_or_send(tmp_path,monkeypatch):
    report=tmp_path/'report.json'
    report.write_text(json.dumps(dict(status='succeeded',live_requests=21,attempts=[{}]*21,is_mock=False,
        rows=[dict(status='ambiguous',exact=False)]*10)))
    workbook=tmp_path/'altered.xlsx';workbook.write_bytes(b'wrong workbook')
    monkeypatch.setattr(helper,'report',report);monkeypatch.setattr(helper,'workbook',workbook)
    monkeypatch.setattr(helper,'SENDER_CONFIG',tmp_path/'must-not-be-read')
    monkeypatch.setattr(helper,'send_message',lambda *a,**k:pytest.fail('Send'))
    with pytest.raises(ValueError):helper.execute()
