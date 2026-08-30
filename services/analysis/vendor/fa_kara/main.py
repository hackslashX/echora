import argparse
from functools import partial
import json
import os
import soundfile as sf
import re
import subprocess
import time

# import ass2lrc
import haruraw2norm as hn
import lrcfmt
import norm2ass
from norm2lrc import process_main, process_ruby_V2, process_rlf
from utils_audio import (
    non_silent_recog, time_stretch_audio, func_tail_correct_v250615
)
from utils_basic import (
    split_long_segments,
    non_silent_head_adjust,
    func_tail_correct_v250611,
)

def main(argv=None):
    start_time = time.time()
    script_dir = os.path.dirname(os.path.realpath(__file__))
    parser = argparse.ArgumentParser(description='可选参数')
    parser.add_argument('-x', '--sokuon_split', type=int, default=0, help='是否将促音与前一字符拆开')
    parser.add_argument('-n', '--hatsuon_split', type=int, default=1, help='是否将拨音与前一字符拆开')
    parser.add_argument('-v', '--audio_speedx', type=float, default=1, help='推理时使用的音频倍速')
    parser.add_argument('-p', '--path_io', default='', help='输入输出文件目录。基于主文件所在目录，支持绝对路径或相对路径')
    parser.add_argument('-ia', '--input_audio', default=None, help='输入音频文件名')
    parser.add_argument('-it', '--input_text', default='i.txt', help='输入歌词文件名')
    parser.add_argument('-t', '--tail_correct', type=int, default=-999, help='尾音拖长选项')
    parser.add_argument('-tl', '--tail_limit_window', type=float, default=0.8, help='全曲静音检测窗口时长，单位：秒')
    parser.add_argument('-tp', '--tail_thres_pct', type=float, default=10, help='尾音阈值百分位数，单位：％。以音频能量前“百分位数”的一定比例作为静音检测阈值')
    parser.add_argument('-tr', '--tail_thres_ratio', type=float, default=0.1, help='尾音阈值比例。以音频能量前百分位数的一定“比例”作为静音检测阈值')
    parser.add_argument('--offset', type=int, default=-150, help='输出ruby歌词文件中Offset标签的偏移值')
    parser.add_argument('--bpm', type=float, default=60, help='歌曲的BPM，导唱指示灯用')
    parser.add_argument('--bpb', type=int, default=3, help='导唱指示灯的符号个数')
    parser.add_argument('--lang', default='auto', help='歌词语言')
    parser.add_argument('-f', '--txt_format', default='hrh', help='歌词文本格式')
    parser.add_argument('-cl', '--characters_per_line', type=int, default=0, help='输出文件每行最大字数')
    parser.add_argument('--no-gpu', action='store_false', dest='use_gpu', default=True, help='禁用GPU加速')
    parser.add_argument('-m', '--model', type=str.lower, default='mms', choices=['mms', 'yohane'], help='底层模型选择')
    parser.add_argument('-hf', '--hf_model_path', default=None, help='HuggingFace模型ID或本地路径')
    parser.add_argument('--head_correct', type=int, default=-999, help='是否进行静音检测')
    parser.add_argument('--timeline_json', default=None, help='Source lyric line timestamps for anchored alignment')
    parser.add_argument('--refine_all_lines', action='store_true', help='Retry every line inside its source-cued interval')
    parser.add_argument('--duration_aware_priors', action='store_true', help='Guide inner token onsets across each source line')
    parser.add_argument('--reference_audio', default=None, help='Original mix for dual-audio line refinement')
    parser.add_argument('--separate_vocals', action='store_true', help='Align a persistent Demucs vocal stem')
    args = parser.parse_args(argv)
    sokuon_split = args.sokuon_split
    hatsuon_split = args.hatsuon_split
    audio_speed = args.audio_speedx
    user_path = args.path_io
    user_audio_path = args.input_audio
    user_text_path = args.input_text
    tail_correct = args.tail_correct
    head_correct = args.head_correct
    silent_window_s = args.tail_limit_window
    tail_thres_pct = args.tail_thres_pct
    tail_thres_ratio = args.tail_thres_ratio
    ruby_tag_offset = args.offset
    bpm = args.bpm
    beats_per_bar = args.bpb
    lrc_language = args.lang.lower()
    txt_format = args.txt_format.lower()
    output_characters_per_line = args.characters_per_line
    align_use_gpu = True if args.use_gpu else False
    hf_model_path = args.hf_model_path
    if hf_model_path is not None:
        fa_model_select = 'yohane_hf'
    elif args.model == 'yohane':
        fa_model_select = 'yohane_hf'
        hf_model_path = 'NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn'
    else:
        fa_model_select = 'MMS_FA_torch'
    if fa_model_select == 'MMS_FA_torch':
        if tail_correct==-999: tail_correct = 3
        if head_correct==-999: head_correct = 1
    elif fa_model_select == 'yohane_hf':
        if tail_correct==-999: tail_correct = 0
        if head_correct==-999: head_correct = 0

    real_io_path = os.path.normpath(user_path) if os.path.isabs(user_path) else os.path.normpath(os.path.join(script_dir, user_path))
    if not os.path.exists(real_io_path):
        os.makedirs(real_io_path)
    input_text_path = os.path.normpath(os.path.join(real_io_path, user_text_path))
    if user_audio_path:
        input_audio_path = os.path.normpath(os.path.join(real_io_path, user_audio_path))
    elif os.path.exists(os.path.normpath(os.path.join(real_io_path, 'i.wav'))):
        input_audio_path = os.path.normpath(os.path.join(real_io_path, 'i.wav'))
    else:
        input_audio_path = os.path.normpath(os.path.join(real_io_path, 'i.mp3'))

    print('Loading files...')
    result_list = []
    with open(input_text_path, 'r', encoding='utf-8') as file:
        if txt_format=='uta':
            utat_str = ''
            for line in file:
                utat_str += line
            file = lrcfmt.utat_process(utat_str)
        for line in file:
            if txt_format=='moe':
                line = lrcfmt.moeg_process_line(line)
            if line.strip():
                result_list.extend(hn.process_haruhi_line(line, lrc_language, sokuon_split, hatsuon_split))
    if not result_list:
        raise ValueError("Lyrics contain no alignable text")
    if result_list[-1]['orig']!='\n':
        result_list.append({'orig': '\n', 'type': 0, 'pron': ''})

    if tail_correct in (1, 2): # 不建议使用
        result_list = func_tail_correct_v250611(result_list, tail_correct)

    alignment_tokens = []
    alignment_token_lines = [[]]
    token_to_index_map = {}
    for i, item in enumerate(result_list):
        if item.get('orig') == '\n':
            alignment_token_lines.append([])
        elif 'pron' in item and item['pron']:
            alignment_tokens.append(item['pron'])
            alignment_token_lines[-1].append(item['pron'])
            token_to_index_map[len(alignment_tokens) - 1] = i
    if alignment_token_lines and not alignment_token_lines[-1]:
        alignment_token_lines.pop()

    for item in alignment_tokens:
        if hn.is_english(item):
            continue
        else:
            print(f"alignment_tokens可能包含错误数据{item}")

    end_time = time.time()
    print("Lyrics text analysis executed in", round(end_time - start_time, 3), "seconds")

    try:
        audio_channels, sr = sf.read(input_audio_path, dtype='float32', always_2d=True)
    except sf.LibsndfileError:
        decoded_audio_path = os.path.join(os.path.dirname(input_audio_path), "decoded.wav")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", input_audio_path,
             "-vn", "-acodec", "pcm_f32le", decoded_audio_path],
            check=True,
        )
        audio_channels, sr = sf.read(decoded_audio_path, dtype='float32', always_2d=True)
    input_sr = sr
    reference_audio = audio_channels.mean(axis=1) if args.separate_vocals else None
    if args.separate_vocals:
        if os.environ.get("FA_KARA_SINGLE_VOCAL_CHECKPOINT", "true").lower() == "true":
            from separate_vocals import separate_vocals_single_checkpoint as separate_vocals
        else:
            from separate_vocals import separate_vocals
        audio_file, sr = separate_vocals(audio_channels, sr, use_gpu=align_use_gpu)
    else:
        audio_file = audio_channels.mean(axis=1)
    non_silent_ranges = (
        non_silent_recog(audio_file, sr, silent_window_s, tail_thres_pct, tail_thres_ratio)
        if head_correct else []
    )

    def get_align_function(model_name):
        'Select FA model'
        if model_name == 'MMS_FA_torch':
            from align import align_audio_with_text
            return align_audio_with_text
        if model_name == 'yohane_hf':
            from align_yohane import align_audio_with_text
            return partial(align_audio_with_text, hf_model_id=hf_model_path)
        raise ValueError(f"Unsupported FA model: '{model_name}'. ")

    align_func = get_align_function(fa_model_select) # TODO: 面向对象方法实现

    y_processed = time_stretch_audio(audio_file, audio_speed)
    reference_processed = None
    if args.reference_audio:
        reference_channels, reference_sr = sf.read(args.reference_audio, dtype='float32', always_2d=True)
        reference_audio = reference_channels.mean(axis=1)
        if reference_sr != sr:
            raise ValueError("reference audio sample rate must match alignment audio")
    if reference_audio is not None:
        if args.separate_vocals and input_sr != sr:
            import librosa
            reference_audio = librosa.resample(reference_audio, orig_sr=input_sr, target_sr=sr)
        reference_processed = time_stretch_audio(reference_audio, audio_speed)
    print('Adding timelines...')
    if args.timeline_json:
        with open(os.path.join(real_io_path, args.timeline_json), 'r', encoding='utf-8') as timeline_file:
            timeline = json.load(timeline_file)
        if len(timeline) != len(alignment_token_lines):
            raise ValueError(f"Timeline has {len(timeline)} lines but parsed lyrics have {len(alignment_token_lines)}")
        timed_token_lines = [(tokens, line) for tokens, line in zip(alignment_token_lines, timeline) if tokens]
        if fa_model_select == 'MMS_FA_torch':
            from align_yohane import align_audio_with_timeline_mms
            alignment_results = align_audio_with_timeline_mms(
                y_processed, [tokens for tokens, _ in timed_token_lines],
                [line['start_ms'] for _, line in timed_token_lines],
                sr=sr, speed=audio_speed, use_gpu=align_use_gpu,
            )
        else:
            from align_yohane import align_audio_with_timeline
            alignment_results = align_audio_with_timeline(
                y_processed, [tokens for tokens, _ in timed_token_lines],
                [line['start_ms'] for _, line in timed_token_lines],
                sr=sr, speed=audio_speed, use_gpu=align_use_gpu, hf_model_id=hf_model_path,
                refine_all_lines=args.refine_all_lines,
                duration_aware_priors=args.duration_aware_priors,
                reference_audio=reference_processed,
            )
    else:
        alignment_results = align_func(y_processed, alignment_tokens, non_silent_ranges, sr, audio_speed, use_gpu=align_use_gpu)

    if len(alignment_results) != len(alignment_tokens):
        raise RuntimeError(
            f"Alignment returned {len(alignment_results)} tokens for {len(alignment_tokens)} inputs"
        )
    for i, result in enumerate(alignment_results):
        original_index = token_to_index_map[i]
        result_list[original_index]['start'] = result['start']
        result_list[original_index]['end'] = result['end']
        result_list[original_index]['alignment_score'] = float(result.get('score', 0.0))
        result_list[original_index]['alignment_start'] = float(result.get('original_start', 0.0))
        result_list[original_index]['alignment_end'] = float(result.get('original_end', 0.0))

    canonical_lines = []
    token_offset = 0
    source_timeline = timeline if args.timeline_json else []
    for line_index, line_tokens in enumerate(alignment_token_lines):
        token_records = []
        for token_index, _ in enumerate(line_tokens):
            alignment_index = token_offset + token_index
            original_item = result_list[token_to_index_map[alignment_index]]
            token_records.append({
                'source_index': token_index,
                'text': str(original_item.get('orig', '')),
                'acoustic_token': str(original_item.get('pron', '')),
                'start_ms': round(float(original_item['alignment_start']) * 1000),
                'end_ms': round(float(original_item['alignment_end']) * 1000),
                'ctc_score': float(original_item['alignment_score']),
            })
        token_offset += len(line_tokens)
        source = source_timeline[line_index] if line_index < len(source_timeline) else {}
        canonical_lines.append({
            'source_index': line_index,
            'text': str(source.get('text', '')),
            'source_start_ms': source.get('start_ms'),
            'start_ms': token_records[0]['start_ms'] if token_records else None,
            'end_ms': token_records[-1]['end_ms'] if token_records else None,
            'tokens': token_records,
        })
    finite_scores = [token['ctc_score'] for line in canonical_lines for token in line['tokens']]
    source_diagnostics = alignment_results[0].get('source_diagnostics', {}) if alignment_results else {}
    alignment_document = {
        'schema_version': 1,
        'alignment': {'mode': 'global_ctc_calibrated_source_prior', 'lines': canonical_lines},
        'diagnostics': {
            'inference_passes': max((int(result.get('inference_passes', 1)) for result in alignment_results), default=0),
            'line_count': len(canonical_lines),
            'token_count': len(finite_scores),
            'mean_ctc_score': sum(finite_scores) / len(finite_scores) if finite_scores else 0.0,
            'minimum_ctc_score': min(finite_scores) if finite_scores else 0.0,
            'interpolated_source_lines': [
                index for index, line in enumerate(source_timeline) if line.get('interpolated')
            ],
            **source_diagnostics,
        },
    }
    with open(os.path.join(real_io_path, 'o.alignment.json'), 'w', encoding='utf-8') as f:
        json.dump(alignment_document, f, ensure_ascii=False, separators=(',', ':'))

    result_list = non_silent_head_adjust(result_list, non_silent_ranges)
    
    if tail_correct == 3:
        result_list = func_tail_correct_v250615(result_list, audio_file, sr, tail_thres_pct, tail_thres_ratio)
    
    if output_characters_per_line > 0:
        split_long_segments(result_list, max_length=output_characters_per_line)

    main_output = process_main(result_list, ruby_tag_offset, bpm, beats_per_bar)
    ruby_output = process_ruby_V2(result_list)
    content = f"{main_output}\n{ruby_output}"
    with open(os.path.join(real_io_path, 'o_ruby.lrc'), 'w', encoding='utf-8') as f:
        f.write(content)
    rlf_output = process_rlf(result_list)
    with open(os.path.join(real_io_path, 'o_rlf.lrc'), 'w', encoding='utf-8') as f:
        f.write(rlf_output)
    ass_output = norm2ass.process_norm2assV2(result_list)
    ass_head = '''[Script Info]
ScriptType: v4.00+
YCbCr Matrix: TV.601
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Source Han Serif,71,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1.99999,1.99999,2,11,11,101,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    with open(os.path.join(real_io_path, 'o.ass'), 'w', encoding='utf-8') as f:
        f.write(ass_head+ass_output)
    # hrhlrc_output = ''
    # for i in ass_output.splitlines():
    #     hrhlrc_output += ass2lrc.ass2lrc(i, 0)+'\n'
    # with open(os.path.join(real_io_path, 'o_hrh.lrc'), 'w', encoding='utf-8') as f:
    #     f.write(hrhlrc_output)
    print('Success!')

if __name__=='__main__':
    main()