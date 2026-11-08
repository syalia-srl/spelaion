import tempfile
import threading
import time
from pathlib import Path

from spelaion import Limits, Mount, Sandbox

print(Limits())
for bad in ({"timeout_s": 0}, {"max_output": 0}, {"max_disk": -1}, {"memory_mb": True}):
    try:
        Limits(**bad)
    except ValueError as e:
        print(e)
work = Path(tempfile.mkdtemp())
cache = Path(tempfile.mkdtemp())
limits = Limits(timeout_s=2, max_output=200, max_disk=400, memory_mb=64)
sb = Sandbox(
    [Mount("/work", host=work), Mount("/cache", host=cache)],
    cwd="/work",
    limits=limits,
)
r = sb.bash("echo start > keep.txt; sleep 999")
print("timed_out:", r.timed_out, "exit code:", r.exit_code)
print(r.stderr, end="")
print("after the restart:", sb.bash("cat keep.txt").stdout, end="")
r = sb.bash("timeout 0.3 sleep 999; echo status=$?")
print(r.stdout, end="")
print("timed_out:", r.timed_out, "exit code:", r.exit_code)
r = sb.bash("seq 1 100")
print(r.stdout, end="")
print("characters:", len(r.stdout))
r = sb.bash("seq 1 50 > /work/a.txt")
print("first write:", r.exit_code, (work / "a.txt").stat().st_size, "bytes")
r = sb.bash("seq 1 100 > /cache/b.txt")
print(r.stderr, end="")
print("exit code:", r.exit_code)
print("work:", sorted(p.name for p in work.iterdir()))
print("cache:", sorted(p.name for p in cache.iterdir()))
r = sb.bash("rm /work/a.txt; seq 1 100 > /cache/b.txt; wc -c /cache/b.txt")
print(r.stdout, end="")
r = sb.bash("seq 1 10000000 | wc -l")
print(r.stderr, end="")
print("exit code:", r.exit_code)
print("still alive:", sb.bash("echo alive").stdout, end="")
started = time.monotonic()


def slow():
    sb.bash("sleep 0.4")


threads = [threading.Thread(target=slow) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print(f"two 0.4 s calls took {time.monotonic() - started:.2f} s")
print("work:", sorted(p.name for p in work.iterdir()))
print("cache:", sorted(p.name for p in cache.iterdir()))
sb.close()
