import argparse
import sys

from aw_core.config import load_config_toml

default_config = """
[aw-watcher-afk]
timeout = 180
poll_time = 5
username_override = ""
hostname_override = ""

[aw-watcher-afk-testing]
timeout = 20
poll_time = 1
""".strip()


def load_config(testing: bool):
    section = "aw-watcher-afk" + ("-testing" if testing else "")
    return load_config_toml("aw-watcher-afk", default_config)[section]


def parse_args():
    # get testing in a dirty way, because we need it for the config lookup
    testing = "--testing" in sys.argv
    config = load_config(testing)
    default_username_override = config.get("username_override", "")
    default_hostname_override = config.get("hostname_override", "")

    default_poll_time = config["poll_time"]
    default_timeout = config["timeout"]

    parser = argparse.ArgumentParser(
        description="A watcher for keyboard and mouse input to detect AFK state."
    )
    parser.add_argument("--host", dest="host")
    parser.add_argument("--port", dest="port")
    parser.add_argument(
        "--testing", dest="testing", action="store_true", help="run in testing mode"
    )
    parser.add_argument(
        "--verbose",
        dest="verbose",
        action="store_true",
        help="run with verbose logging",
    )
    parser.add_argument(
        "--timeout", dest="timeout", type=float, default=default_timeout
    )
    parser.add_argument(
        "--poll-time", dest="poll_time", type=float, default=default_poll_time
    )
    parser.add_argument(
        "--username-override",
        dest="username_override",
        default=default_username_override,
        help="Override username used in bucket IDs (takes precedence over config if provided).",
    )
    parser.add_argument(
        "--hostname-override",
        dest="hostname_override",
        default=default_hostname_override,
        help="Override hostname used in bucket IDs (takes precedence over config if provided).",
    )
    parsed_args = parser.parse_args()
    return parsed_args
