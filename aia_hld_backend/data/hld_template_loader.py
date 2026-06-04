import json
from collections import OrderedDict
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "hld_template_json_onprem.json"


def load_hld_template_config() -> OrderedDict:
    """
    Loads section order directly from the canonical HLD v7.2 template.
    """
    with open(TEMPLATE_PATH, "r") as f:
        template = json.load(f, object_pairs_hook=OrderedDict)

    # Preserve top-level key order
    return OrderedDict(
        (key, key.replace("_", " ").title())
        for key in template.keys()
    )