"""Detect the legacy Douyin capture helper without controlling its process."""

import psutil


def legacy_douyin_grabber_pids() -> list[int]:
    result = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if (process.info.get("name") or "").casefold() == "wssbarrageserver.exe":
                result.append(process.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return result
