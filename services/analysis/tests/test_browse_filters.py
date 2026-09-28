import pytest
from fastapi import HTTPException
from echora_analysis.browse_filters import predicates


def test_values_are_bound_not_interpolated():
    clauses, values = predicates(genre="'; DROP TABLE tracks; --", language='ja,en', translation='en', year_from=2000)
    assert 'DROP TABLE' not in ' '.join(clauses)
    assert values == ["'; DROP TABLE tracks; --", 2000, ['ja','en'], 'en']
    assert ' '.join(clauses).count('%s') == len(values)


@pytest.mark.parametrize('vocals', ['instrumental','vocal','female','male','unknown'])
def test_vocal_filters_use_current_aggregate(vocals):
    clauses, values = predicates(vocals=vocals)
    assert 'current_embeddings' in clauses[0]
    assert 'window_index IS NULL' in clauses[0]
    assert not values


def test_unknown_language_and_missing_lyrics():
    clauses, values = predicates(language='unknown,ja', lyrics='missing')
    assert ' OR ' in clauses[0]
    assert 'NOT EXISTS' in clauses[1]
    assert values == [['ja']]


@pytest.mark.parametrize('options', [{'vocals':'bad'}, {'lyrics':'bad'}, {'year_from':2020,'year_to':1990}])
def test_invalid_filters(options):
    with pytest.raises(HTTPException): predicates(**options)
