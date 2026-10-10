"""mini Brain - background service.
Keeps the app alive so the HTTP server always runs.
"""
import time
import os

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain_service.log")


def write_log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " - " + msg + "\n")
    except Exception:
        pass


write_log("mini Brain service started")

while True:
    time.sleep(10)
    write_log("heartbeat")
