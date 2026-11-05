"""Windows worker ownership and resource admission, without external dependencies."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import functools
import os
from pathlib import Path
import shutil
import subprocess

PROCESS_SYNCHRONIZE = 0x100000
PROCESS_QUERY_MEMORY = 0x410
WAIT_TIMEOUT = 258
JOB_OBJECT_EXTENDED_LIMIT_INFO = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
TH32CS_SNAPPROCESS = 2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class _BasicLimitInfo(ctypes.Structure):
    _fields_ = [
        ('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong), ('flags', w.DWORD),
        ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('processes', w.DWORD),
        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD),
    ]


class _ExtendedLimitInfo(ctypes.Structure):
    _fields_ = [
        ('basic', _BasicLimitInfo), ('io', ctypes.c_ulonglong * 6), ('process_memory', ctypes.c_size_t),
        ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t),
    ]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [('length', w.DWORD), ('load', w.DWORD)] + [
        (n, ctypes.c_ulonglong) for n in (
            'total', 'available', 'total_page', 'available_page', 'total_virtual', 'available_virtual', 'extended'
        )
    ]


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ('ac', w.BYTE), ('battery', w.BYTE), ('percent', w.BYTE),
        ('saver', w.BYTE), ('remaining', w.DWORD), ('full', w.DWORD),
    ]


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD), ('heap', ctypes.c_size_t),
        ('module', w.DWORD), ('threads', w.DWORD), ('parent', w.DWORD), ('priority', w.LONG),
        ('flags', w.DWORD), ('name', w.WCHAR * 260),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [('size', w.DWORD), ('faults', w.DWORD)] + [
        (n, ctypes.c_size_t) for n in (
            'peak', 'working', 'q_peak_page', 'q_page', 'q_peak_nonpage', 'q_nonpage', 'pagefile', 'peak_pagefile'
        )
    ]


@functools.cache
def _kernel():
    if os.name != 'nt':
        raise RuntimeError('Batch OCR requires Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    return kernel


@functools.cache
def _psapi():
    if os.name != 'nt':
        raise RuntimeError('Batch OCR requires Windows')
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(_ProcessMemoryCounters), w.DWORD]
    return psapi


def process_alive(pid):
    kernel = _kernel()
    handle = kernel.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel.CloseHandle(handle)


class ManagedProcess:
    """Worker waits for START until its entire future child tree belongs to our job."""
    def __init__(self, command, log_path):
        kernel = self.kernel = _kernel()
        self.handle = None
        self.process = None
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self.log = Path(log_path).open('ab')
        try:
            self.handle = kernel.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = _ExtendedLimitInfo()
            limits.basic.flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE  # Also covers OCR grandchildren.
            if not kernel.SetInformationJobObject(
                self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFO, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=self.log, stderr=self.log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if not kernel.AssignProcessToJobObject(self.handle, w.HANDLE(int(self.process._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
            self.process.stdin.write(b'START\n')
            self.process.stdin.flush()
            self.process.stdin.close()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=10)
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
        if not self.log.closed:
            self.log.close()


def resources(directory):
    kernel = _kernel()
    memory = _MemoryStatusEx()
    memory.length = ctypes.sizeof(memory)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise ctypes.WinError(ctypes.get_last_error())
    power = _SystemPowerStatus()
    known = kernel.GetSystemPowerStatus(ctypes.byref(power))
    power_ok = bool(known and (power.ac == 1 or power.battery == 128) and not power.saver)
    return dict(
        total_ram=memory.total, available_ram=memory.available, batch_rss=tree_rss(),
        free_disk=shutil.disk_usage(directory).free, power_ok=power_ok,
    )


def tree_rss(root_pid=None):
    kernel = _kernel()
    snapshot = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    parents = {}
    entry = _ProcessEntry32W()
    entry.size = ctypes.sizeof(entry)
    try:
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.pid] = entry.parent
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    pids = {root_pid or os.getpid()}
    while True:
        extended = pids | {pid for pid, parent in parents.items() if parent in pids}
        if extended == pids:
            break
        pids = extended
    total = 0
    psapi = _psapi()
    for pid in pids:
        handle = kernel.OpenProcess(PROCESS_QUERY_MEMORY, False, pid)
        if not handle:
            continue
        try:
            counter = _ProcessMemoryCounters()
            counter.size = ctypes.sizeof(counter)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counter), counter.size):
                total += counter.working
        finally:
            kernel.CloseHandle(handle)
    return total


@contextmanager
def keep_awake():
    kernel = _kernel()
    previous = kernel.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.SetThreadExecutionState(ES_CONTINUOUS)
