"""Container smoke check: PID 1 is tini and no zombie processes are left in the container."""
import glob
import time


def status(path):
    try:
        with open(path) as f:
            return dict(line.split(":", 1) for line in f if ":" in line)
    except OSError:
        return {}


init = status("/proc/1/status").get("Name", "").strip()
assert init == "tini", f"PID 1 is {init!r}, expected tini"
for _ in range(20):
    zombies = [(st["Name"].strip(), st["PPid"].strip()) for st in map(status, glob.glob("/proc/[0-9]*/status"))
               if st.get("State", "").strip().startswith("Z")]
    if not zombies:
        break
    time.sleep(0.5)
assert not zombies, f"zombie processes left: {zombies}"
print("no zombies, PID 1:", init)
