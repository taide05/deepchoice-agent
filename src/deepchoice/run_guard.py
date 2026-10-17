"""Launcher-side final stop mechanism for one research run.

The in-process stop line cannot fire while the event loop is blocked in a
synchronous call — a run was observed stuck in a model load for 36 minutes with
the 900 s deadline already past. This module is the outside enforcement:

  * the clock starts from the run record the service writes when research
    actually begins, not from service start;
  * normal cancellation is attempted first, with a bounded call;
  * the wait for a clean exit is bounded;
  * if the child is still alive, only the dedicated child process the launcher
    created is terminated;
  * the deadline and the actual exit time are recorded next to the run;
  * nothing here needs the HTTP interface to answer — the final step is a
    process signal on that child.

It is a process guard, not a task platform: it owns one child, watches one
active run, and writes one stop record. A forced stop is recorded as forced, and
the final consumption is recorded as unknown rather than as zero.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import time

POLL_S = 0.5
DEFAULT_GRACE_S = 20.0
DEFAULT_KILL_GRACE_S = 5.0

# Tolerance when telling this service's runs from older run records on disk.
RUN_START_TOLERANCE_S = 5.0

_STILL_ACTIVE = 259


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch))


def _pid_alive(pid: int) -> bool:
    """Whether the process is still running, without signalling it."""
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == _STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_pid(pid: int) -> bool:
    """Terminate one process the run record names as this run's service process.

    On Windows a virtualenv's python.exe is a launcher: Popen reports the
    launcher pid while the interpreter that runs the service is its child. The
    record carries the interpreter's own pid, so that is the process stopped.
    """
    try:
        if os.name == "nt":
            result = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                    capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False



def find_active_run(outputs_dir, service_started_epoch: float,
                    service_token: str | None = None) -> dict | None:
    """The newest run this service started that is still marked running.

    When the launcher supplies its per-service token, the record must carry the
    same token: a stale record from an older process can never supply the current
    deadline. The token travels by environment variable rather than by process id,
    because a virtualenv's python.exe is a launcher and the service runs as a
    child process with a different pid.
    """
    outputs = pathlib.Path(outputs_dir)
    if not outputs.is_dir():
        return None
    active = []
    for state_path in outputs.glob("*/run_state.json"):
        try:
            record = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            continue  # a partially written record is not evidence of a run
        if record.get("state") != "running":
            continue
        if service_token is not None:
            if record.get("service_token") != service_token:
                continue
        started = record.get("started_at_epoch")
        if not isinstance(started, (int, float)):
            continue
        if started < service_started_epoch - RUN_START_TOLERANCE_S:
            continue
        active.append({
            "task_id": record.get("task_id") or state_path.parent.name,
            "dir": state_path.parent,
            "state_path": state_path,
            "started_at_epoch": float(started),
            "record": record,
        })
    if not active:
        return None
    return max(active, key=lambda item: item["started_at_epoch"])


def count_confirmed_dispatches(outputs_dir, service_started_epoch: float,
                              service_token: str | None = None) -> int:
    """How many runs this service actually dispatched, as far as the records show.

    A run record is written by the research task itself, so a dispatch that never
    reached a record cannot be counted — hence "confirmed". The value is measured
    from the run records, not assumed.
    """
    outputs = pathlib.Path(outputs_dir)
    if not outputs.is_dir():
        return 0
    count = 0
    for state_path in outputs.glob("*/run_state.json"):
        try:
            record = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if service_token is not None and record.get("service_token") != service_token:
            continue
        started = record.get("started_at_epoch")
        if not isinstance(started, (int, float)):
            continue
        if started < service_started_epoch - RUN_START_TOLERANCE_S:
            continue
        count += 1
    return count


def _read_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _wait_for_exit(child, seconds: float, poll_s: float) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(poll_s)


def _write_stop_record(run: dict, record: dict) -> str | None:
    try:
        path = pathlib.Path(run["dir"]) / "guard_stop.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    except Exception:
        return None


def guard_service(child, outputs_dir, wall_clock_max_s: float,
                  service_started_epoch: float, cancel_fn,
                  service_token: str | None = None,
                  poll_s: float = POLL_S, grace_s: float = DEFAULT_GRACE_S,
                  kill_grace_s: float = DEFAULT_KILL_GRACE_S,
                  clock=time.time, log=print) -> dict:
    """Watch the service child until it exits, or force it down at the deadline.

    `child` is the process the launcher itself spawned and `service_token` is the
    token only this launcher gave its child, so only this service's run can arm
    the deadline. On Windows Popen reports a launcher pid while the interpreter
    that runs the service is its child; the run record carries that interpreter's
    pid and it is the process stopped. `cancel_fn(task_id)` is the normal
    cancellation path and must return quickly (the caller bounds it) — a failure
    or timeout here does not prevent the final step.
    """
    while child.poll() is None:
        run = find_active_run(outputs_dir, service_started_epoch,
                              service_token=service_token)
        if run is None:
            time.sleep(poll_s)
            continue

        deadline = run["started_at_epoch"] + float(wall_clock_max_s)
        now = clock()
        if now < deadline:
            time.sleep(min(poll_s, max(0.05, deadline - now)))
            continue

        # --- normal cancellation first, bounded -----------------------------
        record = {
            "task_id": run["task_id"],
            "forced": False,
            "reason": "wall_clock",
            "service_pid": child.pid,
            "started_at_epoch": run["started_at_epoch"],
            "started_at_iso": _iso(run["started_at_epoch"]),
            "deadline_epoch": deadline,
            "deadline_iso": _iso(deadline),
            "cancel_attempted_at_epoch": clock(),
            "cancel_result": "not_attempted",
            "clean_exit_wait_s": grace_s,
            "final_consumption": "unknown",
            "note": ("final consumption is unknown: the run was stopped outside "
                     "its normal completion"),
        }
        try:
            record["cancel_result"] = str(cancel_fn(run["task_id"]))
        except Exception as exc:  # blocked event loop, refused connection, ...
            record["cancel_result"] = f"failed: {type(exc).__name__}"

        _wait_for_exit(child, grace_s, poll_s)
        if child.poll() is not None:
            record.update({
                "forced": False,
                "reason": "cancelled",
                "exit_code": child.returncode,
                "exit_confirmed": True,
                "exited_at_epoch": clock(),
            })
            record["exited_at_iso"] = _iso(record["exited_at_epoch"])
            record["record_path"] = _write_stop_record(run, record)
            log(f"[guard] run {run['task_id']} exited after cancellation "
                f"(code {child.returncode})")
            return record

        # --- bounded escalation, this run's dedicated process only ----------
        service_pid = run.get("record", {}).get("pid")
        record["terminate_at_epoch"] = clock()
        record["service_process_pid"] = service_pid
        target_terminated = False
        if isinstance(service_pid, int) and service_pid != child.pid:
            # The interpreter that runs the service (a virtualenv python.exe
            # launcher reports a different pid through Popen).
            target_terminated = _terminate_pid(service_pid)
        if not target_terminated:
            child.terminate()
        _wait_for_exit(child, kill_grace_s, poll_s)
        if child.poll() is None:
            record["kill_at_epoch"] = clock()
            if isinstance(service_pid, int) and service_pid != child.pid:
                _terminate_pid(service_pid)
            child.kill()
            _wait_for_exit(child, kill_grace_s, poll_s)

        exited_at = clock()
        exit_confirmed = child.poll() is not None
        if not exit_confirmed and isinstance(service_pid, int):
            exit_confirmed = not _pid_alive(service_pid)
        record.update({
            "forced": True,
            "service_process_terminated": target_terminated,
            "exit_code": child.returncode,
            "exit_confirmed": exit_confirmed,
            "exited_at_epoch": exited_at,
            "exited_at_iso": _iso(exited_at),
            "overrun_s": round(max(0.0, exited_at - deadline), 1),
        })
        if not exit_confirmed:
            record["note"] = ("the dedicated service process could not be "
                              "confirmed gone; no other process was signalled")

        # What the run confirmed about itself before it was stopped.
        counts = _read_json(pathlib.Path(run["dir"]) / "run_limits_counts.json")
        state = _read_json(pathlib.Path(run["dir"]) / "run_state.json")
        record["confirmed_counts"] = {
            "llm_requests": counts.get("llm_requests"),
            "tavily_posts": counts.get("tavily_posts"),
        }
        record["confirmed_dispatch_count"] = count_confirmed_dispatches(
            outputs_dir, service_started_epoch, service_token=service_token)
        record["dispatches_confirmed"] = (
            "measured from the run records of this service; a request in flight "
            "when the process was stopped may not be counted")
        record["record_path"] = _write_stop_record(run, record)
        log(f"[guard] forced stop of run {run['task_id']} at deadline "
            f"{_iso(deadline)}; exit confirmed={exit_confirmed} "
            f"code={child.returncode}")
        return record

    # Child exited on its own.
    return {
        "forced": False,
        "reason": "service_exited",
        "exit_code": child.returncode,
        "exit_confirmed": True,
        "exited_at_epoch": clock(),
        "final_consumption": "recorded_by_run",
    }
