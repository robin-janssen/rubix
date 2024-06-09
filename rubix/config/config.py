from rubix.utils import read_yaml
import os
import json
from functools import reduce

PARENT_DIR = os.path.dirname(os.path.abspath(__file__))
RUBIX_CONFIG_PATH = os.path.join(PARENT_DIR, "rubix_config.yml")
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "rubix_config.yml"
)

PIPELINE_CONFIG_PATH = os.path.join(PARENT_DIR, "pipeline_config.yml")


class Config:

    @staticmethod
    def load() -> dict:
        rubix_config = read_yaml(RUBIX_CONFIG_PATH)
        pipeline_config = read_yaml(PIPELINE_CONFIG_PATH)
        config = {**rubix_config, "pipelines": pipeline_config}
        return config


class UserConfig:
    def __init__(self, config: dict):
        self.config = config

    # def __getitem__(self, key):
    #     keys = key.split("/")
    #
    #     value = self.config
    #     for k in keys:
    #         # Check if it exists, otherwise raise error
    #         if k not in value:
    #             raise KeyError(f"Key {k} not found in config located at {key}: {value}")
    #         value = value[k]
    #     return value
    def __getitem__(self, key):
        # key can have / to access nested keys
        # e.g. key = "data/args"
        # returns self.config["data"]["args"]
        # or key = "data/args/arg1"
        # returns self.config["data"]["args"]["arg1"]
        keys = key.split("/")
        try:
            return reduce(lambda d, k: d[k], keys, self.config)
        except KeyError:
            raise KeyError(f"Key {key} not found in config")

    def __str__(self):
        return json.dumps(self.config, indent=4)

    def __repr__(self):
        return f"UserConfig({json.dumps(self.config, indent=4)})"
