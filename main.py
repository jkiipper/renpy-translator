import argparse
import json
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
DEBUG = os.environ['DEBUG']
MAX_RETRIES = 3
TIMEOUT = 300  # seconds

# ANSI codes for colored terminal output
CYAN = '\033[36m'
GREEN = '\033[32m'
RESET = '\033[0m'

# Mapping dictionary for Batch mode (Folder -> Language Name)
# You can expand or modify this map according to your needs.
LANGUAGE_MAP = {
    'brazilian': 'Brazilian Portuguese',
    'german': 'German',
    'latam': 'Spanish (Latin America)',
    'russian': 'Russian',
    'schinese': 'Simplified Chinese',
    'spanish': 'Spanish',
    'tchinese': 'Traditional Chinese',
}

# LLM Client
client = OpenAI(
    api_key=LLM_API_KEY, base_url=LLM_BASE_URL, max_retries=MAX_RETRIES, timeout=TIMEOUT
)

if DEBUG == 'True':
    print(f'Debug Enabled')


# ========================
# Core Functions
# ========================
def extract_translatable_blocks(content):
    """
    Splits .rpy content into translatable blocks (dialogue + metadata).
    Returns a list of dicts with keys: 'id', 'text', 'line_number', 'raw_line'.
    """
    blocks = []
    lines = content.split('\n')

    # Simple regex to catch `new "text"` blocks inside translate blocks or string translations
    # Matches `new "Anything inside quotes"`
    pattern = re.compile(r'^\s*new\s+"((?:\\.|[^"\\])*)"')

    for i, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            extracted_text = match.group(1)
            # Use 1-based index for line numbers to make debugging easier
            blocks.append({
                'id': len(blocks) + 1,
                'text': extracted_text,
                'line_number': i + 1,
                'raw_line': line
            })

    return blocks


def translate_batch_with_llm(blocks, src_lang, dst_lang):
    """
    Sends a batch of blocks to the LLM and asks for a JSON array response.
    """
    # Create an array containing only id and text to optimize context/tokens
    payload = [{'id': b['id'], 'text': b['text']} for b in blocks]

    prompt = (
        f"You are an automated game localization engine. Translate the text fields in the provided JSON array from {src_lang} into {dst_lang}.\n\n"
        f"Task Instructions:\n"
        f"- Translate only the \"text\" values into natural, flowing {dst_lang}.\n"
        f"- CRITICAL: Keep all internal curly-brace tags completely unchanged, such as {{#weekday_short}} or {{#month}}. Do NOT translate or alter text inside `{{#...}}`.\n"
        f"- CRITICAL: Keep all variable brackets completely unchanged, such as [text], [identifier], or [renpy.display.tts.last]. Do NOT translate text inside square brackets `[...]`.\n"
        f"- Keep all Ren'Py tags (e.g., {{w}}, {{fast}}, %s) exactly as they are.\n"
        f"- Retain formatting characters like '\\n' or '\\t' if they are present in the source strings.\n"
        f"- Do NOT change the \"id\" values.\n"
        f"- Respond strictly with a valid JSON array matching the exact structure received. Do not wrap the JSON output in markdown blocks (like ```json ... ```) or append explanation prose.\n\n"
        """Example:
        Input JSON:
        [
        {{"id": 1, "text": "Hello{{w=0.5}}, world!{{fast}}"}},
        {{"id": 2, "text": "{{#weekday_short}}Sun"}},
        {{"id": 3, "text": "skip unseen [text]"}}
        ]
        Output JSON:
        [
        {{"id": 1, "text": "Olá{{w=0.5}}, mundo!{{fast}}"}},
        {{"id": 2, "text": "{{#weekday_short}}Dom"}},
        {{"id": 3, "text": "pular não visto [text]"}}
        ]

        Translate this JSON array from {src_lang} into {dst_lang}:"""
        f"Input Data:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=4)}"
    )

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a professional localizer specializing in video games and interactive novels."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )

        response_text = response.choices[0].message.content.strip()

        if DEBUG == 'True':
            print(f"\n--- [DEBUG LLM RESPONSE] ---")
            print(response_text)
            print(f"-----------------------------\n")

        return response_text

    except Exception as e:
        print(f"API Error during translation: {e}")
        return None


def chunk_list(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def process_rpy_file(in_file_path, out_file_path, src_lang, dst_lang, overwrite=False, chunk_size=50):
    """
    Parses an .rpy file, extracts target texts, translates them in batches via the LLM,
    and reconstructs the updated file structure in the output destination.
    """
    if out_file_path.exists() and not overwrite:
        print(f"Skipping file: '{out_file_path.name}' (Already exists in output path. Use --overwrite to force refresh).")
        return

    with open(in_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = extract_translatable_blocks(content)

    if not blocks:
        print(f"No strings found to translate in '{in_file_path.name}'. Copying file directly.")
        out_file_path.write_text(content, encoding='utf-8')
        return

    print(f"Processing '{in_file_path.name}': Found {len(blocks)} strings to translate.")

    lines = content.split('\n')
    chunks = list(chunk_list(blocks, chunk_size))
    total_chunks = len(chunks)

    for idx, chunk in enumerate(chunks, 1):
        print(f"Translating batch {idx}/{total_chunks}...")

        llm_response = translate_batch_with_llm(chunk, src_lang, dst_lang)
        if not llm_response:
            print(f"Error: Unable to get translation for batch {idx}. Aborting file to prevent script corruption.")
            return

        try:
            # strict=False handles literal unescaped control characters (like tabs/newlines) inside LLM-returned text strings
            translated_data = json.loads(llm_response, strict=False)
        except json.JSONDecodeError as je:
            print(f"CRITICAL ERROR: Failed to decode JSON response from batch {idx}: {je}")
            print("Aborting file write operations to avoid breaking the script structure.")
            return

        # Build an easy-lookup dictionary from the translated data
        translation_map = {}
        for item in translated_data:
            if isinstance(item, dict) and 'id' in item and 'text' in item:
                translation_map[item['id']] = item['text']

        # Replace the original strings inside the line buffer
        for block in chunk:
            block_id = block['id']
            if block_id in translation_map:
                translated_text = translation_map[block_id]

                # Reconstruct the line preserving the indentation layout
                raw_line = block['raw_line']
                indentation = raw_line[:len(raw_line) - len(raw_line.lstrip())]

                # Format the newly updated translation line
                new_line = f'{indentation}new "{translated_text}"'

                # Match line index conversion (1-based to 0-based index adjustments)
                line_idx = block['line_number'] - 1
                lines[line_idx] = new_line
            else:
                print(f"Warning: Id {block_id} was missing from the returned translation payload. Keeping original text.")

    # Reassemble and save the finalized script file
    finalized_content = '\n'.join(lines)
    out_file_path.write_text(finalized_content, encoding='utf-8')
    print(f"Successfully saved translated script to: '{out_file_path}'")


def process_directory_recursive(input_dir, output_dir, src_lang, dst_lang, overwrite, chunk_size):
    """
    Recursively scans and processes all .rpy files found inside a specific directory.
    """
    for item in input_dir.rglob('*.rpy'):
        # Get matching relative structural paths to mirror output layouts
        rel_path = item.relative_to(input_dir)
        target_out_path = output_dir / rel_path

        # Build missing parent directory branches dynamically
        target_out_path.parent.mkdir(parents=True, exist_ok=True)

        process_rpy_file(item, target_out_path, src_lang, dst_lang, overwrite, chunk_size)


# ========================
# Main Execution Pipeline
# ========================
def main():
    parser = argparse.ArgumentParser(
        description="Automated Ren'Py Visual Novel Script Translator Engine leveraging LLM Capabilities."
    )
    parser.add_argument('input_folder', type=str, help="Path to the input file or base translation directory containing script nodes.")
    parser.add_argument('output_folder', type=str, help="Destination directory where generated translated files will be organized.")
    parser.add_argument('--src-lang', type=str, default='English', help="Source language identifier signature (Default: English).")
    parser.add_argument('--dst-lang', type=str, default=None, help="Explicit destination language name (e.g., 'Traditional Chinese'). If using --batch-mode, this argument is ignored.")
    parser.add_argument('--overwrite', action='store_true', help="Force overwrite files if they already exist in the output path directory.")
    parser.add_argument('--chunk-size', type=int, default=50, help="Number of translatable text strings bundled into each individual LLM payload chunk (Default: 50).")
    parser.add_argument('--batch-mode', action='store_true', help="Scans input directory subfolders matching known names inside LANGUAGE_MAP and translates all of them automatically.")

    args = parser.parse_args()

    input_base = Path(args.input_folder)
    output_dir = Path(args.output_folder)

    if not input_base.exists():
        raise FileNotFoundError(f"Input path structural location error: Targeted reference does not exist: {input_base}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # MODE 1: Batch Directory Automation Mode
    if args.batch_mode:
        if not input_base.is_dir():
            raise ValueError("Error: Input target must be a valid root directory folder when enabling --batch-mode processing options.")

        # Gather immediate subdirectories representing separate language folders
        subfolders = [f for f in input_base.iterdir() if f.is_dir()]
        print(f"\n[BATCH] Batch mode active. Detected {len(subfolders)} subdirectories inside {input_base}.\n")

        for folder in subfolders:
            folder_name = folder.name

            # Check if the folder name matches a configuration inside LANGUAGE_MAP
            if folder_name in LANGUAGE_MAP:
                detected_dst_lang = LANGUAGE_MAP[folder_name]
                print(f"\n[BATCH] Starting processing for folder '{folder_name}' -> Target Language: {detected_dst_lang}")

                # Mirror the language folder name layout inside the primary output directory path
                target_output_dir = output_dir / folder_name
                process_directory_recursive(folder, target_output_dir, args.src_lang, detected_dst_lang, args.overwrite, args.chunk_size)
            else:
                print(f"\n[BATCH] Notice: Folder '{folder_name}' skipped. No matching translation mapping found in LANGUAGE_MAP.")

        print("\n[BATCH] All mapped language batch translation pipelines completed successfully!")

    # MODE 2: Standard Individual File / Target Directory Mode
    else:
        if input_base.is_file():
            if input_base.suffix != '.rpy':
                raise ValueError(f"Target script file format mismatch exception. Expected an '.rpy' extension. Received: {input_base.name}")

            out_file_path = output_dir / input_base.name
            process_rpy_file(input_base, out_file_path, args.src_lang, args.dst_lang, args.overwrite, args.chunk_size)

        elif input_base.is_dir():
            if not args.dst_lang:
                raise ValueError("Missing parameter: An explicit target translation language must be defined via `--dst-lang` when processing standard directories.")

            print(f"\nScanning workspace directory target structure: '{input_base}' -> Export Target: '{args.dst_lang}'\n")
            process_directory_recursive(input_base, output_dir, args.src_lang, args.dst_lang, args.overwrite, args.chunk_size)


if __name__ == '__main__':
    main()