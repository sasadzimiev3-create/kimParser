import json
import logging
import os
import time

log = logging.getLogger("kimparser")


def trace(hypothesis_id, location, message, data):
    details = " ".join("{}={}".format(key, data[key]) for key in data)
    log.info("%s %s", message, details)
    payload = {
        "sessionId": "409c2d",
        "runId": "monitor",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    # #region agent log
    for path in (
        "/Users/geniu/Desktop/parserKIM/.cursor/debug-409c2d.log",
        "/opt/kimparser/.cursor/debug-409c2d.log",
    ):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass
    # #endregion
