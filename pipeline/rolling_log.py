"""Tee a crawl's output into a size-capped log file, so a long run leaves something to read.

    python3 -u mb_crawl.py projects hyderabad | python3 rolling_log.py logs/hyderabad-crawl.log

A city the size of Hyderabad takes hours and prints a line per checkpoint, per parse failure and per
block. Redirected to a plain file that is something nobody trims; redirected to /dev/null it is a crawl
nobody can check on. So the log rolls: the newest KEEP_BYTES stay in <path>, the generation before it in
<path>.1, and anything older is dropped. Every line is stamped, which is how you tell a crawl that is
being slow from one that has stopped, and every line also goes to stdout so a terminal still follows it.
"""
import logging
import logging.handlers
import pathlib
import sys

KEEP_BYTES = 512 * 1024  # ~10,000 crawl lines: a whole run's checkpoints, failures and restarts
KEEP_FILES = 1  # plus the live file, so a roll never takes the last few minutes with it


def tee(stream, path, keep_bytes=KEEP_BYTES, keep_files=KEEP_FILES):
    """Copy stream to stdout line by line, and into a log at path that rolls at keep_bytes."""
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=keep_bytes, backupCount=keep_files)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%m-%d %H:%M:%S"))
    log = logging.getLogger("rolling_log." + str(path))
    log.handlers.clear()  # called twice on one path (a test, a restart in-process) must not log twice
    log.addHandler(handler)
    log.propagate = False
    log.setLevel(logging.INFO)
    for line in stream:
        log.info(line.rstrip("\n"))
        print(line, end="", flush=True)
    handler.close()


if __name__ == "__main__":
    f = pathlib.Path(sys.argv[1])
    f.parent.mkdir(parents=True, exist_ok=True)
    tee(sys.stdin, f)
