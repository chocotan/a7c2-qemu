"""Opt-in policy for original-byte checks; synthetic tests do not use this gate."""
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ORIGINAL_ASSET_OPT_IN = 'A7C2_RUN_ORIGINAL_ASSET_TESTS'


def requires_original_assets(*paths):
    """Keep the original-byte assertions intact when locally supplied assets exist."""
    assert paths and all(not Path(path).is_absolute() and '..' not in Path(path).parts
                         for path in paths)
    missing = [path for path in paths if not (HERE/'menu-root'/path).is_file()]
    reason = ('original firmware byte identity check; set ' + ORIGINAL_ASSET_OPT_IN +
              '=1 and prepare the matching official assets separately')
    if missing:
        reason += '; missing: ' + ', '.join(missing)
    return pytest.mark.skipif(os.environ.get(ORIGINAL_ASSET_OPT_IN) != '1' or bool(missing),
                              reason=reason)
