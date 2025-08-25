import logging
import os
import platform
import subprocess
import getpass

from datetime import datetime, timedelta, timezone
from time import sleep

from aw_client import ActivityWatchClient
from aw_core.models import Event

from .config import load_config

system = platform.system()

if system == "Windows":
    # noreorder
    from .windows import seconds_since_last_input  # fmt: skip
elif system == "Darwin":
    # noreorder
    from .macos import seconds_since_last_input  # fmt: skip
elif system == "Linux":
    # noreorder
    from .unix import seconds_since_last_input  # fmt: skip
else:
    raise Exception(f"Unsupported platform: {system}")


logger = logging.getLogger(__name__)
td1ms = timedelta(milliseconds=1)

def get_logged_in_user():
    """Возвращает *локального* пользователя, сидящего за физическим рабочим столом (seat0).
    SSH/PTS‑сессии игнорируются"""

    # 1) Пытаемся через systemd‑logind (самый надёжный способ)
    try:
        seat0 = subprocess.check_output(
            "loginctl list-sessions --no-legend | awk '$3==\"seat0\" {print $1; exit}'",
            shell=True,
        ).decode().strip()
        if seat0:
            user = subprocess.check_output(
                f"loginctl show-session {seat0} -p Name --value",
                shell=True,
            ).decode().strip()
            if user:
                return user
    except Exception:
        pass  # fallback ниже

    # 2) Первая строка `who`, где tty НЕ начинается с pts/ (т.е. не SSH)
    try:
        for line in subprocess.check_output("who", shell=True).decode().splitlines():
            cols = line.split()
            if len(cols) >= 2 and not cols[1].startswith("pts/"):
                return cols[0]
    except Exception:
        pass

    # 3) Запасной вариант — пользователь, под которым запущен процесс
    try:
        return getpass.getuser()
    except Exception as e:
        logger.error(f"Failed to get logged in user: {e}")
        return "unknown"


def running_over_ssh() -> bool:
    """True, если скрипт запущен из SSH‑сессии (SSH_CLIENT/SSH_TTY)."""
    return bool(os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY"))


class Settings:
    def __init__(self, config_section, timeout=None, poll_time=None):
        # Time without input before we're considering the user as AFK
        self.timeout = timeout or config_section["timeout"]
        # How often we should poll for input activity
        self.poll_time = poll_time or config_section["poll_time"]

        assert self.timeout >= self.poll_time


class AFKWatcher:
    def __init__(self, args, testing=False):
        # Read settings from config
        self.settings = Settings(
            load_config(testing), timeout=args.timeout, poll_time=args.poll_time
        )
        username = get_logged_in_user()
        self.client = ActivityWatchClient(
            "aw-watcher-afk", host=args.host, port=args.port, testing=testing
        )
        self.bucketname = "{}-afk_{}".format(
            username, self.client.client_hostname
        )

    def ping(self, afk: bool, timestamp: datetime, duration: float = 0):
        data = {"status": "afk" if afk else "not-afk"}
        e = Event(timestamp=timestamp, duration=duration, data=data)
        pulsetime = self.settings.timeout + self.settings.poll_time
        self.client.heartbeat(self.bucketname, e, pulsetime=pulsetime, queued=True)

    def run(self):
        logger.info("aw-watcher-afk started")

        # Initialization
        self.client.wait_for_start()

        eventtype = "afkstatus"
        self.client.create_bucket(self.bucketname, eventtype, queued=True)

        # Start afk checking loop
        with self.client:
            self.heartbeat_loop()

    def heartbeat_loop(self):
        afk = False
        while True:
            try:
                if system in ["Darwin", "Linux"] and os.getppid() == 1:
                    # TODO: This won't work with PyInstaller which starts a bootloader process which will become the parent.
                    #       There is a solution however.
                    #       See: https://github.com/ActivityWatch/aw-qt/issues/19#issuecomment-316741125
                    logger.info("afkwatcher stopped because parent process died")
                    break

                now = datetime.now(timezone.utc)
                seconds_since_input = seconds_since_last_input()
                last_input = now - timedelta(seconds=seconds_since_input)
                logger.debug(f"Seconds since last input: {seconds_since_input}")

                # If no longer AFK
                if afk and seconds_since_input < self.settings.timeout:
                    logger.info("No longer AFK")
                    self.ping(afk, timestamp=last_input)
                    afk = False
                    # ping with timestamp+1ms with the next event (to ensure the latest event gets retrieved by get_event)
                    self.ping(afk, timestamp=last_input + td1ms)
                # If becomes AFK
                elif not afk and seconds_since_input >= self.settings.timeout:
                    logger.info("Became AFK")
                    self.ping(afk, timestamp=last_input)
                    afk = True
                    # ping with timestamp+1ms with the next event (to ensure the latest event gets retrieved by get_event)
                    self.ping(
                        afk, timestamp=last_input + td1ms, duration=seconds_since_input
                    )
                # Send a heartbeat if no state change was made
                else:
                    if afk:
                        # we need the +1ms here too, to make sure we don't "miss" the last heartbeat
                        # (if last_input hasn't changed)
                        self.ping(
                            afk,
                            timestamp=last_input + td1ms,
                            duration=seconds_since_input,
                        )
                    else:
                        self.ping(afk, timestamp=last_input)

                sleep(self.settings.poll_time)

            except KeyboardInterrupt:
                logger.info("aw-watcher-afk stopped by keyboard interrupt")
                break
