import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("kimparser")

WEEK_SECONDS = 7 * 24 * 60 * 60


class KeywordStats:
    def __init__(self, path):
        self.path = Path(path)
        self.events = []
        self._lock = threading.Lock()
        self._load()

    def record(self, keyword, now=None):
        if not keyword:
            return
        moment = self._moment(now)
        with self._lock:
            self.events.append([moment, keyword])
            self.events = self._fresh(moment)
            self._save()

    def top(self, now=None, limit=3):
        moment = self._moment(now)
        with self._lock:
            fresh = list(self._fresh(moment))
        counts = {}
        for _, keyword in fresh:
            counts[keyword] = counts.get(keyword, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return ranked[:limit]

    def _moment(self, now):
        if now is None:
            return int(time.time())
        return int(now)

    def _fresh(self, moment):
        cutoff = moment - WEEK_SECONDS
        return [item for item in self.events if item[0] >= cutoff]

    def _load(self):
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text())
        except (OSError, ValueError):
            log.warning("Файл статистики повреждён, начинаю заново")
            return
        if not isinstance(payload, list):
            log.warning("Файл статистики повреждён, начинаю заново")
            return
        events = []
        for item in payload:
            if (
                isinstance(item, list)
                and len(item) == 2
                and isinstance(item[0], (int, float))
                and isinstance(item[1], str)
                and item[1]
            ):
                events.append([int(item[0]), item[1]])
        self.events = events

    def _save(self):
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.events, ensure_ascii=False))
        tmp.chmod(0o600)
        tmp.replace(self.path)
