from echora_analysis.settings import get_settings

from types import SimpleNamespace
from unittest.mock import Mock
import sys

import echora_analysis
from echora_analysis import analysis_jobs


def setup_main(monkeypatch):
    main = SimpleNamespace(_load_connection=Mock(return_value=('url','user','password')))
    monkeypatch.setitem(sys.modules, 'echora_analysis.main', main)
    monkeypatch.setattr(echora_analysis, 'main', main, raising=False)
    return SimpleNamespace(check=Mock(), report=Mock(), token='lease')


def test_default_batch_is_128(monkeypatch):
    ctx = setup_main(monkeypatch)
    monkeypatch.delenv('ECHORA_BATCH_SIZE', raising=False)
    get_settings.cache_clear()
    jobs = SimpleNamespace(expand=Mock())
    monkeypatch.setitem(sys.modules, 'echora_analysis.jobs', jobs)
    monkeypatch.setattr(echora_analysis, 'jobs', jobs, raising=False)
    analysis_jobs.execute({'id':'p','kind':'import','user_id':'u','payload':{
        'connection_id':'c','track_ids':[str(i) for i in range(129)]}},ctx)
    batches = jobs.expand.call_args.args[2]
    assert [len(b['track_ids']) for b in batches] == [128,1]


def test_lyrics_stage_precedes_karaoke_even_for_karaoke_backfill(monkeypatch):
    ctx = setup_main(monkeypatch)
    order = []
    def lyrics(*args, **kwargs):
        order.append('lyrics'); return {}
    def karaoke(*args, **kwargs):
        order.append('karaoke'); return {}
    monkeypatch.setitem(sys.modules, 'echora_analysis.lyrics_pipeline', SimpleNamespace(backfill_lyrics=lyrics))
    monkeypatch.setitem(sys.modules, 'echora_analysis.karaoke_pipeline', SimpleNamespace(backfill_karaoke=karaoke))
    analysis_jobs.execute({'kind':'analysis_batch','user_id':'u','payload':{
        'operation':'karaoke_backfill','connection_id':'c','track_ids':['song']}},ctx)
    assert order == ['lyrics','karaoke']
