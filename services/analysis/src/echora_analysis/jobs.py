"""PostgreSQL queue. Each operation commits independently; no process-local state.

Active dedupe keys are scoped to the owner. Three attempts use 2/4 second
backoff. A batch parent consumes no lease while waiting. Family advisory locks
serialize cancellation/aggregation without serializing unrelated jobs.
"""
from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ACTIVE = ('queued', 'running', 'waiting')
TERMINAL = ('complete', 'partial', 'failed', 'cancelled')
PUBLIC = ('id', 'kind', 'worker_type', 'connection_id', 'parent_id', 'status',
          'cancel_requested', 'progress', 'summary', 'error', 'created_at',
          'updated_at', 'finished_at')


def _uuid(value):
    return UUID(str(value)) if value is not None else None


def _db():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)


def _public(row, existing=False):
    result = {key: row[key] for key in PUBLIC}
    for key, value in result.items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
    # Preserve the legacy snapshot shape while retaining structured progress.
    snapshot = row.get('progress') or {}
    result['progress'] = {key: value for key, value in snapshot.items()
                          if key in {'phase', 'completed', 'total', 'message', 'unit', 'track',
                                     'plan', 'summary', *ACTIVE, *TERMINAL}}
    for key in ('phase', 'completed', 'total', 'message', 'unit', 'track'):
        if key in snapshot:
            result[key] = snapshot[key]
    result.setdefault('phase', row['status'])
    result.setdefault('completed', 0)
    result.setdefault('total', 0)
    result.update(job_id=result['id'], existing=existing)
    return result


def _family(db, job_id, attempt=False):
    row = db.execute('SELECT COALESCE(parent_id,id) AS root FROM jobs WHERE id=%s',
                     (_uuid(job_id),)).fetchone()
    if row is None:
        return False
    function = 'pg_try_advisory_xact_lock' if attempt else 'pg_advisory_xact_lock'
    locked = db.execute(f'SELECT {function}(hashtextextended(%s,0)) AS locked',
                        (str(row['root']),)).fetchone()
    return bool(locked['locked']) if attempt else True


def _insert(db, kind, worker_type, user_id, connection_id, payload, dedupe_key, parent_id):
    row = db.execute('''INSERT INTO jobs
        (id,kind,worker_type,user_id,connection_id,payload,dedupe_key,parent_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (user_id,dedupe_key) WHERE dedupe_key IS NOT NULL
          AND status IN ('queued','running','waiting') DO NOTHING RETURNING *''',
        (uuid4(), kind, worker_type, _uuid(user_id), _uuid(connection_id),
         Jsonb(payload if payload is not None else {}), dedupe_key, _uuid(parent_id))).fetchone()
    if row:
        return _public(row)
    row = db.execute('''SELECT * FROM jobs WHERE user_id=%s AND dedupe_key=%s
                        AND status IN ('queued','running','waiting')''',
                     (_uuid(user_id), dedupe_key)).fetchone()
    return _public(row, True) if row else None


def enqueue(kind, worker_type, user_id, connection_id=None, payload=None,
            dedupe_key=None, parent_id=None):
    with _db() as db:
        if parent_id is not None:
            _family(db, parent_id)
            parent = db.execute('SELECT * FROM jobs WHERE id=%s AND user_id=%s',
                                (_uuid(parent_id), _uuid(user_id))).fetchone()
            if not parent or parent['parent_id'] or parent['status'] != 'waiting' or parent['cancel_requested']:
                raise ValueError('Parent must be an owned, waiting root job')
            connection_id = parent['connection_id']
        # A conflicting job may finish between INSERT and SELECT; retry then.
        while True:
            result = _insert(db, kind, worker_type, user_id, connection_id,
                             payload, dedupe_key, parent_id)
            if result is not None:
                if parent_id:
                    _aggregate(db, parent_id)
                return result


def get_job(job_id, user_id):
    with _db() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=%s AND user_id=%s',
                         (_uuid(job_id), _uuid(user_id))).fetchone()
        return _public(row) if row else None


def list_jobs(user_id, connection_id=None, active_only=False, limit=20):
    clauses, args = ['user_id=%s', 'parent_id IS NULL'], [_uuid(user_id)]
    if connection_id is not None:
        clauses.append('connection_id=%s')
        args.append(_uuid(connection_id))
    if active_only:
        clauses.append("status IN ('queued','running','waiting')")
    args.append(max(0, min(int(limit), 1000)))
    with _db() as db:
        return [_public(row) for row in db.execute(
            'SELECT * FROM jobs WHERE ' + ' AND '.join(clauses) +
            ' ORDER BY created_at DESC,id DESC LIMIT %s', args).fetchall()]


def _terminal(db, job_id, status, summary=None, error=None):
    row = db.execute('''UPDATE jobs SET status=%s,summary=%s,error=%s,token=NULL,
        worker_id=NULL,lease_until=NULL,finished_at=now(),updated_at=now(),
        progress=progress || %s
        WHERE id=%s RETURNING kind,user_id''',
                     (status, Jsonb(summary), error, Jsonb({'phase': status}), job_id)).fetchone()
    if row and row['kind'] == 'hum_corpus':
        # This durable domain projection commits with the parent terminal state,
        # including empty expansions and lease-expiry failures.
        db.execute('''UPDATE hum_corpora SET status=%s,error=%s,completed_at=now()
            WHERE id=%s AND user_id=%s''',
                   ('complete' if status == 'complete' else 'failed',
                    None if status == 'complete' else 'Index job did not complete successfully.',
                    job_id, row['user_id']))


def _aggregate(db, parent_id):
    if not parent_id:
        return
    parent = db.execute('SELECT * FROM jobs WHERE id=%s', (parent_id,)).fetchone()
    if parent['status'] != 'waiting':
        return
    rows = db.execute('SELECT status,count(*) AS n FROM jobs WHERE parent_id=%s GROUP BY status',
                      (parent_id,)).fetchall()
    counts = {state: 0 for state in (*ACTIVE, *TERMINAL)}
    counts.update({r['status']: r['n'] for r in rows})
    counts['total'] = sum(counts.values())
    counts['completed'] = sum(counts[s] for s in TERMINAL)
    snapshot = {**counts, 'phase': 'processing', 'unit': 'batches',
                'message': f"Processed {counts['completed']} of {counts['total']} batches"}
    db.execute('UPDATE jobs SET progress=%s,updated_at=now() WHERE id=%s',
               (Jsonb(snapshot), parent_id))
    if counts['completed'] == counts['total']:
        status = ('cancelled' if parent['cancel_requested'] else
                  'complete' if counts['complete'] == counts['total'] else
                  'partial' if counts['complete'] or counts['partial'] else
                  'failed' if counts['failed'] else 'cancelled')
        _terminal(db, parent_id, status, counts)


def cancel(job_id, user_id):
    with _db() as db:
        _family(db, job_id)
        row = db.execute('SELECT * FROM jobs WHERE id=%s AND user_id=%s',
                         (_uuid(job_id), _uuid(user_id))).fetchone()
        if not row:
            return None
        changed = db.execute('''UPDATE jobs SET cancel_requested=true,updated_at=now()
            WHERE (id=%s OR parent_id=%s) AND status IN ('queued','running','waiting')
            RETURNING id,status''', (row['id'], row['id'])).fetchall()
        for child in changed:
            if child['status'] == 'queued':
                _terminal(db, child['id'], 'cancelled')
        _aggregate(db, row['id'])
        _aggregate(db, row['parent_id'])
        return _public(db.execute('SELECT * FROM jobs WHERE id=%s', (row['id'],)).fetchone())


def _lease(seconds):
    return max(1, min(int(seconds), 86400))


def claim(worker_type, worker_id, lease_seconds=120):
    with _db() as db:
        candidates = db.execute('''SELECT id FROM jobs WHERE worker_type=%s AND
            ((status='queued' AND available_at<=now()) OR
             (status='running' AND lease_until<=now())) ORDER BY available_at,created_at''',
                                (worker_type,)).fetchall()
        for candidate in candidates:
            if not _family(db, candidate['id'], attempt=True):
                continue
            row = db.execute('''SELECT * FROM jobs WHERE id=%s AND
                ((status='queued' AND available_at<=now()) OR
                 (status='running' AND lease_until<=now())) FOR UPDATE SKIP LOCKED''',
                             (candidate['id'],)).fetchone()
            if not row:
                continue
            if row['cancel_requested'] or row['attempts'] >= row['max_attempts']:
                _terminal(db, row['id'], 'cancelled' if row['cancel_requested'] else 'failed',
                          error=None if row['cancel_requested'] else 'Job retry limit reached.')
                _aggregate(db, row['parent_id'])
                continue
            if row['status'] == 'running':
                _retry(db, row, 'Worker lease expired.')
                _aggregate(db, row['parent_id'])
                continue
            claimed = db.execute('''UPDATE jobs SET status='running',attempts=attempts+1,
                token=%s,worker_id=%s,lease_until=now()+(%s * interval '1 second'),
                updated_at=now(),error=NULL WHERE id=%s RETURNING *''',
                                 (uuid4(), str(worker_id), _lease(lease_seconds), row['id'])).fetchone()
            _aggregate(db, row['parent_id'])
            claimed['job_id'] = str(claimed['id'])
            claimed['claim_token'] = claimed['token']
            return claimed
    return None


def _owned(db, job_id, token):
    _family(db, job_id)
    return db.execute('''SELECT * FROM jobs WHERE id=%s AND token=%s
        AND status='running' AND lease_until>clock_timestamp() FOR UPDATE''',
                      (_uuid(job_id), _uuid(token))).fetchone()


def _ack_cancel(db, row):
    if row['cancel_requested']:
        _terminal(db, row['id'], 'cancelled')
        _aggregate(db, row['parent_id'])
        return True
    return False


def heartbeat(job_id, token, lease_seconds=120):
    with _db() as db:
        row = _owned(db, job_id, token)
        if not row or _ack_cancel(db, row):
            return False
        db.execute("UPDATE jobs SET lease_until=clock_timestamp()+(%s * interval '1 second'),updated_at=now() WHERE id=%s",
                   (_lease(lease_seconds), row['id']))
        return True


def progress(job_id, token, update):
    if not isinstance(update, dict):
        raise ValueError('Progress must be an object')
    with _db() as db:
        row = _owned(db, job_id, token)
        if not row or _ack_cancel(db, row):
            return False
        db.execute('UPDATE jobs SET progress=progress || %s,updated_at=now() WHERE id=%s',
                   (Jsonb(update), row['id']))
        return True


def checkpoint(job_id, token, payload_update):
    """Shallow-merge private durable selection/checkpoint data under the live fence."""
    if not isinstance(payload_update, dict):
        raise ValueError('Checkpoint must be an object')
    with _db() as db:
        row = _owned(db, job_id, token)
        if not row or _ack_cancel(db, row):
            return False
        db.execute('UPDATE jobs SET payload=payload || %s,updated_at=now() WHERE id=%s',
                   (Jsonb(payload_update), row['id']))
        return True


def finish(job_id, token, summary=None, status='complete'):
    if status not in TERMINAL:
        raise ValueError('Finish requires a terminal status')
    with _db() as db:
        row = _owned(db, job_id, token)
        if not row or _ack_cancel(db, row):
            return False
        _terminal(db, row['id'], status, summary)
        _aggregate(db, row['parent_id'])
        return True


def _retry(db, row, error):
    db.execute('''UPDATE jobs SET status='queued',token=NULL,worker_id=NULL,
        lease_until=NULL,error=%s,available_at=now()+(%s * interval '1 second'),
        updated_at=now() WHERE id=%s''', (error, min(60, 2 ** row['attempts']), row['id']))


def fail(job_id, token, error, retryable=True):
    # Never persist exception text: URLs, SQL and provider credentials can occur anywhere.
    safe_error = 'Job execution failed.'
    with _db() as db:
        row = _owned(db, job_id, token)
        if not row or _ack_cancel(db, row):
            return False
        if retryable and row['attempts'] < row['max_attempts']:
            _retry(db, row, safe_error)
        else:
            _terminal(db, row['id'], 'failed', error=safe_error)
        _aggregate(db, row['parent_id'])
        return True


def expand(job_id, token, batches: list[dict]):
    if not isinstance(batches, list) or any(not isinstance(batch, dict) for batch in batches):
        raise ValueError('Batches must be a list of payload objects')
    with _db() as db:
        row = _owned(db, job_id, token)
        if not row or _ack_cancel(db, row):
            return False
        if row['parent_id']:
            raise ValueError('Only root jobs may expand')
        for batch in batches:
            _insert(db, 'analysis_batch', 'analysis', row['user_id'],
                    row['connection_id'], batch, None, row['id'])
        db.execute("""UPDATE jobs SET status='waiting',token=NULL,worker_id=NULL,
            lease_until=NULL,updated_at=now() WHERE id=%s""", (row['id'],))
        _aggregate(db, row['id'])
        return True


class JobCancelled(BaseException):
    """Cooperative cancellation or loss of a fenced claim."""


class JobContext:
    def __init__(self, job):
        self.job = job
        self.job_id = job.get('job_id', job.get('id'))
        self.token = job.get('claim_token', job.get('token'))

    def report(self, update):
        if not progress(self.job_id, self.token, update):
            raise JobCancelled()

    def check(self):
        if not heartbeat(self.job_id, self.token):
            raise JobCancelled()

    def complete(self, summary=None, status='complete'):
        if not finish(self.job_id, self.token, summary, status):
            raise JobCancelled()
