from unittest.mock import Mock
from uuid import uuid4

import pytest

from echora_analysis import analysis_jobs, jobs, worker


@pytest.fixture
def execution(monkeypatch):
    monkeypatch.setattr(worker.os, 'setsid', Mock())
    monkeypatch.setattr(worker.signal, 'signal', Mock())
    context = Mock()
    monkeypatch.setattr(jobs, 'JobContext', Mock(return_value=context))
    failure = Mock()
    monkeypatch.setattr(jobs, 'fail', failure)
    job = {'id': uuid4(), 'claim_token': uuid4(), 'worker_type': 'analysis',
           'attempts': 1, 'max_attempts': 3}
    return job, context, failure


def test_expansion_is_not_finished_twice(execution, monkeypatch):
    job, context, failure = execution
    monkeypatch.setattr(analysis_jobs, 'execute', Mock(return_value=None))
    worker.execute(job)
    context.complete.assert_not_called()
    failure.assert_not_called()


def test_partial_batch_retries_then_reports_partial(execution, monkeypatch):
    job, context, failure = execution
    summary = {'lyrics': {'failed': 1}}
    monkeypatch.setattr(analysis_jobs, 'execute', Mock(return_value=summary))
    worker.execute(job)
    failure.assert_called_once()
    context.complete.assert_not_called()
    job['attempts'] = 3
    worker.execute(job)
    context.complete.assert_called_once_with(summary, status='partial')


def test_cancel_does_not_retry(execution, monkeypatch):
    job, context, failure = execution
    monkeypatch.setattr(analysis_jobs, 'execute', Mock(side_effect=jobs.JobCancelled()))
    worker.execute(job)
    context.complete.assert_not_called()
    failure.assert_not_called()


def test_failure_never_persists_provider_exception(execution, monkeypatch):
    job, context, failure = execution
    monkeypatch.setattr(analysis_jobs, 'execute', Mock(side_effect=RuntimeError('password=secret')))
    worker.execute(job)
    assert 'secret' not in repr(failure.call_args)
    context.complete.assert_not_called()


def test_success_is_terminal(execution, monkeypatch):
    job, context, failure = execution
    summary = {'failed': 0, 'embedded': 3}
    monkeypatch.setattr(analysis_jobs, 'execute', Mock(return_value=summary))
    worker.execute(job)
    context.complete.assert_called_once_with(summary, status='complete')
    failure.assert_not_called()
