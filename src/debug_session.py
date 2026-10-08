import json
import os
import time


def agent_log(hypothesis_id, location, message, data, run_id="pre-fix"):
    payload = {
        "sessionId": "409c2d",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
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
