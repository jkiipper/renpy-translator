# Renpy Translator

Translate your Renpy game with LLM.

## Usage

Install dependencies:

```bash
uv sync
```

Create a `.env` file based on `.env.example` and fill the info as needed:

```dotenv
LLM_BASE_URL=your-openai-base-url
LLM_API_KEY=your-openai-api-key
LLM_MODEL=your-model-name
DEBUG=FALSE
```

The API needs to be compatible with OpenAI API.

Show help message:

```bash
uv run main.py -h
```

### Arguments

*   **`input_folder`**: Path to the input file or base translation directory containing script nodes.
*   **`output_folder`**: Destination directory where generated translated files will be organized.
*   **`--src-lang`**: Source language identifier signature (Default: English).
*   **`--dst-lang`**: Explicit destination language name (e.g., 'Traditional Chinese'). If using `--batch-mode`, this argument is ignored.
*   **`--overwrite`**: Force overwrite files if they already exist in the output path directory.
*   **`--chunk-size`**: Number of translatable text strings bundled into each individual LLM payload chunk (Default: 50).
*   **`--batch-mode`**: Scans input directory subfolders matching known names inside `LANGUAGE_MAP` and translates all of them automatically.

### Examples

**1. Translate a single `.rpy` file:**

```bash
uv run main.py ./test_data/script.rpy ./test_out/ --dst-lang "Simplified Chinese"
```

**2. Translate an entire directory (standard mode):**

This will recursively translate all `.rpy` files in `input_folder` to the specified destination language.

```bash
uv run main.py ./test_data/ ./test_out/ --dst-lang "Japanese"
```

**3. Translate an entire directory (standard mode) and overwrite existing files:**

```bash
uv run main.py ./test_data/ ./test_out/ --dst-lang "Japanese" --overwrite
```

**4. Translate an entire directory using batch mode:**

In batch mode, the tool scans subfolders within `input_folder` that match keys in the `LANGUAGE_MAP` (defined in `main.py`). For each matching subfolder, it translates its contents to the corresponding language.

Example `LANGUAGE_MAP` entry: `'schinese': 'Simplified Chinese'`

If `input_folder` contains a subfolder named `schinese`, it will be translated to Simplified Chinese.

```bash
uv run main.py ./game/tl/ ./game/tl/ --batch-mode
```

The translator will recursively translate all the `.rpy` files in the source folder and write to the target folder,
preserving folder structures.
To skip the translated `.rpy` files (files that do not need to translate), create a `.rpyignore` file in the `.rpy`
source folder:

```gitignore
file1.rpy
file2.rpy
folder1/file1.rpy
# file3.rpy
```

## Step-by-step Guide for Translating Renpy Games

Enable language selection in the `Preferences` tab.

`game/screens.rpy`:

```renpy
# ...
screen preferences():

    tag menu

    use game_menu(_("Preferences"), scroll="viewport"):

        vbox:

            hbox:
                # ...

                ## Additional vboxes of type "radio_pref" or "check_pref" can be
                ## added here, to add additional creator-defined preferences.

                vbox:
                    style_prefix "radio"
                    label _("Language")
                    textbutton "English" action Language(None)
                    textbutton "简体中文" text_font "SourceHanSansLite.ttf" action Language("zh_cn")

            null height (4 * gui.pref_spacing)

            hbox:
                # ...
# ...
```

Generate translation with Renpy SDK (GUI), e.g., `zh_cn`.

Run translation:

```bash
uv run main.py /path/to/game/tl/zh_cn/ /path/to/game/tl/zh_cn/ --dst-lang "Simplified Chinese"
```

This will translate and replace the `.rpy` files in the `game/tl/zh_cn` folder.

Check the translated files to make sure the translation is correct.

> Hint: init a git repo, e.g., for `game/tl`, to track translation changes.

Launch game and enjoy!

> Some languages, e.g., Chinese, may need special fonts to work well.
> In that case, modify `game/tl/zh_cn/options.rpy` to use that font.

Put the font file in the `game` folder and modify `game/tl/zh_cn/options.rpy` like the following:

```renpy
translate zh_cn python:
    gui.system_font = gui.main_font = gui.text_font = gui.name_text_font = gui.interface_text_font = gui.button_text_font = gui.choice_button_text_font = "SourceHanSansLite.ttf"

translate zh_cn strings:

    # game/options.rpy:15
    old "Renpy Example"
    new "Renpy 示例"
```

Alternatively, create a `game/tl/zh_cn/style.rpy` file:

```renpy
translate zh_cn python:
    gui.system_font = gui.main_font = gui.text_font = gui.name_text_font = gui.interface_text_font = gui.button_text_font = gui.choice_button_text_font = "SourceHanSansLite.ttf"
```