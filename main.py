import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ========================
# Configuration
# ========================
LLM_BASE_URL = os.environ['LLM_BASE_URL']
LLM_API_KEY = os.environ['LLM_API_KEY']
LLM_MODEL = os.environ['LLM_MODEL']
MAX_RETRIES = 3
TIMEOUT = 300  # seconds

# LLM client
client = OpenAI(
    api_key=LLM_API_KEY, base_url=LLM_BASE_URL, max_retries=MAX_RETRIES, timeout=TIMEOUT
)


# ========================
# Core Functions
# ========================
def extract_translatable_blocks(content):
    """
    Splits .rpy content into translatable blocks (dialogue + metadata).
    Returns list of dicts with keys: 'text', 'line_number', 'tags'.
    """
    blocks = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        # Match dialogue with an explicit display name (e.g., `"Eileen" "Hello" nointeract`)
        explicit_name_match = re.match(
            r'^\s*"((?:\\.|[^"\\])*)"\s+"((?:\\.|[^"\\])*)"\s*(.*)$', line
        )
        if explicit_name_match:
            speaker = f'"{explicit_name_match.group(1)}"'
            text = explicit_name_match.group(2)
            trailing_args = explicit_name_match.group(3).strip()
            tags = re.findall(r'\{.*?\}|\[.*?\]', text)
            stmt_args = [trailing_args] if trailing_args else []

            blocks.append(
                {
                    'original': line,
                    'speaker': speaker,
                    'text': text,
                    'tags': tags,
                    'stmt_args': stmt_args,
                    'line_number': i + 1,
                }
            )
            continue

        # Match dialogue lines (e.g., `e "Hello{w=0.5}, world!"`)
        match = re.match(r'^(\s*[a-zA-Z0-9_]*\s*)"(.*)"\s*', line)
        if not match:
            continue

        speaker = match.group(1).strip()
        # do not translate what 'old' says, it is a keyword
        if speaker == 'old':
            continue
        text = match.group(2)
        tags = re.findall(r'\{.*?\}|\[.*?\]', text)
        # s "What is a visual novel?" nointeract
        stmt_args = re.findall(
            r'^\s*[a-zA-Z0-9_]*\s*"(?:\\.|[^"\\])*"\s*(\S+(?:\s+\S+)*)', line
        )

        blocks.append(
            {
                'original': line,
                'speaker': speaker,
                'text': text,
                'tags': tags,
                'stmt_args': stmt_args,
                'line_number': i + 1,
            }
        )

    return blocks


def generate_llm_prompt(blocks, target_lang):
    """
    Formats blocks into an LLM prompt with strict instructions.
    """
    examples = """
Example Input:

<1> e "Hello{w=0.5}, world!{fast}"
<3> s "What is a visual novel?"
<15> ai "Let's make a game, {w} a very good one, with [c]!"
<99> f "{i}{alpha=.6}\"What's going on...?{w} Why is she crying now...?!\"{/alpha}{i}"
<112> "Score: %s points"
<156> "I am the narrator, and I will guide you through this game."
<177> g "My first name is [player.names[0]]."
<203> g "You achieved [100.0 * points / max_points:.2] scores!"
<205> so "Hello, Natsuki! My name is Sora."
<208> n "You are very happy to see Sora, as you have been waiting for her for a long time."

Example Output:

<1> e "你好{w=0.5}, 世界!{fast}"
<3> s "什么是视觉小说？"
<15> ai "让我们制作一个游戏，{w} 一个非常好的游戏，和[c]一起！"
<99> f "{i}{alpha=.6}\"发生了什么事...?{w} 她为什么现在在哭...？！\"{/alpha}{i}"
<112> "得分: %s 分"
<156> "我是旁白，我将引导你完成这个游戏。"
<177> g "我的名字是 [player.names[0]]。"
<203> g "你获得了 [100.0 * points / max_points:.2] 分！"
<205> so "你好，Natsuki！我叫Sora。"
<208> n "你非常高兴见到Sora，因为你已经等她很久了。"
    """.strip()

    instructions = f"""
Translate these Ren'Py game dialogues to {target_lang}. Follow these rules:
1. Preserve ALL tags ({{...}}, [...], etc.), speaker labels, and formatting EXACTLY.
2. Preserve ALL line numbers at the beginning EXACTLY, and translate line by line.
3. Preserve ALL character names in the ORIGINAL language.
4. Keep placeholders like %s unchanged.
5. Never add/remove quotes or line breaks.

{examples}

Now translate these:
    """.strip()

    text_to_translate = '\n'.join(
        f'<{block["line_number"]}> {block["speaker"]} "{block["text"]}"'
        for block in blocks
    )

    return f'{instructions}\n{text_to_translate}'


def call_llm_api(prompt):
    """
    Calls the LLM API with the constructed prompt.
    Adjust according to your API's requirements.
    """
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    'role': 'system',
                    'content': 'You are a professional game translator.',
                },
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.3,
            # max_tokens=4000,
            stream=False,
        )

        return response.choices[0].message.content
    except Exception as e:
        print(f'Retrying... Error: {e}')

    raise Exception('LLM API failed after retries')


def validate_translation(original_block, translated_line):
    """
    Checks if tags, speakers, etc. are preserved.
    """
    # Check line number
    orig_ln = original_block['line_number']
    try:
        trans_ln = int(re.findall(r'^<(\d+)>', translated_line)[0])
    except IndexError:
        print(f'Line number not found in translated line: {translated_line}')
        return False

    if orig_ln != trans_ln:
        print(f'Line number mismatch: Original {orig_ln} vs Translated {trans_ln}')
        return False

    # Check speaker
    orig_speaker = original_block['speaker']
    speaker_match = re.match(
        r'^<\d+>\s*("((?:\\.|[^"\\])*)"|[a-zA-Z0-9_]*)\s*"', translated_line
    )
    if not speaker_match:
        print(f'Speaker not found in translated line: {translated_line}')
        return False
    trans_speaker = speaker_match.group(1).strip()
    if orig_speaker != trans_speaker:
        print(
            f'Speaker mismatch: Original {orig_speaker} vs Translated {trans_speaker}'
        )
        return False

    # Check tags
    orig_tags = original_block['tags']
    trans_tags = re.findall(r'\{.*?\}|\[.*?\]', translated_line)
    if set(orig_tags) != set(trans_tags):
        print(f'Tag mismatch:\nOriginal: {orig_tags}\nTranslated: {trans_tags}')
        return False

    return True


def process_rpy_file(in_path, out_path, target_lang):
    """
    Main pipeline: Read -> Extract -> Translate -> Validate -> Write.
    """
    print(f'Processing {in_path} -> {out_path} ({target_lang})')

    # Read input file
    with open(in_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract translatable blocks
    blocks = extract_translatable_blocks(content)
    if not blocks:
        print('No translatable dialogue found.')
        return

    # Generate LLM prompt and call API
    prompt = generate_llm_prompt(blocks, target_lang)
    translated_response = call_llm_api(prompt)

    # Parse LLM response
    translated_lines = [
        line.strip()
        for line in translated_response.split('\n')
        if line.strip() and '"' in line
    ]

    # check if all blocks are translated
    if len(blocks) != len(translated_lines):
        print(
            f'Warning: {len(translated_lines)} lines translated, but there are {len(blocks)} translate blocks.'
        )

    # Reintegrate translations
    output_lines = content.split('\n')
    err_cnt = 0
    for block, translated_line in zip(blocks, translated_lines):
        if not validate_translation(block, translated_line):
            err_cnt += 1
            print(
                f'Validation failed for block: {block}\nTranslated line: {translated_line}'
            )
        # remove line number from translted line
        translated_line = re.sub(r'^<\d+>\s*', '', translated_line)
        output_lines[block['line_number'] - 1] = '    ' + ' '.join(
            [translated_line, *block['stmt_args']]
        )
    if err_cnt:
        print(f'{err_cnt} errors encountered.')

    # Write output
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))

    print(f'Successfully translated {len(blocks)} lines.')


# ========================
# CLI Interface
# ========================
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Automatically translate Ren'Py (.rpy) scripts using an LLM API."
    )
    parser.add_argument(
        'input_folder',
        help='Path to the input folder that contains the .rpy files to be translated.',
    )
    parser.add_argument(
        'output_folder', help='Path to the output folder for the translated .rpy files.'
    )
    parser.add_argument(
        '--lang', required=True, help='Target language (e.g., "chinese")'
    )
    args = parser.parse_args()

    # Verify paths
    input_path = Path(args.input_folder)
    if not input_path.exists():
        raise FileNotFoundError(f'Input folder not found: {input_path}')

    output_path = Path(args.output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    # read .rpyignore
    ignore_set = set()
    ignore_file = input_path.joinpath('.rpyignore')
    if ignore_file.exists():
        try:
            with open(ignore_file, 'r', encoding='utf-8') as f:
                ignore_set = set(
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith('#')
                )
        except UnicodeDecodeError:
            print(
                f'Warning: ignore file {ignore_file} is not a Unicode file, skipping.'
            )

    for in_file_path in input_path.glob('**/*.rpy'):
        # get relative path
        rel_path = in_file_path.relative_to(input_path)

        if str(rel_path) in ignore_set:
            continue

        out_file_path = output_path / rel_path
        out_file_path.parent.mkdir(parents=True, exist_ok=True)

        # run translation
        process_rpy_file(in_file_path, out_file_path, args.lang)

        ignore_set.add(str(rel_path))

        # update .rpyignore
        with open(ignore_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sorted(ignore_set)))
