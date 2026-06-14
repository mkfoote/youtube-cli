from __future__ import annotations

import signal
import subprocess
import time


class PlayerProcess:
    def __init__(
        self,
        foreground: subprocess.Popen[bytes],
        helpers: list[subprocess.Popen[bytes]] | None = None,
    ) -> None:
        self.foreground = foreground
        self.helpers = helpers or []

    def poll(self) -> int | None:
        return self.foreground.poll()

    def wait(self) -> int:
        code = self.foreground.wait()
        for process in self.helpers:
            if process.poll() is None:
                process.terminate()
        for process in self.helpers:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        return code

    def send_signal(self, sig: int) -> None:
        if self.foreground.poll() is None:
            self.foreground.send_signal(sig)

    def terminate(self) -> None:
        for process in [self.foreground, *self.helpers]:
            if process.poll() is None:
                process.terminate()

    def kill(self) -> None:
        for process in [self.foreground, *self.helpers]:
            if process.poll() is None:
                process.kill()

    def wait_stopped(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        for process in [self.foreground, *self.helpers]:
            remaining = max(0.0, deadline - time.monotonic())
            if process.poll() is None:
                process.wait(timeout=remaining)


def pause_process(process: PlayerProcess) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGSTOP)


def resume_process(process: PlayerProcess) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGCONT)


def stop_process(process: PlayerProcess) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait_stopped(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait_stopped(timeout=3)
