"""Launcher-side final stop mechanism for one research run.

The in-process stop line cannot fire while the event loop is blocked in a
synchronous call — a run was observed stuck in a model load for 36 minutes with
the 900 s deadline already past. This module is the outside enforcement:

  * the clock starts from the run record the service writes when research
    actually begins, not from service start;
  * normal cancellation is attempted first, with a bounded call;
  * the wait for a clean exit is bounded;
  * the process that is stopped and the process whose death confirms the stop are
    bound by the launch relationship: the launcher enumerated the children of
    the process it created, and the run record's pid is only a cross-check, never
    a standalone ownership proof;
  * a task that reports itself finished or cancelled does not prove the process
    stopped — the guard keeps enforcing the deadline until the process is gone;
  * the deadline and the actual exit time are recorded next to the run;
  * nothing here needs the HTTP interface to answer — the final step is a
    process signal on a process the launcher created.

It is a process guard, not a task platform: it owns one child tree, watches one
active run, and writes one stop record. A forced stop is recorded as forced; if
the stop cannot be confirmed it is recorded as failed together with the process
identities that are still alive.
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
_TH32CS_SNAPPROCESS = 0x00000002


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(epoch))


def _pid_alive(pid: int) -> bool:
    """Whether the process is still running, without signalling it."""
    if not isinstance(pid, int) or pid <= 0:
        return False
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


def direct_children(parent_pid: int) -> list[int] | None:
    """The direct children of a process, or None if enumeration is unavailable.

    This is how the guard reuses the launch relationship: a virtualenv's
    python.exe is a redirector that starts the real interpreter as its child, and
    only that child runs the service.
    """
    if not isinstance(parent_pid, int) or parent_pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snapshot = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        invalid = wintypes.HANDLE(-1).value
        if snapshot in (invalid, None):
            return None
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            ok = k32.Process32First(snapshot, ctypes.byref(entry))
            found = []
            while ok:
                if int(entry.th32ParentProcessID) == int(parent_pid):
                    found.append(int(entry.th32ProcessID))
                ok = k32.Process32Next(snapshot, ctypes.byref(entry))
            return found
        except Exception:
            return None
        finally:
            k32.CloseHandle(snapshot)

    proc = pathlib.Path("/proc")
    if proc.is_dir():
        found = []
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
                # pid (comm) state ppid ...  — comm may contain spaces/parens.
                after = text.rsplit(")", 1)[-1].split()
                if int(after[1]) == int(parent_pid):
                    found.append(int(entry.name))
            except Exception:
                continue
        return found
    return None


def bind_service_process(launcher_pid: int, record_pid) -> dict:
    """Bind the actual service interpreter to the process the launcher created.

    The run record's pid is a cross-check, not proof: the record file could name
    an unrelated process. What is trusted is the launch relationship — the
    launcher created `launcher_pid`, and the interpreter must be one of its
    descendants.
    """
    children = direct_children(launcher_pid)
    result = {
        "launcher_pid": launcher_pid,
        "record_pid": record_pid,
        "record_pid_matched_launch": None,
        "bound_pid": None,
        "source": "unresolved",
        "candidates": children,
        "reason": "",
    }
    if children is None:
        result["source"] = "unavailable"
        result["reason"] = "process enumeration unavailable; launch relationship cannot be checked"
        return result
    if isinstance(record_pid, int) and record_pid == launcher_pid:
        result.update(bound_pid=record_pid, source="record_is_launcher",
                      record_pid_matched_launch=True)
        return result
    if isinstance(record_pid, int) and record_pid in children:
        result.update(bound_pid=record_pid, source="record_corroborated",
                      record_pid_matched_launch=True)
        return result
    if len(children) == 1:
        # The redirector started exactly one child: the interpreter that runs the
        # service. The record's pid is not used to pick a target.
        result.update(bound_pid=children[0], source="launch_relationship",
                      record_pid_matched_launch=False)
        result["reason"] = ("the run record's pid is not a child of the process "
                            "the launcher created; the launch relationship is used")
        return result
    result["record_pid_matched_launch"] = False
    result["reason"] = ("the run record's pid is not a child of the launcher's "
                        "process and the launch relationship is ambiguous")
    return result


def terminate_pid(pid: int) -> bool:
    """Terminate one process the guard has bound to this run's launch tree."""
    try:
        if os.name == "nt":
            result = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                    capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


# Backwards-compatible alias: the guard is the only caller.
_terminate_pid = terminate_pid


def find_active_run(outputs_dir, service_started_epoch: float,
                    service_token: str | None = None) -> dict | None:
    """The newest run this service started that is still marked running.

    The token identifies the service instance, not a process. Ownership of the
    process is established separately by `bind_service_process`.
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
        if service_token is not None and record.get("service_token") != service_token:
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


def _wait_for_death(pid: int | None, seconds: float, poll_s: float) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(poll_s)


def _write_stop_record(run: dict, record: dict) -> str | None:
    try:
        path = pathlib.Path(run["dir"]) / "guard_stop.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    except Exception:
        return None


def _residual_identity(binding: dict, child) -> dict:
    """Who is still alive, so an unconfirmed stop names what remains."""
    residual = []
    bound = binding.get("bound_pid")
    if bound and _pid_alive(bound):
        residual.append({"pid": bound, "role": "service_interpreter",
                         "alive": True})
    if child.poll() is None:
        residual.append({"pid": child.pid, "role": "launcher_created_process",
                         "alive": True})
    return {
        "bound_pid": bound,
        "binding_source": binding.get("source"),
        "record_pid": binding.get("record_pid"),
        "residual_pids": residual,
    }


def _stop_bound_process(child, binding: dict, kill_grace_s: float,
                        poll_s: float) -> dict:
    """Stop and confirm the bound service interpreter.

    Exit is confirmed by the bound interpreter's death, not by the launcher
    process exiting. If only the launcher process exits, the execution has not
    been shown to stop.
    """
    bound = binding.get("bound_pid")
    record = {
        "binding": binding,
        "record_pid_signalled": False,
        "bound_pid_signalled": False,
        "termination_failures": 0,
    }
    if bound is None:
        record["stop_failed"] = True
        record["note"] = ("no process was bound to the launcher's process tree; "
                          "no termination signal was sent to an unverified pid")
        return record | {"exit_confirmed": False, "launcher_exit_confirmed": child.poll() is not None}

    # Only the bound interpreter is targeted; the record pid is never signalled
    # unless it is the bound interpreter.
    if terminate_pid(bound):
        record["bound_pid_signalled"] = True
    else:
        record["termination_failures"] += 1
    record["record_pid_signalled"] = (bound == binding.get("record_pid"))
    _wait_for_death(bound, kill_grace_s, poll_s)
    if _pid_alive(bound):
        record["termination_failures"] += 1
        terminate_pid(bound)
        _wait_for_death(bound, kill_grace_s, poll_s)

    interpreter_dead = not _pid_alive(bound)

    # The launcher-created process may be a redirector; let it settle, then reap
    # it as owned cleanup. Its exit is recorded but is not the exit confirmation.
    _wait_for_exit(child, kill_grace_s, poll_s)
    if child.poll() is None:
        child.terminate()
        _wait_for_exit(child, kill_grace_s, poll_s)
    if child.poll() is None:
        child.kill()
        _wait_for_exit(child, kill_grace_s, poll_s)

    record["exit_confirmed"] = interpreter_dead
    record["launcher_exit_confirmed"] = child.poll() is not None
    record["stop_failed"] = not interpreter_dead
    if not interpreter_dead:
        record["note"] = ("the bound service interpreter could not be confirmed "
                          "gone; the stop is reported as failed")
    record["residual"] = _residual_identity(binding, child)
    return record


def _force_stop(run: dict, child, outputs_dir, service_started_epoch: float,
                service_token: str | None, deadline: float, reason: str,
                cancel_fn, grace_s: float, kill_grace_s: float, poll_s: float,
                clock, log, task_state_at_stop: str | None = None) -> dict:
    """Cancel first, then stop the bound interpreter and record what happened."""
    record = {
        "task_id": run["task_id"],
        "forced": True,
        "reason": reason,
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
        "task_state_at_stop": task_state_at_stop,
    }
    try:
        record["cancel_result"] = str(cancel_fn(run["task_id"]))
    except Exception as exc:  # blocked event loop, refused connection, ...
        record["cancel_result"] = f"failed: {type(exc).__name__}"

    # A task terminal state is not proof that execution stopped (a cancelled
    # coroutine can leave a worker thread blocked); the guard waits on the
    # process, not on the record.
    _wait_for_exit(child, grace_s, poll_s)

    binding = bind_service_process(child.pid, run.get("record", {}).get("pid"))
    stop = _stop_bound_process(child, binding, kill_grace_s, poll_s)
    record.update(stop)
    record["terminate_at_epoch"] = clock()
    record["exited_at_epoch"] = clock()
    record["exited_at_iso"] = _iso(record["exited_at_epoch"])
    record["overrun_s"] = round(max(0.0, record["exited_at_epoch"] - deadline), 1)

    counts = _read_json(pathlib.Path(run["dir"]) / "run_limits_counts.json")
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
    log(f"[guard] stopped run {run['task_id']} ({reason}); "
        f"exit confirmed={record['exit_confirmed']} "
        f"bound_pid={binding.get('bound_pid')} source={binding.get('source')}")
    return record


def guard_service(child, outputs_dir, wall_clock_max_s: float,
                  service_started_epoch: float, cancel_fn,
                  service_token: str | None = None,
                  poll_s: float = POLL_S, grace_s: float = DEFAULT_GRACE_S,
                  kill_grace_s: float = DEFAULT_KILL_GRACE_S,
                  clock=time.time, log=print) -> dict:
    """Watch the service child until it exits, or stop it at the deadline.

    `child` must be the process the launcher itself created; ownership of the
    actual interpreter is established through that launch relationship, not by a
    pid in a file. `cancel_fn(task_id)` is the normal cancellation path and must
    return quickly — a failure or timeout here does not prevent the final step.
    """
    armed: dict | None = None
    while child.poll() is None:
        run = find_active_run(outputs_dir, service_started_epoch,
                              service_token=service_token)
        if run is not None:
            armed = run
        if armed is not None:
            state_record = _read_json(armed["state_path"])
            task_state = state_record.get("state")
            if task_state == "complete":
                # The run finished on its own; the service may keep serving, so
                # its deadline no longer governs this process.
                armed = None
            else:
                # running, or terminal-but-maybe-still-executing (failed /
                # cancelled): a task state alone does not prove the process
                # stopped, so the deadline keeps applying.
                deadline = armed["started_at_epoch"] + float(wall_clock_max_s)
                if clock() >= deadline:
                    return _force_stop(
                        armed, child, outputs_dir, service_started_epoch,
                        service_token, deadline, "wall_clock", cancel_fn,
                        grace_s, kill_grace_s, poll_s, clock, log,
                        task_state_at_stop=task_state)
                time.sleep(min(poll_s, max(0.05, deadline - clock())))
                continue
        time.sleep(poll_s)

    # The launcher-created process exited. If a run was armed, its interpreter may
    # still be alive (a redirector can exit while its child keeps running): clean
    # up and confirm against the interpreter, not against this exit.
    if armed is not None:
        deadline = armed["started_at_epoch"] + float(wall_clock_max_s)
        state_record = _read_json(armed["state_path"])
        record_pid = armed.get("record", {}).get("pid")
        binding_probe = bind_service_process(child.pid, record_pid)
        if binding_probe.get("bound_pid") and _pid_alive(binding_probe["bound_pid"]):
            return _force_stop(
                armed, child, outputs_dir, service_started_epoch, service_token,
                deadline, "launcher_exited", cancel_fn, grace_s, kill_grace_s,
                poll_s, clock, log,
                task_state_at_stop=state_record.get("state"))

        # Nothing could be bound, but the record still names a live process. It is
        # not proof of ownership, so it is not signalled — and the stop cannot be
        # reported as confirmed.
        if (binding_probe.get("bound_pid") is None
                and isinstance(record_pid, int) and _pid_alive(record_pid)):
            record = {
                "task_id": armed["task_id"],
                "forced": True,
                "reason": "launcher_exited",
                "service_pid": child.pid,
                "started_at_epoch": armed["started_at_epoch"],
                "started_at_iso": _iso(armed["started_at_epoch"]),
                "deadline_epoch": deadline,
                "deadline_iso": _iso(deadline),
                "final_consumption": "unknown",
                "binding": binding_probe,
                "record_pid_signalled": False,
                "bound_pid_signalled": False,
                "exit_confirmed": False,
                "launcher_exit_confirmed": True,
                "stop_failed": True,
                "task_state_at_stop": state_record.get("state"),
                "note": ("the launcher-created process exited and no interpreter "
                         "could be bound to it; the process named in the record was "
                         "not signalled and its stop is unconfirmed"),
                "residual": {
                    "bound_pid": None,
                    "binding_source": binding_probe.get("source"),
                    "record_pid": record_pid,
                    "residual_pids": [{"pid": record_pid, "role": "record_pid",
                                       "alive": True}],
                },
                "confirmed_dispatch_count": count_confirmed_dispatches(
                    outputs_dir, service_started_epoch, service_token=service_token),
                "exited_at_epoch": clock(),
            }
            record["exited_at_iso"] = _iso(record["exited_at_epoch"])
            record["record_path"] = _write_stop_record(armed, record)
            log(f"[guard] stop NOT confirmed for run {armed['task_id']}: "
                f"no bound interpreter; residual record pid {record_pid}")
            return record
        _wait_for_death(binding_probe.get("bound_pid"), kill_grace_s, poll_s)

    return {
        "forced": False,
        "reason": "service_exited",
        "exit_code": child.returncode,
        "exit_confirmed": child.poll() is not None,
        "exited_at_epoch": clock(),
        "exited_at_iso": _iso(clock()),
        "final_consumption": "recorded_by_run",
    }
