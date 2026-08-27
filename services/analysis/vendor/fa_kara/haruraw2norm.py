from janome.tokenizer import Tokenizer
import nltk
from nltk.corpus import cmudict
import pykakasi
import pyphen
import pypinyin
from pypinyin import pinyin, Style
from uroman import Uroman
import re
import unicodedata
# import string

kks = pykakasi.kakasi()
tokenizer = Tokenizer()
tail_pron = '' # 'h'

phoneme_map = {
    'AA': 'a', 'AE': 'a', 'AH': 'a', 'AO': 'o', 'AW': 'au', 'AY': 'ai',
    'B': 'b', 'CH': 'ch', 'D': 'd', 'DH': 'z', 'EH': 'e', 'ER': 'a',
    'EY': 'ei', 'F': 'f', 'G': 'g', 'HH': 'h', 'IH': 'i', 'IY': 'i',
    'JH': 'j', 'K': 'k', 'L': 'r', 'M': 'm', 'N': 'n', 'NG': 'ng',
    'OW': 'o', 'OY': 'oi', 'P': 'p', 'R': 'r', 'S': 's', 'SH': 'sh',
    'T': 't', 'TH': 's', 'UH': 'u', 'UW': 'u', 'V': 'v', 'W': 'w',
    'Y': 'y', 'Z': 'z', 'ZH': 'j'
}
PINYIN_TO_PHONETIC = {
    # 声母
    'b': 'b', 'p': 'p', 'm': 'm', 'f': 'f',
    'd': 'd', 't': 't', 'n': 'n', 'l': 'r',
    'g': 'g', 'k': 'k', 'h': 'h',
    'j': 'j', 'q': 'ch', 'x': 'sh',
    'zh': 'j', 'ch': 'ch', 'sh': 'sh', 'r': 'r',
    'z': 'z', 'c': 'ts', 's': 's',
    'y': 'y', 'w': 'w',
    
    # 韵母
    'a': 'a', 'o': 'o', 'e': 'e', 'i': 'i', 'u': 'u', 'ü': 'yu',
    'ai': 'ai', 'ei': 'ei', 'ao': 'ao', 'ou': 'ou',
    'an': 'an', 'en': 'en', 'ang': 'ang', 'eng': 'eng', 'ong': 'ong',
    'ia': 'ya', 'ie': 'ye', 'iao': 'yao', 'iu': 'yu', 
    'ian': 'yan', 'in': 'in', 'iang': 'yang', 'ing': 'ing', 'iong': 'yong',
    'ua': 'wa', 'uo': 'wo', 'uai': 'wai', 'ui': 'wei',
    'uan': 'wan', 'un': 'wen', 'uang': 'wang', 'ueng': 'weng',
    'üe': 'yue', 'üan': 'yuan', 'ün': 'yun',
    
    'er': 'a', 'io': 'yo', 'o': 'wo', 'e': 'e'
}
try:
    cmu_dict = cmudict.dict()
except LookupError:
    nltk.download('cmudict')
    cmu_dict = cmudict.dict()
eng_dic = pyphen.Pyphen(lang='en_US')
uroman = Uroman()

newnums = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩',
           '⑪', '⑫', '⑬', '⑭', '⑮', '⑯', '⑰', '⑱', '⑲', '⑳',
           '㉑', '㉒', '㉓', '㉔', '㉕', '㉖', '㉗', '㉘', '㉙', '㉚']

def normalize_numbers(text):
    """将字符串中的各种数字字符转换为半角阿拉伯数字"""
    # 全角数字转半角
    fullwidth_to_half = str.maketrans('０１２３４５６７８９', '0123456789')
    text = text.translate(fullwidth_to_half)
    
    # 特殊数字转换映射表
    number_map = {
        # 分数
        '½': '0.5', '⅓': '0.333', '⅔': '0.666', '¼': '0.25', '¾': '0.75',
        '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8', '⅙': '0.166',
        '⅚': '0.833', '⅛': '0.125', '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        # 罗马数字
        'Ⅰ': '1', 'Ⅱ': '2', 'Ⅲ': '3', 'Ⅳ': '4', 'Ⅴ': '5',
        'Ⅵ': '6', 'Ⅶ': '7', 'Ⅷ': '8', 'Ⅸ': '9', 'Ⅹ': '10',
        'Ⅺ': '11', 'Ⅻ': '12', 'Ⅼ': '50', 'Ⅽ': '100', 'Ⅾ': '500', 'Ⅿ': '1000',
        # 汉字数字
        '零': '0', '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
        '六': '6', '七': '7', '八': '8', '九': '9', '十': '10', '百': '100',
        '千': '1000', '万': '10000', '亿': '100000000',
        # 上标/下标
        '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9',
        '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4', '₅': '5', '₆': '6', '₇': '7', '₈': '8', '₉': '9'
    }
    
    # 构建转换表
    trans_table = str.maketrans(number_map)
    return text.translate(trans_table)

def number_to_english(number_str):
    """将数字字符串转换为英文单词"""
    try:
        if '.' in number_str:
            num = float(number_str)
        else:
            num = int(number_str)
    except ValueError:
        print('Unable to process number "'+number_str+'"...')
        return tail_pron
    
    ones = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
            "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
            "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    
    if isinstance(num, float):
        integer_part = int(num)
        decimal_part = round(num - integer_part, 3)
        integer_words = number_to_english(str(integer_part)) if integer_part > 0 else ""
        
        # 处理小数部分
        decimal_str = f"{decimal_part:.3f}"[2:] # 获取小数点后三位
        decimal_words = " point"
        for digit in decimal_str:
            if digit == '0' and not decimal_words.endswith(' zero'):
                decimal_words += " zero"
            elif digit != '0':
                decimal_words += " " + ones[int(digit)]
        return (integer_words + decimal_words).strip()
    
    if num < 0:
        return "minus " + number_to_english(str(abs(num)))
    
    if num < 20:
        return ones[num]
    
    if num < 100:
        return tens[num // 10] + ((" " + ones[num % 10]) if num % 10 != 0 else "")
    
    if num < 1000:
        return ones[num // 100] + " hundred" + (" and " + number_to_english(str(num % 100)) if num % 100 != 0 else "")
    
    # 处理1000及以上
    scales = [
        (10**12, "trillion"),
        (10**9, "billion"),
        (10**6, "million"),
        (10**3, "thousand")
    ]
    
    for scale_value, scale_name in scales:
        if num >= scale_value:
            return number_to_english(str(num // scale_value)) + " " + scale_name + (" " + number_to_english(str(num % scale_value)) if num % scale_value != 0 else "")
    
    print('Unable to process number "'+number_str+'"...')
    return tail_pron

def is_english(text):
    return bool(re.match(r'^[a-zA-Z]+$', text))

def is_english_punctuation(char):
    return char == "'" # in string.punctuation

def is_kanji(char):
    return ('\u4E00' <= char <= '\u9FFF' or '\u3400' <= char <= '\u4DBF' or
            '\uF900' <= char <= '\uFAFF' or char == '\u3005')

def is_hiragana(char):
    return '\u3040' <= char <= '\u309F'

def is_katakana(char):
    return '\u30A0' <= char <= '\u30FF'

def is_kana(char):
    for i in char:
        if not is_hiragana(i) and not is_katakana(i) or i in ['・', '゠']: # , 'ー'
            return False
    return True

def is_number(char):
    # 目前支持判断单个字符
    if char in newnums:
        return False
    return char.isdigit() # isnumeric

def get_norm_ruby(item):
    # 1:英文, 2:注音结构, 3:东亚文字（假名、中文汉字）, 4:数字, 5:隐式辅助注音
    if item['type'] == 2:
        return item['ruby']
    if item['type'] in (3, 5):
        return item['orig'].lower() if is_english(item['orig']) else item['orig']
    if item['type'] == 1:
        return ''.join([char for char in item['orig'].strip() if not is_english_punctuation(char)]).lower()
    return tail_pron

def get_norm_surface(item):
    if item['type'] in (1,2,3,4,5):
        return item['orig']
    return ''

def min_error_split(target_list, s):
    n = len(s)
    m = len(target_list)
    
    # 初始化 DP 表
    # dp[i][k] 表示处理到字符串位置 i 时，已匹配 k 个目标项的最小错误数
    dp = [[float('inf')] * (m + 1) for _ in range(n + 1)]
    # 记录回溯路径
    backtrack = [[None] * (m + 1) for _ in range(n + 1)]
    
    # 初始状态：空字符串匹配 0 个目标项
    dp[0][0] = 0
    
    # 动态规划填表
    for i in range(n + 1):
        for k in range(m + 1):
            if dp[i][k] == float('inf'):
                continue
                
            # 尝试匹配下一个目标项
            if k < m:
                target = target_list[k]
                # 处理空字符串目标项
                if target == "":
                    # 不消耗任何字符
                    if dp[i][k] < dp[i][k + 1]:
                        dp[i][k + 1] = dp[i][k]
                        backtrack[i][k + 1] = (i, k, "")
                else:
                    # 尝试所有可能的子串
                    for j in range(i + 1, n + 1):
                        segment = s[i:j]
                        # 计算错误成本（0~1 匹配~不匹配）
                        if segment == target:
                            cost = 0
                        elif target == tail_pron:
                            cost = min(len(segment)*0.1, 1)
                        elif segment=='wa' and target=='ha' or segment=='e' and target=='ha':
                            # 此处可添加当て字
                            cost = 0.1
                        else:
                            cost = 1
                        new_cost = dp[i][k] + cost
                        if new_cost < dp[j][k + 1]:
                            dp[j][k + 1] = new_cost
                            backtrack[j][k + 1] = (i, k, segment)
    
    # 回溯找到最佳分割
    if dp[n][m] == float('inf'):
        return None  # 无有效分割
    
    # 从终点回溯
    result = []
    i, k = n, m
    while k > 0:
        prev_i, prev_k, segment = backtrack[i][k]
        result.append(segment)
        i, k = prev_i, prev_k
    
    # 反转结果（因为是从后往前回溯）
    return result[::-1]

def sylla_split(kana_str, sokuon_split=False, hatsuon_split=True):
    kana_list = []
    i = 0
    n = len(kana_str)
    while i < n:
        current_char = kana_str[i]
        small_kana = ['ゃ', 'ゅ', 'ょ', 'ぁ', 'ぃ', 'ぅ', 'ぇ', 'ぉ', 'ー',
                      'ャ', 'ュ', 'ョ', 'ァ', 'ィ', 'ゥ', 'ェ', 'ォ']
        if not sokuon_split: small_kana += ['っ', 'ッ']
        if not hatsuon_split: small_kana += ['ん', 'ン']
        if current_char in small_kana:
            if i > 0:
                kana_list[-1] += current_char
            else:
                kana_list.append(current_char)
            i += 1
        else:
            kana_list.append(current_char)
            i += 1
    return kana_list

def convert_phoneme(ph):
    """去除音素中的重音标记并映射为罗马音"""
    base_ph = ph.rstrip('012') # 移除数字重音标记
    return phoneme_map.get(base_ph, '')

def split_into_syllables_en(phonemes):
    """将英语音素序列拆分为音节"""
    vowels = ['AA', 'AE', 'AH', 'AO', 'AW', 'AY', 'EH', 'ER', 'EY', 
              'IH', 'IY', 'OW', 'OY', 'UH', 'UW']
    vowel_positions = []
    # 识别元音位置
    for i, ph in enumerate(phonemes):
        base_ph = ph.rstrip('012')
        if base_ph in vowels:
            vowel_positions.append(i)
    if not vowel_positions: return [phonemes]
    
    syllables = []
    prev_vowel_idx = -1

    # 按元音位置拆分音节
    for i, vowel_idx in enumerate(vowel_positions):
        if i == 0:
            # 首个音节
            onset = phonemes[:vowel_idx]
            vowel = [phonemes[vowel_idx]]
            syllables.append(onset + vowel)
            prev_vowel_idx = vowel_idx
        else:
            # 获取两个元音之间的辅音序列
            consonants = phonemes[prev_vowel_idx + 1 : vowel_idx]
            if consonants:
                onset_start = 0
                # 最大节首辅音原则
                if len(consonants) > 1:
                    # 将第一个辅音分配给前一个音节
                    syllables[-1].append(consonants[0])
                    onset_start = 1
                # 剩余辅音分配给后一个音节
                onset = consonants[onset_start:]
                vowel = [phonemes[vowel_idx]]
                syllables.append(onset + vowel)
            else:
                # 没有辅音，直接开始新音节
                syllables.append([phonemes[vowel_idx]])
            prev_vowel_idx = vowel_idx
    
    # 添加尾部剩余辅音到最后一个音节
    if prev_vowel_idx < len(phonemes) - 1:
        trailing = phonemes[prev_vowel_idx + 1:]
        syllables[-1].extend(trailing)
    
    return syllables

def align_syllables_en(a, b):
    """简单对齐表面音节和发音音节"""
    if len(a) > len(b):
        long_list, short_list = a, b
        long_to_short = True
    elif len(b) > len(a):
        long_list, short_list = b, a
        long_to_short = False
    else:
        return list(zip(a, b))
    
    print("Ignored errors when dealing with the pronunciation of '"+''.join(a)+"'...")
    n_segments = len(short_list)
    total_elements = len(long_list)
    
    # 计算每段应包含的元素数
    base_size = total_elements // n_segments
    extra = total_elements % n_segments
    
    merged_list = []
    start = 0
    for i in range(n_segments):
        seg_size = base_size + (1 if i >= n_segments-extra else 0) # 后 extra 段多一个元素
        segment = long_list[start:start+seg_size]
        merged = ''.join(segment)
        merged_list.append(merged)
        start += seg_size

    if long_to_short:
        return list(zip(merged_list, short_list))
    else:
        return list(zip(short_list, merged_list))

def process_english_word(word, surf=True):
    if word=='a':
        return [('a', 'a')]
    elif word=='A':
        return [('A', 'ei')]

    hyphenated = eng_dic.inserted(word)
    surface_syllables = hyphenated.split('-')

    word_lower = word.lower()
    # if word_lower=='you':
    #     return [(word, 'iyu')]
    if word_lower not in cmu_dict:
        print("Word '"+word+"' not in the dictionary...")
        direct_syllables = [i.replace("'", '').lower() for i in surface_syllables]
        return list(zip(surface_syllables, direct_syllables))
    
    phonemes = cmu_dict[word_lower][0]
    syllables_phonemes = split_into_syllables_en(phonemes)
    syllables_romaji = []
    for syl in syllables_phonemes:
        romaji = ''.join(convert_phoneme(p) for p in syl) # p.rstrip('012').lower()
        syllables_romaji.append(romaji)
    
    if not surf:
        return ''.join(syllables_romaji)

    # 对齐表面音节和发音音节
    return align_syllables_en(surface_syllables, syllables_romaji)

def convert_pinyin_to_phonetic(pinyin_str):
    """将拼音转换为表音拼写，赞美AI"""
    # 移除音调数字
    pinyin_str = re.sub(r'[1-5]', '', pinyin_str)
    
    # 特殊整体音节处理
    special_cases = {
        'zhi': 'jru', 'chi': 'chu', 'shi': 'shu', 'ri': 'ru',
        'zi': 'zu', 'ci': 'tsu', 'si': 'su',
        'yi': 'i', 'wu': 'u', 'yu': 'yu',
        'ye': 'ye', 'yue': 'yue', 'yuan': 'yuen',
        'yin': 'in', 'yun': 'yun', 'ying': 'ing'
    }
    
    if pinyin_str in special_cases:
        return special_cases[pinyin_str]
    
    # 分离声母和韵母
    initials = ['b', 'p', 'm', 'f', 'd', 't', 'n', 'l', 'g', 'k', 'h', 
                'j', 'q', 'x', 'zh', 'ch', 'sh', 'r', 'z', 'c', 's', 'y', 'w']
    
    # 找出最长的匹配声母
    found_initial = ""
    for initial in sorted(initials, key=len, reverse=True):
        if pinyin_str.startswith(initial):
            found_initial = initial
            break
    
    # 获取韵母部分
    final = pinyin_str[len(found_initial):] if found_initial else pinyin_str
    
    # 转换声母和韵母
    phonetic_initial = PINYIN_TO_PHONETIC.get(found_initial, found_initial)
    phonetic_final = PINYIN_TO_PHONETIC.get(final, final)
    
    # 特殊规则处理
    # 1. i/u/ü 开头的韵母前没有声母时，添加y/w
    if not found_initial:
        if final.startswith('i'):
            phonetic_final = 'y' + phonetic_final
        elif final.startswith('u'):
            phonetic_final = 'w' + phonetic_final
        elif final.startswith('ü'):
            phonetic_final = 'yu' + phonetic_final[2:] if len(phonetic_final) > 2 else 'yu'
    
    # 2. j/q/x 后的 ü 去掉两点
    if found_initial in ['j', 'q', 'x'] and final.startswith('ü'):
        phonetic_final = 'u' + phonetic_final[2:] if len(phonetic_final) > 2 else 'u'
    
    # 组合声母和韵母
    return phonetic_initial + phonetic_final

def hanzi_to_phonetic(text, heteronym=False):
    """将汉字文本转换为表音拼写，可以结合语义处理句子但目前只用来处理单字"""
    # 获取拼音
    pinyin_list = pinyin(text, style=Style.TONE3, heteronym=heteronym)
    
    result = []
    for item in pinyin_list:
        if not item: # 非汉字字符
            result.append("")
            continue
            
        # 处理多音字
        pronunciations = []
        for py in item:
            phonetic_form = convert_pinyin_to_phonetic(py)
            pronunciations.append(phonetic_form)
        
        # 去重并选择第一个发音
        unique_prons = list(dict.fromkeys(pronunciations))
        result.append(unique_prons[0])
    return result

def is_hangul(char):
    return '\uac00' <= char <= '\ud7a3' or '\u1100' <= char <= '\u11ff'


def is_arabic_script(char):
    return ('\u0600' <= char <= '\u06ff' or '\u0750' <= char <= '\u077f'
            or '\u08a0' <= char <= '\u08ff')


def is_devanagari(char):
    return '\u0900' <= char <= '\u097f' or '\ua8e0' <= char <= '\ua8ff'


def is_gurmukhi(char):
    return '\u0a00' <= char <= '\u0a7f'


def process_haruhi_line(line, lang='jaen', sokuon_split=False, hatsuon_split=True):

    def haruhi_eng_pron_func(result_list):
        # 英语分音节注音、数字注音
        new_list = []
        for item in result_list:
            if item.get('type')==1:
                new_elements = get_norm_surface(item)
                new_list.extend([{'orig': char, 'type': 1, 'pron': pron} for char, pron in process_english_word(new_elements)])
            elif item.get('type')==4:
                en_nums = number_to_english(get_norm_surface(item)).split(' ')
                new_list.append({'orig': get_norm_surface(item), 'type': 4, 'pron': ''.join([process_english_word(i, surf=False) for i in en_nums])})
            else:
                new_list.append(item)
        return new_list

    if lang == 'auto': # 后续考虑langdetect
        if any(is_hangul(char) for char in line):
            lang = 'ko'
        elif any(is_arabic_script(char) for char in line):
            lang = 'ur'
        elif any(is_devanagari(char) or is_gurmukhi(char) for char in line):
            lang = 'indic'
        elif any(is_hiragana(char) or is_katakana(char) for char in line):
            lang = 'jaen'
        else:
            lang = 'zhen'

    result = []
    if lang in ['ja', 'jaen']:
        tokens = re.split(r'(\{.*?\}|\[.*?\])', line)
        
        for token in tokens:
            if not token:
                continue
            # 处理振假名结构 {漢字|假名}
            if token.startswith('{') and token.endswith('}'):
                content = token[1:-1]
                parts = content.split('|')
                assert len(parts) == 2, f"注音格式错误：{token}"
                kanji, ruby_text = parts
                ruby_text = sylla_split(ruby_text, sokuon_split, hatsuon_split)
                assert len(ruby_text)>=1, "振假名为空"
                result.append({
                    'orig': kanji,
                    'type': 2,
                    'ruby': ruby_text[0]
                })
                if len(ruby_text)>=2:
                    for i in range(1, len(ruby_text)):
                        result.append({
                            'orig': '',
                            'type': 2,
                            'ruby': ruby_text[i]
                        })
            # 隐式注音 [字符|romaji]
            elif token.startswith('[') and token.endswith(']'):
                content = token[1:-1]
                parts = content.split('|')
                assert len(parts) == 2, f"注音格式错误：{token}"
                kanji, ruby_text = parts
                assert is_english(ruby_text), f"辅助注音格式错误：{token}"
                result.append({
                    'orig': kanji,
                    'type': 5,
                    'pron': ruby_text
                })
            # 处理普通字符
            else:
                token = sylla_split(token, sokuon_split, hatsuon_split)
                if lang == 'ja':
                    for char in token:
                        if is_kana(char) or is_kanji(char) or is_english(char):
                            result.append({'orig': char, 'type': 3})
                        # elif is_number(char):
                        #     result.append({'orig': char, 'type': 4})
                        else:
                            result.append({'orig': char, 'type': 0})
                elif lang == 'jaen':
                    for char in token:
                        if is_kana(char) or is_kanji(char):
                            result.append({'orig': char, 'type': 3})
                        elif is_english(char) or is_english_punctuation(char):
                            if result and result[-1].get('type')==1:
                                result[-1]['orig'] += char
                            elif is_english(char):
                                result.append({'orig': char, 'type': 1})
                            else:
                                result.append({'orig': char, 'type': 0})
                        elif is_number(char):
                            if result and result[-1].get('type')==4:
                                result[-1]['orig'] += char
                            else:
                                result.append({'orig': char, 'type': 4})
                        else:
                            result.append({'orig': char, 'type': 0})
        
        # 英语分音节注音、数字注音
        result = haruhi_eng_pron_func(result)

        # 标注单字罗马音
        postpron = None        
        for i in range(len(result)-1, -1, -1):
            if result[i].get('type') in (0, 2, 3):
                ruby_now = get_norm_ruby(result[i])
                if result[i].get('type')!=0 and ruby_now and ruby_now[-1] in ('っ', 'ッ'):
                    try:
                        pron = postpron[0]
                    except:
                        pron = 'h' # tail_pron
                    else:
                        if pron=='c': pron = 't'
                    finally:
                        pron = kks.convert(ruby_now[:-1])[0]['hepburn'] + pron
                else:
                    pron = kks.convert(ruby_now)[0]['hepburn']
                result[i]['pron'] = pron.replace('-', '') # 长音的错误token
            postpron = result[i]['pron']
        
        # 通用读音修正（は，へ）
        line_pron_list = [item['pron'] for item in result]
        line_surface = ''.join([get_norm_surface(i) for i in result])
        line_roma = ''.join([i['hepburn'] for i in kks.convert(''.join([token.phonetic for token in tokenizer.tokenize(line_surface)]))])
        line_roma_proc = min_error_split(line_pron_list, line_roma)
        for i in range(len(result)):
            if result[i]['type']==3:
                try:
                    if result[i]['orig']=='は' and line_roma_proc[i]=='wa':
                        result[i]['pron'] = 'wa'
                    elif result[i]['orig']=='へ' and line_roma_proc[i]=='e':
                        result[i]['pron'] = 'e'
                except:
                    print('Ignored errors when trying to correct ha and he...')
    elif lang == 'ko':
        for char in line:
            if is_hangul(char):
                pronunciation = uroman.romanize_string(char).replace('-', '').replace(' ', '')
                result.append({'orig': char, 'type': 5, 'pron': pronunciation})
            elif is_english(char) or is_english_punctuation(char):
                if result and result[-1].get('type') == 1:
                    result[-1]['orig'] += char
                elif is_english(char):
                    result.append({'orig': char, 'type': 1})
                else:
                    result.append({'orig': char, 'type': 0})
            elif is_number(char):
                if result and result[-1].get('type') == 4:
                    result[-1]['orig'] += char
                else:
                    result.append({'orig': char, 'type': 4})
            else:
                result.append({'orig': char, 'type': 0})
        result = haruhi_eng_pron_func(result)

    elif lang in ('ur', 'hi', 'pa', 'indic'):
        if lang == 'ur':
            script_test = is_arabic_script
        elif lang == 'hi':
            script_test = is_devanagari
        elif lang == 'pa':
            script_test = is_gurmukhi
        else:
            script_test = lambda char: is_devanagari(char) or is_gurmukhi(char)
        for char in line:
            if script_test(char) and unicodedata.category(char)[0] in {'L', 'M'}:
                if result and result[-1].get('type') == 6:
                    result[-1]['orig'] += char
                else:
                    result.append({'orig': char, 'type': 6})
            elif is_english(char) or is_english_punctuation(char):
                if result and result[-1].get('type') == 1:
                    result[-1]['orig'] += char
                elif is_english(char):
                    result.append({'orig': char, 'type': 1})
                else:
                    result.append({'orig': char, 'type': 0})
            elif is_number(char):
                if result and result[-1].get('type') == 4:
                    result[-1]['orig'] += char
                else:
                    result.append({'orig': char, 'type': 4})
            else:
                result.append({'orig': char, 'type': 0})
        for item in result:
            if item.get('type') == 6:
                item['pron'] = uroman.romanize_string(item['orig']).replace('-', '').replace(' ', '')
        result = haruhi_eng_pron_func(result)

    elif lang == 'zhen':
        tokens = re.split(r'(\[.*?\])', line)
        
        for token in tokens:
            if not token:
                continue
            if token.startswith('[') and token.endswith(']'):
                content = token[1:-1]
                parts = content.split('|')
                assert len(parts) == 2, f"注音格式错误：{token}"
                kanji, ruby_text = parts
                assert is_english(ruby_text), f"辅助注音格式错误：{token}"
                result.append({
                    'orig': kanji,
                    'type': 5,
                    'pron': ruby_text
                })
            else:
                for char in token:
                    if is_kanji(char):
                        result.append({'orig': char, 'type': 3, 'pron': hanzi_to_phonetic(char)[0]})
                    elif is_english(char) or is_english_punctuation(char):
                        if result and result[-1].get('type')==1:
                            result[-1]['orig'] += char
                        elif is_english(char):
                            result.append({'orig': char, 'type': 1})
                        else:
                            result.append({'orig': char, 'type': 0})
                    elif is_number(char):
                        if result and result[-1].get('type')==4:
                            result[-1]['orig'] += char
                        else:
                            result.append({'orig': char, 'type': 4})
                    else:
                        result.append({'orig': char, 'type': 0})

        # 数字先给英语吧
        result = haruhi_eng_pron_func(result)

    return result

if __name__=='__main__':
    input_string = "{阻|はば}むも[の|n]は{無|な}い {身|み}{勝|かっ}{手|て}に More love, more jump!"
    parsed = process_haruhi_line(input_string)
    print(parsed)