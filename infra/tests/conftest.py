import functools
import tempfile
from pathlib import Path

import config
from tests.test_config import VALID, write

# Fixed here so a filled-in project.toml cannot break the suite.
TEMPLATE = (
    VALID.replace('model_id = "model-a"', 'model_id = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"')
    .replace('model_ids = ["model-a", "model-b"]', 'model_ids = ["us.anthropic.claude-sonnet-4-5-20250929-v1:0"]')
    + "nat_gateways = 1\n\n[environments.prod]\ndesired_count = 2\ncpu = 512\nmemory = 1024\nnat_gateways = 2\n"
)


@functools.cache
def fixed_config() -> config.Config:
    with tempfile.TemporaryDirectory() as d:
        return config.load(write(Path(d), TEMPLATE))
