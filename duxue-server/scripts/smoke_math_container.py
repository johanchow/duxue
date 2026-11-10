"""Build/run isolation smoke; only disposable math container and volume are touched."""

import json
import subprocess
import sys
import time
from uuid import uuid4


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True)


def main():
    image = sys.argv[1] if len(sys.argv) > 1 else "duxue-math:ci"
    name = "duxue-math-test-" + uuid4().hex[:12]
    volume = name + "-socket"
    docker("volume", "create", volume)
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--pids-limit",
            "16",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "-v",
            volume + ":/run/math",
            image,
        )
        probe = """import socket,json
s=socket.socket(socket.AF_UNIX); s.settimeout(4); s.connect('/run/math/engine.sock')
s.sendall(json.dumps({'op':'equivalent','args':{'left':'90-37','right':'53'}}).encode()+b'\\n')
r=json.loads(s.makefile('rb').readline()); assert r['verdict']=='equal',r
"""
        for attempt in range(30):
            result = subprocess.run(
                ["docker", "exec", name, "python", "-c", probe],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("isolated math executor did not become ready")
        configuration = json.loads(docker("inspect", name))[0]
        host = configuration["HostConfig"]
        assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"]
        assert host["Memory"] == 512 * 1024 * 1024 and host["PidsLimit"] == 16
        assert configuration["Config"]["User"] == "10001:10001"
        check = """import os,socket
assert os.getuid()==10001
assert not any(k in os.environ for k in ('DATABASE_URL','VLM_API_KEY','SECRET_KEY'))
try: open('/forbidden','w')
except OSError: pass
else: raise AssertionError('root filesystem writable')
s=socket.socket(); s.settimeout(0.2)
try: s.connect(('1.1.1.1',443))
except OSError: pass
else: raise AssertionError('outbound network allowed')
"""
        docker("exec", name, "python", "-c", check)
        print(
            "Math container computation, UID, filesystem, network and resource configuration passed."
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            ["docker", "volume", "rm", volume],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


if __name__ == "__main__":
    main()
