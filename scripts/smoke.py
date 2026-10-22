"""Run the installed service as a subprocess and exercise its HTTP fallback."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for_health(base_url: str, process: subprocess.Popen) -> dict:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Service exited before becoming healthy")
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=0.5) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError("Service did not become healthy within 10 seconds")


def stop_process(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    port = free_port()
    environment = {
        **os.environ,
        "PORT": str(port),
        "HOST": "127.0.0.1",
        "APP_ENV": "prod",
        "GIGACHAT_CREDENTIALS": " ",
        "LOG_LEVEL": "ERROR",
        "DOCS_ENABLED": "false",
    }
    process = subprocess.Popen([sys.executable, "-m", "task_ai_service"], env=environment)
    base_url = f"http://127.0.0.1:{port}"
    try:
        assert wait_for_health(base_url, process)["status"] == "ok"
        body = json.dumps(
            {"text": "Сервис установлен из wheel. Локальный fallback работает."}
        ).encode()
        request = urllib.request.Request(
            f"{base_url}/process", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.load(response)
            assert result["source"] == "fallback" and result["warning"]
        print("PASS: installed package starts, /health responds, /process returns offline fallback")
    finally:
        stop_process(process)


if __name__ == "__main__":
    main()
