#!/usr/bin/env python3
"""Entry point. The tool now lives in mtg_utils/; this file stays so that every
command already in use keeps working unchanged:

    python3 mana_model.py audit deck.txt --cache scry.json

`python -m mtg_utils` does the same thing. `import mana_model` also still works
as a library import -- mtg_utils re-exports everything the single file exposed,
so a script that called mana_model.castable() does not care that the file was
split up.

The banner `--help` prints is mtg_utils.__doc__, not this docstring.
"""
from mtg_utils import *          # noqa: F401,F403  -- library compatibility
from mtg_utils.cli import main   # noqa: F401

if __name__ == "__main__":
    main()
