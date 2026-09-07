"""No model/checkpoint loading: exercise the shared vendor normalizer."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor' / 'fa_kara'))
import haruraw2norm as norm


def test_janome_word_readings_and_particles():
    items = norm.process_haruhi_line('宝石に憧れ私は東京へ行く', 'ja')
    words = {i['orig']: i.get('pron') for i in items}
    assert words['宝石'] == 'houseki'
    assert words['憧れ'] == 'akogare'
    assert words['は'] == 'wa'
    assert words['へ'] == 'e'
    assert ''.join(i['orig'] for i in items) == '宝石に憧れ私は東京へ行く'
    assert items == norm.process_haruhi_line('宝石に憧れ私は東京へ行く', 'auto')


def test_chinese_context_before_character_mapping():
    with patch.object(norm, 'pinyin', wraps=norm.pinyin) as contextual:
        items = norm.process_haruhi_line('银行 重庆', 'auto')
    assert [call.args[0] for call in contextual.call_args_list] == ['银行', '重庆']
    assert [(i['orig'], i.get('pron')) for i in items if i.get('pron')] == [
        ('银', 'in'), ('行', 'hang'), ('重', 'chong'), ('庆', 'ching')]


def test_annotations_remain_overrides_in_mixed_scripts():
    for lang in ('auto', 'ja', 'ko', 'es'):
        items = norm.process_haruhi_line('한{宝石|アコガレ}[重庆|hello]', lang)
        assert ''.join(i.get('pron', '') for i in items) == 'hanakogarehello'
        assert ''.join(i['orig'] for i in items) == '한宝石重庆'


def test_ruby_sokuon_across_annotation_boundaries():
    for text in ('{勝|かっ}{手|て}', '{勝|かっ}手'):
        items = norm.process_haruhi_line(text, 'ja')
        assert ''.join(i.get('pron', '') for i in items) == 'katte'


def test_code_switch_and_unknown_surfaces():
    text = '한宝石に憧れ银行重庆 café नमस्ते مرحبا Ж'
    items = norm.process_haruhi_line(text, 'auto')
    assert ''.join(i['orig'] for i in items) == text
    assert next(i for i in items if i['orig'] == '宝石')['pron'] == 'houseki'
    for surface in ('한', 'café', 'नमस्ते', 'مرحبا'):
        assert next(i for i in items if i['orig'] == surface)['pron']
    assert any('Ж' in i['orig'] and not i.get('pron') for i in items)


def test_latin_fallback_keeps_accents_and_avoids_cmu():
    for lang in ('auto', 'es', 'fr', 'ko'):
        with patch.object(norm, 'process_english_word', side_effect=AssertionError('CMU forbidden')):
            items = norm.process_haruhi_line('no café canción cafe\u0301', lang)
        assert ''.join(i['orig'] for i in items) == 'no café canción cafe\u0301'
        assert [i['pron'] for i in items if i.get('pron')] == ['no', 'cafe', 'cancion', 'cafe']
    assert norm.process_haruhi_line('no', 'en')[0]['pron'] == 'no'


def test_han_only_policy_is_run_local():
    chinese = norm.process_haruhi_line('银行', 'auto')
    assert norm.process_haruhi_line('한银行', 'auto')[1:] == chinese
    assert norm.process_haruhi_line('宝石', 'ja')[0] == dict(orig='宝石', type=3, pron='houseki')
