"""Unit tests plus isolated-schema PostgreSQL tests (opt in TEST_DATABASE_URL)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from echora_analysis import jobs


def test_public_allowlist():
    row = {key: None for key in jobs.PUBLIC}
    row.update(id=uuid4(), created_at=datetime.now(timezone.utc), status='queued',
               payload={'password': 'secret'}, token=uuid4(), worker_id='private')
    public = jobs._public(row)
    assert public['id'] == public['job_id'] == str(row['id'])
    assert not {'payload', 'token', 'claim_token', 'worker_id'} & public.keys()
    assert public['existing'] is False


def test_context_fencing(monkeypatch):
    token = uuid4()
    context = jobs.JobContext({'id': str(uuid4()), 'claim_token': token})
    assert context.token == token
    for function in ('heartbeat', 'progress', 'finish'):
        monkeypatch.setattr(jobs, function, lambda *args, **kwargs: False)
    for call in (context.check, lambda: context.report({}), context.complete):
        with pytest.raises(jobs.JobCancelled):
            call()
    assert not issubclass(jobs.JobCancelled, Exception)


def test_input_validation():
    with pytest.raises(ValueError):
        jobs.finish(uuid4(), uuid4(), status='waiting')
    with pytest.raises(ValueError):
        jobs.expand(uuid4(), uuid4(), [None])
    with pytest.raises(ValueError):
        jobs.checkpoint(uuid4(), uuid4(), [])
    assert jobs._uuid(str(uuid4())) is not None


@pytest.fixture
def database(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is required for PostgreSQL queue tests')
    schema = 'test_jobs_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    def connect():
        return psycopg.connect(url, options=f'-c search_path={schema}', row_factory=dict_row)
    monkeypatch.setattr(jobs, '_db', connect)
    try:
        with connect() as db:
            # Exercise the packaged migration, also available in deployed source trees.
            import runpy
            from unittest.mock import patch
            migration = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                                           'alembic/versions/0034_jobs.py'))
            with patch('alembic.op.execute', side_effect=db.execute):
                migration['upgrade']()
        yield connect
    finally:
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def ready(database, job_id):
    with database() as db:
        db.execute("UPDATE jobs SET available_at=now()-interval '1 second' WHERE id=%s", (job_id,))


def expire(database, job_id):
    with database() as db:
        db.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (job_id,))


def test_owner_dedupe_and_public(database):
    owner, other, connection = str(uuid4()), str(uuid4()), str(uuid4())
    first = jobs.enqueue('analysis', 'analysis', owner, connection, {'secret': 'hidden'}, 'key')
    assert jobs.enqueue('analysis', 'analysis', owner, dedupe_key='key')['existing']
    assert jobs.enqueue('analysis', 'analysis', other, dedupe_key='key')['id'] != first['id']
    assert jobs.get_job(first['id'], other) is None
    assert jobs.cancel(first['id'], other) is None
    assert jobs.list_jobs(owner, connection) == [first]
    assert jobs.list_jobs(owner, str(uuid4())) == []
    assert jobs.cancel(first['id'], owner)['status'] == 'cancelled'
    assert jobs.list_jobs(owner, active_only=True) == []
    assert jobs.enqueue('analysis', 'analysis', owner, dedupe_key='key')['id'] != first['id']


def test_fencing_checkpoint_retry_and_error(database):
    owner = uuid4()
    public = jobs.enqueue('curation', 'curation', owner, payload={'seed': 1})
    job = jobs.claim('curation', 'worker')
    assert job['claim_token'] == job['token']
    assert jobs.claim('analysis', 'worker') is None
    assert not jobs.progress(public['id'], uuid4(), {'bad': True})
    assert jobs.checkpoint(public['id'], str(job['token']), {'selection': [1, 2]})
    assert jobs.progress(public['id'], job['token'], {'count': 2})
    assert jobs.fail(public['id'], job['token'], 'postgres://password-secret', True)
    assert not jobs.finish(public['id'], job['token'])
    assert jobs.claim('curation', 'worker') is None  # backoff
    ready(database, public['id'])
    second = jobs.claim('curation', 'worker2')
    assert second['payload'] == {'seed': 1, 'selection': [1, 2]}
    assert second['token'] != job['token']
    assert not jobs.checkpoint(public['id'], job['token'], {'selection': []})
    assert jobs.fail(public['id'], second['token'], 'secret', retryable=False)
    final = jobs.get_job(public['id'], owner)
    assert final['status'] == 'failed'
    assert final['error'] == 'Job execution failed.'
    assert 'secret' not in str(final)


def test_expired_lease_and_bounded_attempts(database):
    owner = uuid4()
    public = jobs.enqueue('analysis', 'analysis', owner)
    for attempt in range(1, 4):
        job = jobs.claim('analysis', 'worker')
        assert job['attempts'] == attempt
        expire(database, public['id'])
        assert not jobs.heartbeat(public['id'], job['token'])
        assert not jobs.finish(public['id'], job['token'])
        assert jobs.claim('analysis', 'replacement') is None
        ready(database, public['id'])
    assert jobs.get_job(public['id'], owner)['status'] == 'failed'
    assert jobs.claim('analysis', 'worker') is None


def test_running_cancellation_acknowledgement(database):
    owner = uuid4()
    public = jobs.enqueue('analysis', 'analysis', owner, dedupe_key='one')
    job = jobs.claim('analysis', 'worker')
    cancelled = jobs.cancel(public['id'], owner)
    assert cancelled['status'] == 'running' and cancelled['cancel_requested']
    with database() as db:
        assert db.execute('SELECT token FROM jobs WHERE id=%s', (job['id'],)).fetchone()['token'] == job['token']
    assert jobs.enqueue('analysis', 'analysis', owner, dedupe_key='one')['existing']
    assert not jobs.heartbeat(public['id'], job['token'])
    assert jobs.get_job(public['id'], owner)['status'] == 'cancelled'


def test_cancel_expiry(database):
    owner = uuid4()
    job = jobs.enqueue('analysis', 'analysis', owner)
    claim = jobs.claim('analysis', 'worker')
    jobs.cancel(job['id'], owner)
    expire(database, job['id'])
    assert jobs.claim('analysis', 'worker') is None
    assert jobs.get_job(job['id'], owner)['status'] == 'cancelled'
    assert not jobs.finish(job['id'], claim['token'])


def test_batches_aggregate_and_hide_children(database):
    owner, connection = uuid4(), uuid4()
    root = jobs.enqueue('analysis', 'analysis', owner, connection)
    claim = jobs.claim('analysis', 'worker')
    assert jobs.expand(root['id'], claim['token'], [{'batch': 1}, {'batch': 2}])
    assert not jobs.expand(root['id'], claim['token'], [])
    assert len(jobs.list_jobs(owner)) == 1
    assert jobs.get_job(root['id'], owner)['progress']['total'] == 2
    a, b = jobs.claim('analysis', 'a'), jobs.claim('analysis', 'b')
    assert a['parent_id'] == b['parent_id'] == claim['id']
    assert a['user_id'] == owner and a['connection_id'] == connection
    assert a['kind'] == 'analysis_batch'
    assert jobs.finish(a['id'], a['token'], {'ok': True})
    assert jobs.get_job(root['id'], owner)['status'] == 'waiting'
    assert jobs.fail(b['id'], b['token'], 'error', retryable=False)
    final = jobs.get_job(root['id'], owner)
    assert final['status'] == 'partial'
    assert final['progress']['completed'] == final['progress']['total'] == 2


def test_cancel_batch_and_empty_batch(database):
    owner = uuid4()
    root = jobs.enqueue('analysis', 'analysis', owner)
    claim = jobs.claim('analysis', 'worker')
    assert jobs.expand(root['id'], claim['token'], [{}, {}])
    child = jobs.claim('analysis', 'worker')
    assert jobs.cancel(root['id'], owner)['status'] == 'waiting'
    assert not jobs.progress(child['id'], child['token'], {})
    assert jobs.get_job(root['id'], owner)['status'] == 'cancelled'
    root = jobs.enqueue('analysis', 'analysis', owner)
    claim = jobs.claim('analysis', 'worker')
    assert jobs.expand(root['id'], claim['token'], [])
    assert jobs.get_job(root['id'], owner)['status'] == 'complete'


def test_parallel_claim_and_dedupe(database):
    owner = uuid4()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: jobs.enqueue('analysis', 'analysis', owner,
                                                       dedupe_key='single'), range(6)))
    assert len({r['id'] for r in results}) == 1
    assert sum(not r['existing'] for r in results) == 1
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda i: jobs.claim('analysis', str(i)), range(6)))
    assert sum(c is not None for c in claims) == 1


def test_expand_rollback(database):
    owner = uuid4()
    root = jobs.enqueue('analysis', 'analysis', owner)
    claim = jobs.claim('analysis', 'worker')
    with pytest.raises(TypeError):
        jobs.expand(root['id'], claim['token'], [{'ok': 1}, {'bad': object()}])
    assert jobs.get_job(root['id'], owner)['status'] == 'running'
    with database() as db:
        assert db.execute('SELECT count(*) AS n FROM jobs WHERE parent_id=%s',
                          (root['id'],)).fetchone()['n'] == 0
    assert jobs.expand(root['id'], claim['token'], [{}, {}])
    children = [jobs.claim('analysis', 'worker') for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda child: jobs.finish(child['id'], child['token']), children))
    assert jobs.get_job(root['id'], owner)['status'] == 'complete'


def test_skip_locked(database):
    owner = uuid4()
    first = jobs.enqueue('analysis', 'analysis', owner)
    second = jobs.enqueue('analysis', 'analysis', owner)
    with database() as db:
        db.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE', (first['id'],))
        claimed = jobs.claim('analysis', 'worker')
        assert claimed['job_id'] == second['id']


@pytest.mark.parametrize('outcome', ['empty', 'complete', 'failed', 'cancelled'])
def test_hum_parent_terminal_projection(database, outcome):
    owner = uuid4()
    parent = jobs.enqueue('hum_corpus', 'analysis', owner)
    with database() as db:
        db.execute("CREATE TABLE hum_corpora(id uuid PRIMARY KEY,user_id uuid,status text,error text,completed_at timestamptz)")
        db.execute("INSERT INTO hum_corpora(id,user_id,status) VALUES (%s,%s,'building')", (parent['id'], owner))
    claim = jobs.claim('analysis', 'worker')
    if outcome == 'empty':
        jobs.expand(claim['id'], claim['token'], [])
    elif outcome == 'cancelled':
        jobs.cancel(parent['id'], owner)
        assert not jobs.heartbeat(claim['id'], claim['token'])
    else:
        jobs.expand(claim['id'], claim['token'], [{'track_ids': ['a']}])
        child = jobs.claim('analysis', 'worker')
        jobs.finish(child['id'], child['token'], status=outcome)
    with database() as db:
        row = db.execute('SELECT * FROM hum_corpora WHERE id=%s', (parent['id'],)).fetchone()
    assert row['status'] == ('complete' if outcome in {'empty', 'complete'} else 'failed')
    assert row['completed_at'] is not None


def test_public_progress_snapshot(database):
    owner = uuid4()
    job = jobs.enqueue('import', 'analysis', owner)
    claim = jobs.claim('analysis', 'worker')
    jobs.progress(claim['id'], claim['token'], {'phase': 'muq', 'completed': 2, 'total': 3, 'token': 'hidden'})
    public = jobs.get_job(job['id'], owner)
    assert public['phase'] == 'muq'
    assert public['completed'] == 2 and public['total'] == 3
    assert 'token' not in public
