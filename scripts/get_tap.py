#!/usr/bin/env python3
import json
import os
import socket
from datetime import datetime

SOCKETS = [
    os.getcwd() + "/printer_data/comms/klippy.sock",
    "/tmp/klippy_uds",
]

probe_name = "bdpressure_probe"

sock_path = next((p for p in SOCKETS if os.path.exists(p)), None)
if sock_path is None:
    raise SystemExit("Could not find klippy socket")

req = {
    "id": 1,
    "method": "load_cell_probe/dump_taps",
    "params": {
        "load_cell_probe": probe_name,
        "response_template": {}
    }
}

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(sock_path)
s.sendall(json.dumps(req).encode() + b"\x03")

buf = b""

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
filename = f"bdpressure_tap_klipper_raw_{timestamp}.json"

while True:
    buf += s.recv(4096)
    while b"\x03" in buf:
        raw, buf = buf.split(b"\x03", 1)
        if not raw:
            continue

        msg = json.loads(raw.decode())
        print(json.dumps(msg)[:500])

        if "tap" in msg.get("params", {}):
            with open(filename, "w") as f:
                json.dump(msg, f, indent=2)
            print("saved bdpressure_tap_klipper_raw.json")
            raise SystemExit
