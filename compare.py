#!/usr/bin/env python3
"""
console_compare.py
------------------
Scans this Windows PC's hardware and compares it to the current consoles:
Xbox Series X and PlayStation 5 Pro.

Needs no extra packages. It only uses the Python standard library plus the
PowerShell/WMI that comes with Windows 10/11.

Usage (from Command Prompt or PowerShell):
    python console_compare.py                 # scan and print the comparison
    python console_compare.py --save report.txt
    python console_compare.py --json          # print machine-readable JSON
    python console_compare.py --gpu "RTX 3070" # override GPU if not detected
    python console_compare.py --demo          # use a sample PC (works on any OS)

Notes on accuracy
    * GPU and CPU comparisons use an approximate performance index, not a
      benchmark. Treat "ahead / on par / behind" as a ballpark.
    * The index puts GPUs on one scale (RTX 3060 12GB = 100), based on typical
      rasterization performance in games.
    * Console games are tuned to their hardware, so a PC with the same raw
      power usually needs slightly more power to match a console's results.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Console specs (current as of Nov 2026)
# ---------------------------------------------------------------------------
# Xbox Series X (also the Series X25 Limited Edition, which uses the same chip)
# PS5 Pro: 60 CU RDNA GPU. Sony's 33.5 TFLOPS figure counts dual-issue FP32;
#          ~16.7 TFLOPS is the like-for-like number.
CONSOLE_CPU_IPC = 0.92  # console Zen 2 has far less L3 cache than desktop Zen 2

CONSOLES = {
    "Xbox Series X": {
        "cpu": "AMD Zen 2, 8C/16T @ 3.66 GHz",
        "cores": 8, "threads": 16, "ghz": 3.66,
        "gpu": "AMD RDNA 2, 52 CU, 12.15 TFLOPS",
        "gpu_index": 118,          # ~RX 6700 / RTX 2070 Super class
        "memory": "16 GB GDDR6 shared (~13.5 GB for games)",
        "game_mem_gb": 13.5,
        "storage": "1 TB NVMe, 2.4 GB/s raw",
        "ssd_gbps": 2.4,
        "rt": True,
        "upscaling": "FSR (software)",
        "target": "4K60 (often upscaled), up to 120 fps",
    },
    "PS5 Pro": {
        "cpu": "AMD Zen 2, 8C/16T @ 3.5-3.85 GHz",
        "cores": 8, "threads": 16, "ghz": 3.85,
        "gpu": "AMD RDNA, 60 CU, ~16.7 TFLOPS",
        "gpu_index": 150,          # ~RX 7700 XT / RTX 3070 class
        "memory": "16 GB GDDR6 @ 576 GB/s + 2 GB DDR5 for the OS (~13.7 GB for games)",
        "game_mem_gb": 13.7,
        "storage": "2 TB NVMe, 5.5 GB/s raw",
        "ssd_gbps": 5.5,
        "rt": True,
        "upscaling": "PSSR (AI upscaling)",
        "target": "4K60 with ray tracing via PSSR",
    },
}

# ---------------------------------------------------------------------------
# GPU performance index (RTX 3060 12GB = 100). Approximate, raster, desktop.
# ---------------------------------------------------------------------------
GPU_INDEX = {
    # NVIDIA GTX
    "gtx 1050 ti": 30, "gtx 1050": 24, "gtx 1060": 45, "gtx 1070 ti": 66,
    "gtx 1070": 58, "gtx 1080 ti": 92, "gtx 1080": 72, "gtx 1630": 25,
    "gtx 1650 super": 48, "gtx 1650": 38, "gtx 1660 super": 62,
    "gtx 1660 ti": 63, "gtx 1660": 55, "gtx 980 ti": 55, "gtx 980": 45,
    "gtx 970": 38, "gtx 960": 25,
    # NVIDIA RTX 20
    "rtx 2060 super": 97, "rtx 2060": 85, "rtx 2070 super": 115,
    "rtx 2070": 103, "rtx 2080 super": 128, "rtx 2080 ti": 150, "rtx 2080": 122,
    # NVIDIA RTX 30
    "rtx 3050": 70, "rtx 3060 ti": 125, "rtx 3060": 100, "rtx 3070 ti": 148,
    "rtx 3070": 140, "rtx 3080 ti": 195, "rtx 3080": 175, "rtx 3090 ti": 215,
    "rtx 3090": 200,
    # NVIDIA RTX 40
    "rtx 4060 ti": 135, "rtx 4060": 112, "rtx 4070 ti super": 225,
    "rtx 4070 ti": 210, "rtx 4070 super": 195, "rtx 4070": 170,
    "rtx 4080 super": 265, "rtx 4080": 260, "rtx 4090": 330, "rtx 4050": 85,
    # NVIDIA RTX 50
    "rtx 5050": 105, "rtx 5060 ti": 155, "rtx 5060": 135, "rtx 5070 ti": 245,
    "rtx 5070": 195, "rtx 5080": 290, "rtx 5090": 430,
    # AMD RX 400/500/Vega
    "rx 470": 38, "rx 480": 42, "rx 570": 40, "rx 580": 45, "rx 590": 48,
    "rx vega 56": 58, "rx vega 64": 65, "radeon vii": 85,
    # AMD RX 5000
    "rx 5500 xt": 60, "rx 5600 xt": 85, "rx 5700 xt": 105, "rx 5700": 95,
    # AMD RX 6000
    "rx 6400": 38, "rx 6500 xt": 50, "rx 6600 xt": 108, "rx 6650 xt": 115,
    "rx 6600": 95, "rx 6700 xt": 135, "rx 6750 xt": 142, "rx 6700": 120,
    "rx 6800 xt": 195, "rx 6800": 170, "rx 6900 xt": 210, "rx 6950 xt": 220,
    # AMD RX 7000
    "rx 7600 xt": 115, "rx 7600": 110, "rx 7700 xt": 160, "rx 7700": 150,
    "rx 7800 xt": 190, "rx 7900 gre": 205, "rx 7900 xtx": 280, "rx 7900 xt": 240,
    # AMD RX 9000
    "rx 9060 xt": 150, "rx 9060": 130, "rx 9070 xt": 240, "rx 9070": 230,
    # Intel Arc
    "arc a380": 40, "arc a580": 85, "arc a750": 98, "arc a770": 105,
    "arc b570": 100, "arc b580": 118, "arc 140v": 40, "arc 130v": 34,
    "arc graphics": 30,
    # Integrated graphics
    "radeon 890m": 42, "radeon 880m": 36, "radeon 8060s": 140, "radeon 8050s": 110,
    "radeon 780m": 35, "radeon 760m": 28, "radeon 740m": 18, "radeon 680m": 30,
    "radeon 660m": 22, "radeon vega": 15, "radeon graphics": 15,
    "iris xe": 18, "iris plus": 12, "iris": 10, "uhd graphics": 8, "hd graphics": 5,
}

# Current-generation cards, used for upgrade suggestions.
CURRENT_GPUS = ["rtx 5050", "rtx 5060", "rtx 5060 ti", "rtx 5070", "rtx 5070 ti",
                "rtx 5080", "rtx 5090", "rx 9060 xt", "rx 9070", "rx 9070 xt",
                "arc b570", "arc b580"]

LAPTOP_FACTOR = 0.75  # laptop GPUs run at much lower power than desktop parts

# CPU instructions-per-clock relative to Zen 2 = 1.00 (rough)
IPC = {
    "zen1": 0.85, "zen+": 0.90, "zen2": 1.00, "zen3": 1.18, "zen4": 1.30,
    "zen5": 1.42, "fx": 0.55,
    "intel_old": 0.75, "skylake": 0.95, "intel11": 1.10, "intel12": 1.25,
    "ultra1": 1.20, "ultra2": 1.35, "atom": 0.55, "unknown": 1.00,
}
IPC_LABEL = {
    "zen1": "Zen 1", "zen+": "Zen+", "zen2": "Zen 2", "zen3": "Zen 3",
    "zen4": "Zen 4", "zen5": "Zen 5", "fx": "AMD FX", "intel_old": "Intel 2nd-5th gen",
    "skylake": "Intel 6th-10th gen", "intel11": "Intel 11th gen",
    "intel12": "Intel 12th-14th gen", "ultra1": "Core Ultra (Series 1)",
    "ultra2": "Core Ultra (Series 2)", "atom": "Pentium/Celeron", "unknown": "unknown",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class CPUInfo:
    name: str = "Unknown CPU"
    cores: int = 0
    threads: int = 0
    base_ghz: float = 0.0
    boost_ghz: Optional[float] = None   # measured, if we could
    arch: str = "unknown"

    @property
    def clock_for_score(self) -> float:
        # All-core boost is usually ~8% below the single-core peak we measure.
        if self.boost_ghz:
            return self.boost_ghz * 0.92
        return self.base_ghz


@dataclass
class GPUInfo:
    name: str
    vram_gb: Optional[float] = None
    index: Optional[float] = None
    laptop: bool = False
    rt: Optional[bool] = None
    upscaling: str = "Unknown"
    driver: str = ""


@dataclass
class DiskInfo:
    name: str
    kind: str          # "NVMe SSD", "SATA SSD", "HDD", "USB", "Unknown"
    size_gb: float
    est_gbps: Optional[float]


@dataclass
class PCInfo:
    os: str = ""
    model: str = ""
    cpu: CPUInfo = field(default_factory=CPUInfo)
    ram_gb: float = 0.0
    ram_type: str = ""
    ram_mhz: int = 0
    ram_sticks: int = 0
    gpus: list = field(default_factory=list)
    disks: list = field(default_factory=list)
    display: str = ""

    @property
    def main_gpu(self) -> Optional[GPUInfo]:
        scored = [g for g in self.gpus if g.index is not None]
        if scored:
            return max(scored, key=lambda g: g.index)
        return self.gpus[0] if self.gpus else None

    @property
    def best_disk(self) -> Optional[DiskInfo]:
        order = {"NVMe SSD": 0, "SATA SSD": 1, "SSD": 2, "Unknown": 3, "USB": 4, "HDD": 5}
        return min(self.disks, key=lambda d: order.get(d.kind, 9)) if self.disks else None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def normalize_gpu_name(name: str) -> str:
    n = name.lower()
    for junk in ("(r)", "(tm)", "nvidia", "geforce", "amd ", "intel", "graphics card"):
        n = n.replace(junk, " ")
    return re.sub(r"\s+", " ", n).strip()


def lookup_gpu(name: str) -> GPUInfo:
    g = GPUInfo(name=name)
    n = normalize_gpu_name(name)

    # Laptop detection
    if any(k in n for k in ("laptop", "mobile", "max-q", "max q")):
        g.laptop = True
    m = re.search(r"\brx (\d{4})[ms]\b", n)  # e.g. RX 6800M, RX 7600S
    if m:
        g.laptop = True
        n = n.replace(m.group(0), f"rx {m.group(1)}")

    # Longest key first, so "rtx 4070 ti super" wins over "rtx 4070"
    for key in sorted(GPU_INDEX, key=len, reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", n):
            g.index = GPU_INDEX[key] * (LAPTOP_FACTOR if g.laptop else 1.0)
            break

    # Ray tracing hardware and upscaling options
    if "rtx" in n:
        g.rt, g.upscaling = True, "DLSS + FSR"
    elif re.search(r"rx 9\d{3}", n):
        g.rt, g.upscaling = True, "FSR 4 (AI) + FSR"
    elif re.search(r"rx [67]\d{3}", n) or re.search(r"radeon (6|7|8)\d0m|8060s|8050s", n):
        g.rt, g.upscaling = True, "FSR"
    elif "arc" in n:
        g.rt, g.upscaling = True, "XeSS + FSR"
    elif any(k in n for k in ("gtx", "rx 5", "rx 4", "rx 5", "vega", "uhd", "iris", "hd graphics", "radeon graphics")):
        g.rt, g.upscaling = False, "FSR / XeSS (software)"
    return g


def detect_cpu_arch(name: str) -> str:
    n = name.lower()
    if "ryzen ai" in n:
        return "zen5"
    m = re.search(r"threadripper\s+(?:pro\s+)?(\d)\d{3}", n)
    if m:
        return {"1": "zen1", "2": "zen+", "3": "zen2", "5": "zen3",
                "7": "zen4", "9": "zen5"}.get(m.group(1), "unknown")
    m = re.search(r"ryzen\s+\d+\s+(?:pro\s+)?(\d)(\d)(\d)(\d)([a-z]*)", n)
    if m:
        series, third, suffix = m.group(1), m.group(3), m.group(5)
        model = "".join(m.group(i) for i in range(1, 5))
        mobile = suffix.startswith(("u", "h"))
        if series == "1":
            return "zen1"
        if series == "2":
            return "zen+"
        if series in ("3", "4"):
            return "zen2"
        if series == "5":
            return "zen2" if (mobile and model in ("5300", "5500", "5700")) else "zen3"
        if series == "6":
            return "zen3"
        if series == "7":
            if mobile:
                return {"2": "zen2", "3": "zen3"}.get(third, "zen4")
            return "zen4"
        if series == "8":
            return "zen4"
        if series == "9":
            return "zen5"
    if re.search(r"\bfx-?\d", n):
        return "fx"
    m = re.search(r"ultra\s+\d+\s+(\d)\d\d", n)
    if m:
        return "ultra2" if m.group(1) == "2" else "ultra1"
    m = re.search(r"core\s+[357]\s+(\d)\d\d", n)  # Core 5 120U etc. (Raptor Lake)
    if m:
        return "intel12"
    m = re.search(r"i[3579]-(\d{4,5})", n)
    if m:
        d = m.group(1)
        if len(d) == 5 or (len(d) == 4 and d[0] == "1" and d[1] in "0123"):
            gen = int(d[:2])
        else:
            gen = int(d[0])
        if gen >= 12:
            return "intel12"
        if gen == 11:
            return "intel11"
        if gen >= 6:
            return "skylake"
        return "intel_old"
    if any(k in n for k in ("pentium", "celeron", "atom", "athlon")):
        return "atom"
    return "unknown"


def cpu_score(cores: int, threads: int, ghz: float, ipc: float) -> float:
    # Physical cores count fully; extra SMT/HT threads add ~30%.
    return (cores + 0.3 * max(threads - cores, 0)) * ghz * ipc


def console_cpu_score(c: dict) -> float:
    return cpu_score(c["cores"], c["threads"], c["ghz"], CONSOLE_CPU_IPC)


# ---------------------------------------------------------------------------
# Windows data collection
# ---------------------------------------------------------------------------
PS_SCAN = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$o = [ordered]@{}
$o.os   = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version
$o.cs   = Get-CimInstance Win32_ComputerSystem  | Select-Object TotalPhysicalMemory, Manufacturer, Model
$o.cpu  = @(Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed)
$o.ram  = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity, Speed, ConfiguredClockSpeed, SMBIOSMemoryType)
$o.gpu  = @(Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion, CurrentHorizontalResolution, CurrentVerticalResolution, CurrentRefreshRate)
$o.disk = @(Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, Size)
$o | ConvertTo-Json -Depth 4 -Compress
"""

PS_BOOST = r"""
$ErrorActionPreference = 'SilentlyContinue'
$s = (Get-Counter '\Processor Information(*)\% Processor Performance' -SampleInterval 1 -MaxSamples 2).CounterSamples |
     Where-Object { $_.InstanceName -notmatch '_Total' }
($s | Measure-Object CookedValue -Maximum).Maximum
"""


def run_powershell(script: str, timeout: int = 90) -> str:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        raise RuntimeError("PowerShell not found")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return r.stdout.strip()


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def measure_boost_ghz(base_ghz: float) -> Optional[float]:
    """Load one core briefly and read Windows' % Processor Performance counter.
    That reports the real (boosted) clock relative to base, which WMI doesn't."""
    stop = threading.Event()

    def burn():
        x = 1
        while not stop.is_set():
            x = (x * 1103515245 + 12345) & 0xFFFFFFFF

    t = threading.Thread(target=burn, daemon=True)
    t.start()
    try:
        time.sleep(0.3)
        out = run_powershell(PS_BOOST, timeout=30)
    except Exception:
        return None
    finally:
        stop.set()
    try:
        pct = float(out.splitlines()[-1].replace(",", "."))
    except (ValueError, IndexError):
        return None
    ghz = base_ghz * pct / 100.0
    if base_ghz < ghz <= 6.5:
        return round(ghz, 2)
    return None


def vram_from_nvidia_smi() -> dict:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {}
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        out = {}
        for line in r.stdout.strip().splitlines():
            name, mib = [p.strip() for p in line.rsplit(",", 1)]
            out[name.lower()] = float(mib) / 1024
        return out
    except Exception:
        return {}


def vram_from_registry() -> dict:
    """WMI's AdapterRAM caps at 4 GB; the display driver's registry key has the real size."""
    out = {}
    try:
        import winreg
    except ImportError:
        return out
    path = r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        return out
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        if not sub.isdigit():
            continue
        try:
            with winreg.OpenKey(root, sub) as k:
                name = winreg.QueryValueEx(k, "DriverDesc")[0]
                try:
                    mem = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                except OSError:
                    mem = winreg.QueryValueEx(k, "HardwareInformation.MemorySize")[0]
                    if isinstance(mem, bytes):
                        mem = int.from_bytes(mem[:4], "little")
                out[str(name).lower()] = int(mem) / 1024 ** 3
        except OSError:
            continue
    root.Close()
    return out


BUS = {17: "NVMe", 11: "SATA", 7: "USB", 3: "ATA", 8: "RAID", 10: "SAS", 12: "SD", 15: "File"}
MEDIA = {3: "HDD", 4: "SSD", 5: "SCM", 0: "Unspecified"}
RAM_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 35: "LPDDR5"}


def classify_disk(media, bus) -> str:
    media = MEDIA.get(media, media) if isinstance(media, int) else str(media or "")
    bus = BUS.get(bus, bus) if isinstance(bus, int) else str(bus or "")
    if bus == "USB":
        return "USB"
    if bus == "NVMe":
        return "NVMe SSD"
    if media == "HDD":
        return "HDD"
    if media == "SSD":
        return "SATA SSD" if bus in ("SATA", "ATA") else "SSD"
    return "Unknown"


DISK_SPEED = {"NVMe SSD": 3.5, "SATA SSD": 0.55, "SSD": 0.55, "HDD": 0.15, "USB": 0.4}


def scan_windows(gpu_override: Optional[str] = None, measure_boost: bool = True) -> PCInfo:
    raw = json.loads(run_powershell(PS_SCAN) or "{}")
    pc = PCInfo()

    osinfo = raw.get("os") or {}
    pc.os = f"{osinfo.get('Caption', 'Windows')} ({osinfo.get('Version', '?')})"
    cs = raw.get("cs") or {}
    pc.model = f"{cs.get('Manufacturer', '')} {cs.get('Model', '')}".strip()
    pc.ram_gb = round((cs.get("TotalPhysicalMemory") or 0) / 1024 ** 3, 1)

    # CPU (sum cores across sockets, name from the first)
    cpus = as_list(raw.get("cpu"))
    if cpus:
        c = cpus[0]
        name = re.sub(r"\s+", " ", (c.get("Name") or "Unknown CPU")).strip()
        cores = sum(int(x.get("NumberOfCores") or 0) for x in cpus)
        threads = sum(int(x.get("NumberOfLogicalProcessors") or 0) for x in cpus)
        base = (c.get("MaxClockSpeed") or 0) / 1000
        pc.cpu = CPUInfo(name=name, cores=cores, threads=threads,
                         base_ghz=round(base, 2), arch=detect_cpu_arch(name))
        if measure_boost and base:
            pc.cpu.boost_ghz = measure_boost_ghz(base)

    # RAM
    sticks = as_list(raw.get("ram"))
    pc.ram_sticks = len(sticks)
    if sticks:
        s = sticks[0]
        pc.ram_mhz = int(s.get("ConfiguredClockSpeed") or s.get("Speed") or 0)
        pc.ram_type = RAM_TYPES.get(int(s.get("SMBIOSMemoryType") or 0), "")

    # GPUs
    smi = vram_from_nvidia_smi()
    reg = vram_from_registry()
    skip = ("basic display", "remote display", "virtual", "parsec", "meta ", "citrix", "indirect")
    for g in as_list(raw.get("gpu")):
        name = (g.get("Name") or "").strip()
        if not name or any(k in name.lower() for k in skip):
            continue
        info = lookup_gpu(name)
        info.driver = g.get("DriverVersion") or ""
        key = name.lower()
        vram = next((v for k, v in smi.items() if k in key or key in k), None) or reg.get(key)
        if vram is None and g.get("AdapterRAM"):
            vram = g["AdapterRAM"] / 1024 ** 3  # may be capped at 4 GB
        info.vram_gb = round(vram, 1) if vram else None
        pc.gpus.append(info)
        if g.get("CurrentHorizontalResolution") and not pc.display:
            pc.display = (f"{g['CurrentHorizontalResolution']}x{g['CurrentVerticalResolution']}"
                          f" @ {g.get('CurrentRefreshRate', '?')} Hz")
    if not pc.gpus:
        for g in as_list(raw.get("gpu")):
            if g.get("Name"):
                pc.gpus.append(lookup_gpu(g["Name"]))

    if gpu_override:
        o = lookup_gpu(gpu_override)
        if pc.main_gpu and pc.main_gpu.vram_gb:
            o.vram_gb = pc.main_gpu.vram_gb
        pc.gpus.insert(0, o)

    # Disks
    for d in as_list(raw.get("disk")):
        kind = classify_disk(d.get("MediaType"), d.get("BusType"))
        pc.disks.append(DiskInfo(
            name=(d.get("FriendlyName") or "Disk").strip(), kind=kind,
            size_gb=round((d.get("Size") or 0) / 1000 ** 3), est_gbps=DISK_SPEED.get(kind)))
    return pc


def demo_pc(gpu_override: Optional[str] = None) -> PCInfo:
    name = "AMD Ryzen 5 5600X 6-Core Processor"
    pc = PCInfo(
        os="Windows 11 Pro (demo data)", model="Custom desktop",
        cpu=CPUInfo(name=name, cores=6, threads=12, base_ghz=3.7, boost_ghz=4.6,
                    arch=detect_cpu_arch(name)),
        ram_gb=31.9, ram_type="DDR4", ram_mhz=3200, ram_sticks=2,
        display="2560x1440 @ 144 Hz",
    )
    g = lookup_gpu(gpu_override or "NVIDIA GeForce RTX 3060 Ti")
    g.vram_gb = 8.0
    pc.gpus = [g, lookup_gpu("AMD Radeon(TM) Graphics")]
    pc.disks = [DiskInfo("Samsung SSD 980 1TB", "NVMe SSD", 1000, 3.5),
                DiskInfo("ST2000DM008", "HDD", 2000, 0.15)]
    return pc


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def verdict(ratio: Optional[float]) -> str:
    if ratio is None:
        return "Unknown"
    if ratio >= 1.15:
        return "Ahead"
    if ratio >= 0.90:
        return "On par"
    return "Behind"


def compare(pc: PCInfo) -> dict:
    gpu = pc.main_gpu
    cpu_ipc = IPC.get(pc.cpu.arch, 1.0)
    pc_cpu = cpu_score(pc.cpu.cores, pc.cpu.threads, pc.cpu.clock_for_score, cpu_ipc)
    best = pc.best_disk
    result = {"consoles": {}}
    for cname, c in CONSOLES.items():
        gr = (gpu.index / c["gpu_index"]) if gpu and gpu.index else None
        cr = pc_cpu / console_cpu_score(c) if pc_cpu else None
        sr = (best.est_gbps / c["ssd_gbps"]) if best and best.est_gbps else None
        result["consoles"][cname] = {
            "gpu_ratio": round(gr, 2) if gr else None,
            "cpu_ratio": round(cr, 2) if cr else None,
            "storage_ratio": round(sr, 2) if sr else None,
            "gpu": verdict(gr), "cpu": verdict(cr),
        }
    result["pc_cpu_score"] = round(pc_cpu, 1)
    result["pc_gpu_index"] = round(gpu.index, 1) if gpu and gpu.index else None
    return result


def summary_lines(pc: PCInfo, cmp: dict) -> list:
    out = []
    gpu = pc.main_gpu
    sx = cmp["consoles"]["Xbox Series X"]
    pro = cmp["consoles"]["PS5 Pro"]
    g_pro = pro["gpu_ratio"]
    g_sx = sx["gpu_ratio"]

    if g_pro is None:
        out.append("Couldn't identify your graphics card, so the overall gaming verdict is "
                   "incomplete. Re-run with --gpu \"<your card>\" (for example --gpu \"RTX 3070\").")
    elif g_pro >= 1.5:
        out.append("Your graphics card is well beyond both consoles. Expect higher frame rates "
                   "and resolution than the console versions, with room for heavier ray tracing.")
    elif g_pro >= 1.0:
        out.append("Your graphics card matches or beats the PS5 Pro, the most powerful console "
                   "today. Console-quality settings or better at 1440p-4K (with upscaling) are realistic.")
    elif g_sx and g_sx >= 0.9:
        out.append("Your PC is console-class: roughly Xbox Series X level, a bit under the "
                   "PS5 Pro. Console-like settings at 1440p, or 4K with upscaling, are a good target.")
    elif g_sx and g_sx >= 0.5:
        out.append("Your graphics card is below current consoles. Plan on 1080p with "
                   "medium settings (and upscaling) in new games.")
    else:
        out.append("Your graphics card is well below console level. Newer games will need "
                   "low settings at 1080p or lower, and some may not run well.")

    if pro["cpu_ratio"] and g_pro and pro["cpu_ratio"] < 0.9 and g_pro >= 1.0:
        out.append("Your processor is weaker than the consoles' while your graphics card is "
                   "stronger, so the processor may hold back frame rates in demanding games.")
    elif pro["cpu_ratio"] and pro["cpu_ratio"] >= 1.15:
        out.append("Your processor is faster than the consoles' 8-core Zen 2, which helps "
                   "high-frame-rate (120+ fps) gaming.")

    if gpu and gpu.vram_gb and gpu.vram_gb < 8:
        out.append(f"Only {gpu.vram_gb:g} GB of graphics memory: expect to lower texture "
                   "quality below console settings in recent games.")
    elif gpu and gpu.vram_gb and gpu.vram_gb < 12:
        out.append(f"{gpu.vram_gb:g} GB of graphics memory is fine for 1080p-1440p, but some new "
                   "games at console-level textures want 10-12 GB+ (consoles share ~13.5 GB).")

    if pc.ram_gb and pc.ram_gb < 15:
        out.append(f"{pc.ram_gb:g} GB system RAM is low for modern games; 16 GB is the minimum "
                   "and 32 GB is comfortable.")

    best = pc.best_disk
    if best:
        if best.kind == "HDD":
            out.append("No SSD detected. Many new games list an SSD as required, and load "
                       "times will be far longer than on either console.")
        elif best.kind in ("SATA SSD", "SSD"):
            out.append("Your fastest drive is a SATA SSD (~0.55 GB/s), several times slower than "
                       "the consoles' NVMe drives. Fine for most games; an NVMe drive matches consoles.")

    if gpu and g_pro is not None and g_pro < 1.0:
        target = CONSOLES["PS5 Pro"]["gpu_index"]
        picks = sorted((GPU_INDEX[k], k) for k in CURRENT_GPUS if GPU_INDEX[k] >= target)[:3]
        if picks:
            names = ", ".join(k.upper().replace("TI", "Ti") for _, k in picks)
            out.append(f"Current-gen cards at or above PS5 Pro level include: {names}.")
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
class Colors:
    def __init__(self, on: bool):
        self.on = on

    def c(self, text, code):
        return f"\033[{code}m{text}\033[0m" if self.on else text

    def verdict(self, v):
        return self.c(v, {"Ahead": "92", "On par": "93", "Behind": "91"}.get(v, "90"))

    def head(self, t):
        return self.c(t, "1;96")


def bar(value: float, scale: float, width: int = 30) -> str:
    n = max(0, min(width, round(value / scale * width)))
    return "#" * n + "." * (width - n)


def render(pc: PCInfo, cmp: dict, color: bool = True) -> str:
    C = Colors(color)
    L = []
    gpu = pc.main_gpu
    sx, pro = CONSOLES["Xbox Series X"], CONSOLES["PS5 Pro"]

    L.append(C.head("=" * 100))
    L.append(C.head("  YOUR PC vs XBOX SERIES X vs PS5 PRO"))
    L.append(C.head("=" * 100))
    L.append(f"  System : {pc.model or 'Unknown'}  |  {pc.os}")
    if pc.display:
        L.append(f"  Display: {pc.display}")
    L.append("")

    # Side-by-side spec table
    clock = (f"{pc.cpu.boost_ghz:g} GHz boost (measured)" if pc.cpu.boost_ghz
             else f"{pc.cpu.base_ghz:g} GHz base")
    cpu_txt = f"{pc.cpu.name}, {pc.cpu.cores}C/{pc.cpu.threads}T @ {clock} [{IPC_LABEL[pc.cpu.arch]}]"
    if gpu:
        gpu_txt = gpu.name + (f", {gpu.vram_gb:g} GB VRAM" if gpu.vram_gb else "")
        if gpu.laptop:
            gpu_txt += " (laptop)"
    else:
        gpu_txt = "Not detected"
    ram_txt = f"{pc.ram_gb:g} GB {pc.ram_type} {str(pc.ram_mhz) + ' MT/s' if pc.ram_mhz else ''}".strip()
    if pc.ram_sticks:
        ram_txt += f" ({pc.ram_sticks} stick{'s' if pc.ram_sticks != 1 else ''})"
    disk_txt = "; ".join(f"{d.name} ({d.kind}, {d.size_gb:g} GB)" for d in pc.disks) or "Unknown"
    rt_txt = {True: "Yes", False: "No", None: "Unknown"}[gpu.rt if gpu else None]
    up_txt = gpu.upscaling if gpu else "Unknown"

    rows = [
        ("CPU", cpu_txt, sx["cpu"], pro["cpu"]),
        ("GPU", gpu_txt, sx["gpu"], pro["gpu"]),
        ("Memory", ram_txt + " system RAM", sx["memory"], pro["memory"]),
        ("Storage", disk_txt, sx["storage"], pro["storage"]),
        ("Ray tracing", rt_txt, "Yes", "Yes (2-3x PS5)"),
        ("Upscaling", up_txt, sx["upscaling"], pro["upscaling"]),
    ]
    w0, w = 12, 28
    def fmt_row(cells):
        wrapped = [textwrap.wrap(str(cells[0]), w0)] + [textwrap.wrap(str(c), w) or [""] for c in cells[1:]]
        h = max(len(x) for x in wrapped)
        lines = []
        for i in range(h):
            parts = [(wrapped[0][i] if i < len(wrapped[0]) else "").ljust(w0)]
            parts += [(col[i] if i < len(col) else "").ljust(w) for col in wrapped[1:]]
            lines.append("  " + " | ".join(parts))
        return lines
    L += [C.c(line, "1") for line in fmt_row(("", "YOUR PC", "XBOX SERIES X", "PS5 PRO"))]
    L.append("  " + "-" * (w0 + 3 * (w + 3)))
    for r in rows:
        L += fmt_row(r)
        L.append("  " + "-" * (w0 + 3 * (w + 3)))
    L.append("")

    # Performance bars
    L.append(C.head("  ESTIMATED PERFORMANCE (longer bar = faster)"))
    gscale = max(pro["gpu_index"], (gpu.index if gpu and gpu.index else 0)) * 1.1
    L.append("  Graphics")
    if gpu and gpu.index:
        L.append(f"    Your PC        {bar(gpu.index, gscale)}  {gpu.index:6.0f}")
    else:
        L.append("    Your PC        (GPU not recognized - use --gpu)")
    L.append(f"    Xbox Series X  {bar(sx['gpu_index'], gscale)}  {sx['gpu_index']:6.0f}")
    L.append(f"    PS5 Pro        {bar(pro['gpu_index'], gscale)}  {pro['gpu_index']:6.0f}")
    pcs = cmp["pc_cpu_score"]
    sxs, pros = console_cpu_score(sx), console_cpu_score(pro)
    cscale = max(pcs, sxs, pros) * 1.1
    L.append("  Processor")
    L.append(f"    Your PC        {bar(pcs, cscale)}  {pcs:6.1f}")
    L.append(f"    Xbox Series X  {bar(sxs, cscale)}  {sxs:6.1f}")
    L.append(f"    PS5 Pro        {bar(pros, cscale)}  {pros:6.1f}")
    L.append("")

    # Verdicts
    L.append(C.head("  HEAD TO HEAD"))
    for cname, r in cmp["consoles"].items():
        gtxt = f"{r['gpu_ratio']:.2f}x" if r["gpu_ratio"] else "n/a"
        ctxt = f"{r['cpu_ratio']:.2f}x" if r["cpu_ratio"] else "n/a"
        L.append(f"  vs {cname:<14} Graphics: {C.verdict(r['gpu']):<6} ({gtxt})   "
                 f"Processor: {C.verdict(r['cpu']):<6} ({ctxt})")
    L.append("")

    L.append(C.head("  WHAT THIS MEANS"))
    for s in summary_lines(pc, cmp):
        L += textwrap.wrap(s, 96, initial_indent="  * ", subsequent_indent="    ")
    L.append("")
    if not pc.cpu.boost_ghz:
        L.append(C.c("  Note: Windows only reported your processor's base clock; real boost clocks are "
                     "higher,\n  so your processor estimate is probably conservative.", "90"))
    L.append(C.c("  Scores are estimates from a built-in lookup table (RTX 3060 = 100), not a benchmark.", "90"))
    return "\n".join(L)


def to_json(pc: PCInfo, cmp: dict) -> str:
    d = asdict(pc)
    d["main_gpu"] = asdict(pc.main_gpu) if pc.main_gpu else None
    return json.dumps({"pc": d, "comparison": cmp, "consoles": CONSOLES}, indent=2)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Compare this Windows PC to the Xbox Series X and PS5 Pro.")
    ap.add_argument("--gpu", help='Override the detected GPU, e.g. --gpu "RTX 3070"')
    ap.add_argument("--save", metavar="FILE", help="Also save the report to a text file")
    ap.add_argument("--json", action="store_true", help="Print JSON instead of the report")
    ap.add_argument("--demo", action="store_true", help="Use sample PC data (works on any OS)")
    ap.add_argument("--no-boost", action="store_true", help="Skip the 2-second CPU boost-clock check")
    ap.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = ap.parse_args()

    if args.demo:
        pc = demo_pc(args.gpu)
    else:
        if platform.system() != "Windows":
            sys.exit("This scanner needs Windows. Use --demo to see sample output.")
        print("Scanning hardware (takes about 5-10 seconds)...", file=sys.stderr)
        try:
            pc = scan_windows(args.gpu, measure_boost=not args.no_boost)
        except Exception as e:
            sys.exit(f"Hardware scan failed: {e}")

    cmp = compare(pc)
    if args.json:
        print(to_json(pc, cmp))
        return

    use_color = not args.no_color and sys.stdout.isatty()
    if use_color and os.name == "nt":
        os.system("")  # turns on ANSI colors in the Windows console
    print(render(pc, cmp, color=use_color))
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(render(pc, cmp, color=False))
        print(f"\nSaved report to {args.save}")


if __name__ == "__main__":
    main()
