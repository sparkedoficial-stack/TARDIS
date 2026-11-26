"""core/governor/telemetry_probes.py - Sondas Ring 0 (/proc PSI, térmicas sysfs, GPU, cgroups v2, swap-bloat, Ollama)."""
from __future__ import annotations

from typing import Union
from core.governor.config import *
from core.governor.config import _atomic_write_json, _facade_hook, _now_iso

def _parse_psi_file(path: Path) -> Dict[str, float]:
    out = {"some_avg10": 0.0, "some_avg60": 0.0, "some_avg300": 0.0, "full_avg10": 0.0, "full_avg60": 0.0}
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if not parts:
                continue
            prefix = parts[0]
            if prefix not in ("some", "full"):
                continue
            for kv in parts[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k in ("avg10", "avg60", "avg300"):
                        key = f"{prefix}_{k}"
                        if key in out:
                            out[key] = float(v)
    except Exception:
        pass
    return out

def _parse_cpulist_count(cpulist: str) -> int:
    """Cuenta CPUs lógicas representadas en un formato cpulist Linux (ej. '8-15', '0-3,8-11')."""
    txt = (cpulist or "").strip()
    if not txt:
        return 0
    total = 0
    for token in txt.split(","):
        tok = token.strip()
        if not tok:
            continue
        if "-" in tok:
            parts = tok.split("-", 1)
            if parts[0].isdigit() and parts[1].isdigit():
                lo, hi = int(parts[0]), int(parts[1])
                if hi >= lo:
                    total += (hi - lo) + 1
        elif tok.isdigit():
            total += 1
    return total

def _read_cpu_thermal() -> Dict[str, Any]:
    """Lee temperatura de paquete CPU (k10temp/coretemp/acpitz) y ventiladores (asus) desde sysfs."""
    hwmon_root = Path("/sys/class/hwmon")
    cpu_temp_c = 0.0
    cpu_source = ""
    fallback_temp_c = 0.0
    fans: Dict[str, int] = {}

    if not hwmon_root.is_dir():
        return {"temp_c": 0.0, "source": "", "fan_rpm": fans}

    try:
        for hdir in sorted(hwmon_root.iterdir()):
            name_file = hdir / "name"
            if not name_file.is_file():
                continue
            name = name_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
            if name in ("k10temp", "coretemp", "zenpower"):
                tfile = hdir / "temp1_input"
                if tfile.is_file():
                    raw = tfile.read_text(encoding="utf-8", errors="ignore").strip()
                    if raw.lstrip("-").isdigit():
                        cpu_temp_c = round(int(raw) / 1000.0, 1)
                        cpu_source = name
            elif name == "acpitz" and fallback_temp_c <= 0.0:
                tfile = hdir / "temp1_input"
                if tfile.is_file():
                    raw = tfile.read_text(encoding="utf-8", errors="ignore").strip()
                    if raw.lstrip("-").isdigit():
                        fallback_temp_c = round(int(raw) / 1000.0, 1)
            elif name == "asus":
                for idx, label in ((1, "cpu"), (2, "gpu")):
                    ffile = hdir / f"fan{idx}_input"
                    if ffile.is_file():
                        raw = ffile.read_text(encoding="utf-8", errors="ignore").strip()
                        if raw.isdigit():
                            fans[label] = int(raw)
    except Exception:
        pass

    if cpu_temp_c <= 0.0 and fallback_temp_c > 0.0:
        cpu_temp_c = fallback_temp_c
        cpu_source = "acpitz"

    return {"temp_c": cpu_temp_c, "source": cpu_source, "fan_rpm": fans}

def _read_cpu_power_profile() -> Dict[str, Any]:
    """Lee telemetría Ring 0 de cpufreq/amd-pstate-epp/boost y platform_profile vía sysfs (<0.1ms)."""
    def _read_txt(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return ""

    cpufreq_dir = Path("/sys/devices/system/cpu/cpu0/cpufreq")
    driver = _read_txt(cpufreq_dir / "scaling_driver")
    governor = _read_txt(cpufreq_dir / "scaling_governor")
    epp = _read_txt(cpufreq_dir / "energy_performance_preference")
    boost_raw = _read_txt(Path("/sys/devices/system/cpu/cpufreq/boost"))
    boost_enabled: Optional[bool] = (
        boost_raw == "1" if boost_raw in ("0", "1") else None
    )
    platform_profile = _read_txt(Path("/sys/firmware/acpi/platform_profile")).lower()
    if platform_profile == "quiet":
        power_profile = "power-saver"
    elif platform_profile in ("balanced", "performance"):
        power_profile = platform_profile
    elif governor == "performance":
        power_profile = "performance"
    elif governor == "powersave":
        power_profile = "balanced"
    else:
        power_profile = ""

    return {
        "power_profile": power_profile,
        "platform_profile": platform_profile,
        "scaling_driver": driver,
        "scaling_governor": governor,
        "epp": epp,
        "boost": boost_enabled,
    }

def _read_meminfo_mb() -> Dict[str, float]:
    info: Dict[str, float] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line:
                continue
            k, rest = line.split(":", 1)
            toks = rest.strip().split()
            if toks and toks[0].isdigit():
                info[k.strip()] = round(int(toks[0]) / 1024.0, 1)
    except Exception:
        pass
    total = info.get("MemTotal", 0.0)
    avail = info.get("MemAvailable", 0.0)
    used = max(0.0, total - avail)
    swap_total = info.get("SwapTotal", 0.0)
    swap_free = info.get("SwapFree", 0.0)
    swap_used = max(0.0, swap_total - swap_free)
    return {
        "total_mb": round(total, 1),
        "available_mb": round(avail, 1),
        "used_mb": round(used, 1),
        "used_pct": round((used / total) * 100.0, 1) if total > 0 else 0.0,
        "swap_total_mb": round(swap_total, 1),
        "swap_used_mb": round(swap_used, 1),
    }

def _read_loadavg() -> Tuple[float, float, float]:
    try:
        parts = Path("/proc/loadavg").read_text(encoding="utf-8").split()
        return float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        return 0.0, 0.0, 0.0

def _read_gpu() -> Dict[str, Any]:
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.free,memory.total,pstate,power.draw,clocks.gr,clocks.mem",
                "--format=csv,noheader,nounits",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            cols = [c.strip() for c in res.stdout.strip().splitlines()[0].split(",")]
            if len(cols) >= 6:
                v_used = float(cols[3])
                v_tot = float(cols[5])

                def _opt_float(idx: int) -> float:
                    if idx < len(cols):
                        try:
                            return float(cols[idx])
                        except ValueError:
                            return 0.0
                    return 0.0

                return {
                    "available": True,
                    "name": cols[0],
                    "temp_c": float(cols[1]),
                    "util_pct": float(cols[2]),
                    "vram_used_mb": v_used,
                    "vram_free_mb": float(cols[4]),
                    "vram_total_mb": v_tot,
                    "vram_used_pct": round((v_used / v_tot) * 100.0, 1) if v_tot > 0 else 0.0,
                    "pstate": cols[6] if len(cols) > 6 else "",
                    "power_w": round(_opt_float(7), 2),
                    "clock_gr_mhz": int(round(_opt_float(8))),
                    "clock_mem_mhz": int(round(_opt_float(9))),
                }
    except Exception:
        pass
    return {
        "available": False,
        "temp_c": 0.0,
        "util_pct": 0.0,
        "vram_used_mb": 0.0,
        "vram_free_mb": 0.0,
        "vram_total_mb": 0.0,
        "vram_used_pct": 0.0,
        "pstate": "",
        "power_w": 0.0,
        "clock_gr_mhz": 0,
        "clock_mem_mhz": 0,
    }

def _read_amd_igpu() -> Dict[str, Any]:
    """Telemetría best-effort de la iGPU AMD Radeon (card1) para el Silicon Lab."""
    base = Path("/sys/class/drm/card1/device")
    out: Dict[str, Any] = {
        "available": False,
        "busy_pct": 0.0,
        "temp_c": 0.0,
        "vram_used_mb": 0.0,
        "gtt_used_mb": 0.0,
        "gtt_total_mb": 0.0,
        "gtt_free_mb": 0.0,
    }
    try:
        if not base.exists():
            return out
        out["available"] = True
        busy_file = base / "gpu_busy_percent"
        if busy_file.exists():
            try:
                out["busy_pct"] = float(busy_file.read_text().strip())
            except ValueError:
                out["busy_pct"] = 0.0
        mem_vram = base / "mem_info_vram_used"
        if mem_vram.exists():
            try:
                out["vram_used_mb"] = round(float(mem_vram.read_text().strip()) / (1024 * 1024), 1)
            except ValueError:
                pass
        mem_gtt_used = base / "mem_info_gtt_used"
        if mem_gtt_used.exists():
            try:
                out["gtt_used_mb"] = round(float(mem_gtt_used.read_text().strip()) / (1024 * 1024), 1)
            except ValueError:
                pass
        mem_gtt_total = base / "mem_info_gtt_total"
        if mem_gtt_total.exists():
            try:
                out["gtt_total_mb"] = round(float(mem_gtt_total.read_text().strip()) / (1024 * 1024), 1)
            except ValueError:
                pass
        out["gtt_free_mb"] = round(max(0.0, out["gtt_total_mb"] - out["gtt_used_mb"]), 1)
        # temperatura amdgpu hwmon
        for hw in (base / "hwmon").glob("hwmon*"):
            tfile = hw / "temp1_input"
            if tfile.exists():
                try:
                    out["temp_c"] = round(float(tfile.read_text().strip()) / 1000.0, 1)
                except ValueError:
                    pass
                break
    except Exception:
        out["available"] = False
    return out

def _probe_temporal_brain_busy(sock_path: Path = Path("/tmp/temporal_brain.sock"), timeout: float = 0.5) -> bool:
    """Consulta /slots de TemporalBrain por socket UNIX (<1ms) para saber si hay inferencia CUDA activa."""
    if not sock_path.exists():
        return False
    try:
        import socket as _sock

        with _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(sock_path))
            s.sendall(b"GET /slots HTTP/1.0\r\nHost: localhost\r\n\r\n")
            chunks: List[bytes] = []
            while True:
                buf = s.recv(4096)
                if not buf:
                    break
                chunks.append(buf)
        raw = b"".join(chunks).decode("utf-8", errors="ignore")
        body = raw.split("\r\n\r\n", 1)[-1].strip()
        if body.startswith("["):
            slots = json.loads(body)
            return any(bool(sl.get("is_processing")) for sl in slots if isinstance(sl, dict))
    except Exception:
        pass
    return False

def _read_display_session_state() -> Dict[str, Any]:
    """Inspecciona conectores DRM físicos, firma Hyprland y actividad CUDA de TemporalBrain (<2 ms)."""
    connected = 0
    total_connectors = 0
    try:
        drm_root = Path("/sys/class/drm")
        if drm_root.is_dir():
            for st_file in drm_root.glob("card*-*/status"):
                total_connectors += 1
                try:
                    if st_file.read_text(encoding="utf-8", errors="ignore").strip().lower() == "connected":
                        connected += 1
                except Exception:
                    continue
    except Exception:
        pass

    hypr_sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "").strip()
    if not hypr_sig:
        hypr_dir = RUNTIME_DIR / "hypr"
        if hypr_dir.is_dir():
            try:
                dirs = sorted(
                    (p for p in hypr_dir.iterdir() if p.is_dir()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if dirs:
                    hypr_sig = dirs[0].name
            except Exception:
                pass

    tb_busy = _facade_hook("_probe_temporal_brain_busy", _probe_temporal_brain_busy)()
    return {
        "connected_displays": connected,
        "total_connectors": total_connectors,
        "headless_or_display_off": (total_connectors > 0 and connected == 0),
        "hyprland_signature": hypr_sig,
        "temporal_brain_busy": tb_busy,
    }

def _extract_cli_int_flag(cmdline: str, flags: Tuple[str, ...]) -> int:
    """Extrae un valor entero de un flag CLI en cmdline (ej. '--threads-batch 16' o '-tb=16')."""
    if not cmdline:
        return 0
    for fl in flags:
        m = re.search(rf"(?:^|\s){re.escape(fl)}(?:=|\s+)(\d+)(?:\s|$)", cmdline)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return 0
    return 0

def _count_runnable_threads(pid: int) -> int:
    """Cuenta hilos en estado 'R' (runnable/running) de un PID vía /proc/<pid>/task/*/stat."""
    task_dir = Path(f"/proc/{pid}/task")
    if not task_dir.is_dir():
        return 0
    runnable = 0
    try:
        for tid_dir in task_dir.iterdir():
            try:
                st = (tid_dir / "stat").read_text(encoding="utf-8", errors="ignore")
                rparen = st.rfind(")")
                if rparen > 0:
                    rest = st[rparen + 2 :].split()
                    if rest and rest[0] == "R":
                        runnable += 1
            except Exception:
                continue
    except Exception:
        pass
    return runnable

def _inspect_cgroup_units(
    units: Iterable[str] = ALL_INSPECTED_UNITS,
    cgroup_app_slice: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Inspecciona cgroup v2 (`app.slice/<unit>`) con latencia <1 ms (lectura pura sysfs/procfs):
      - Retorna `(cgroup_pressure, oversubscribed_units)`.
      - Detecta sobresuscripción de hilos frente al `cpuset.cpus.effective` real
        (causa clásica de thrashing de barrera ggml y CPU PSI > 60%).
    """
    uid = os.getuid()
    app_slice = cgroup_app_slice or Path(
        f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice"
    )
    if not app_slice.is_dir():
        return [], []

    pressure_rows: List[Dict[str, Any]] = []
    oversubscribed: List[Dict[str, Any]] = []

    for unit in units:
        cg = app_slice / unit
        if not cg.is_dir():
            continue
        try:
            cpuset_raw = ""
            for fname in ("cpuset.cpus.effective", "cpuset.cpus"):
                fp = cg / fname
                if fp.is_file():
                    cpuset_raw = fp.read_text(encoding="utf-8", errors="ignore").strip()
                    if cpuset_raw:
                        break
            eff_cpus = _parse_cpulist_count(cpuset_raw) or (os.cpu_count() or 1)
            cpu_max = (
                (cg / "cpu.max").read_text(encoding="utf-8", errors="ignore").strip()
                if (cg / "cpu.max").is_file()
                else "max"
            )
            cpu_weight_raw = (
                (cg / "cpu.weight").read_text(encoding="utf-8", errors="ignore").strip()
                if (cg / "cpu.weight").is_file()
                else ""
            )
            cpu_weight = int(cpu_weight_raw) if cpu_weight_raw.isdigit() else 100
            psi = _facade_hook("_parse_psi_file", _parse_psi_file)(cg / "cpu.pressure")

            # Auditar sobresuscripción de hilos (individual y agregada multi-proceso) en el cgroup
            procs_file = cg / "cgroup.procs"
            pids: List[int] = []
            if procs_file.is_file():
                pids = [
                    int(line.strip())
                    for line in procs_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if line.strip().isdigit()
                ]

            pressure_rows.append(
                {
                    "unit": unit,
                    "cpuset_cpus": cpuset_raw or "all",
                    "effective_cpus": eff_cpus,
                    "cpu_max": cpu_max,
                    "cpu_weight": cpu_weight,
                    "pids_count": len(pids),
                    "psi_some_avg10": psi["some_avg10"],
                    "psi_some_avg60": psi["some_avg60"],
                    "psi_full_avg60": psi["full_avg60"],
                }
            )

            if pids and eff_cpus > 0:
                check_runnable = psi["some_avg60"] >= 15.0 or psi["some_avg10"] >= 25.0
                total_runnable = 0
                active_pids = 0
                unit_flagged_single = False
                top_runnable_pid = 0
                top_runnable_comm = ""
                top_runnable_count = 0

                for pid in pids[:16]:
                    try:
                        cmdline = (
                            Path(f"/proc/{pid}/cmdline")
                            .read_bytes()
                            .replace(b"\x00", b" ")
                            .decode("utf-8", errors="ignore")
                            .strip()
                        )
                        comm = (
                            Path(f"/proc/{pid}/comm")
                            .read_text(encoding="utf-8", errors="ignore")
                            .strip()
                        )
                    except Exception:
                        continue
                    cfg_threads = _extract_cli_int_flag(cmdline, ("--threads", "-t"))
                    cfg_batch = _extract_cli_int_flag(cmdline, ("--threads-batch", "-tb"))
                    max_cfg = max(cfg_threads, cfg_batch)
                    runnable = _facade_hook("_count_runnable_threads", _count_runnable_threads)(pid) if (check_runnable or max_cfg > eff_cpus) else 0
                    total_runnable += runnable
                    if runnable > 0:
                        active_pids += 1
                        if runnable > top_runnable_count:
                            top_runnable_count = runnable
                            top_runnable_pid = pid
                            top_runnable_comm = comm
                    if max_cfg > eff_cpus or runnable > eff_cpus:
                        unit_flagged_single = True
                        peak = max(max_cfg, runnable)
                        ratio = round(peak / float(eff_cpus), 2)
                        rec_gen = max(2, eff_cpus // 2)
                        oversubscribed.append(
                            {
                                "unit": unit,
                                "pid": pid,
                                "comm": comm,
                                "effective_cpus": eff_cpus,
                                "cpuset_cpus": cpuset_raw or "all",
                                "configured_threads": cfg_threads,
                                "configured_threads_batch": cfg_batch,
                                "runnable_threads": runnable,
                                "oversubscription_ratio": ratio,
                                "recommendation": f"Alinear --threads <= {rec_gen} y --threads-batch <= {eff_cpus} con --poll 0 para cpuset {cpuset_raw or 'all'}",
                            }
                        )

                if not unit_flagged_single and total_runnable > eff_cpus:
                    ratio = round(total_runnable / float(eff_cpus), 2)
                    rec_gen = max(2, eff_cpus // 2)
                    agg_comm = (
                        f"{top_runnable_comm or 'multi-proc'} (+{active_pids - 1} procs)"
                        if active_pids > 1
                        else (top_runnable_comm or "cgroup")
                    )
                    oversubscribed.append(
                        {
                            "unit": unit,
                            "pid": top_runnable_pid or pids[0],
                            "comm": agg_comm,
                            "effective_cpus": eff_cpus,
                            "cpuset_cpus": cpuset_raw or "all",
                            "configured_threads": 0,
                            "configured_threads_batch": 0,
                            "runnable_threads": total_runnable,
                            "active_pids": active_pids,
                            "oversubscription_ratio": ratio,
                            "recommendation": (
                                f"Acotar concurrencia agregada del cgroup ({total_runnable} hilos R en {active_pids} procesos) "
                                f"a <= {eff_cpus} hilos para cpuset {cpuset_raw or 'all'} (workers/threads <= {rec_gen})"
                            ),
                        }
                    )
        except Exception:
            continue

    pressure_rows.sort(key=lambda r: (r["psi_some_avg60"], r["psi_some_avg10"]), reverse=True)
    return pressure_rows, oversubscribed

def _parse_proc_kb(status_text: str, key: str) -> float:
    m = re.search(rf"^{re.escape(key)}:\s*(\d+)\s*kB", status_text, flags=re.MULTILINE)
    return round(int(m.group(1)) / 1024.0, 1) if m else 0.0

def _read_proc_mem_status(pid: int) -> Dict[str, float]:
    """Lee RSS/Anon/File/VmLck/VmSwap en MB desde /proc/<pid>/status (<0.1ms)."""
    out = {"rss_mb": 0.0, "rss_anon_mb": 0.0, "rss_file_mb": 0.0, "mlock_mb": 0.0, "swap_mb": 0.0}
    try:
        txt = Path(f"/proc/{int(pid)}/status").read_text(encoding="utf-8", errors="ignore")
        out["rss_mb"] = _parse_proc_kb(txt, "VmRSS")
        out["rss_anon_mb"] = _parse_proc_kb(txt, "RssAnon")
        out["rss_file_mb"] = _parse_proc_kb(txt, "RssFile")
        out["mlock_mb"] = _parse_proc_kb(txt, "VmLck")
        out["swap_mb"] = _parse_proc_kb(txt, "VmSwap")
    except Exception:
        pass
    return out

def _read_proc_uptime_s(pid: int) -> float:
    """Devuelve segundos transcurridos desde el arranque del PID usando /proc/<pid>/stat y /proc/uptime."""
    try:
        up_raw = Path("/proc/uptime").read_text(encoding="utf-8", errors="ignore").split()[0]
        sys_up = float(up_raw)
        stat_txt = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8", errors="ignore")
        rparen = stat_txt.rfind(")")
        if rparen < 0:
            return 0.0
        fields = stat_txt[rparen + 2 :].split()
        # Campo 22 en /proc/[pid]/stat -> índice 19 tras comm (campo 3 es índice 0)
        start_ticks = int(fields[19])
        clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        if clk_tck <= 0:
            return 0.0
        return max(0.0, round(sys_up - (start_ticks / float(clk_tck)), 1))
    except Exception:
        return 0.0

def _read_cgroup_bytes_mb(path: Path) -> Optional[float]:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore").strip()
        if raw.isdigit():
            return round(int(raw) / (1024.0 * 1024.0), 1)
    except Exception:
        pass
    return None

def _inspect_service_memory_bloat(
    unit_specs: Optional[Dict[str, Dict[str, Any]]] = None,
    cgroup_app_slice: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Audita consumo real de RAM, Swap, mlock y límites cgroup v2 (`MemoryHigh`/`MemoryMax`/`MemorySwapMax`)
    de los servicios de inferencia `llama-server` para detectar swap-bloat (`COEV-20261124-5B1F5C`).
    Retorna `(inference_memory_rows, bloated_units)`.
    """
    specs = unit_specs if unit_specs is not None else SWAP_BLOAT_UNITS
    uid = os.getuid()
    app_slice = cgroup_app_slice or Path(
        f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice"
    )
    if not app_slice.is_dir():
        return [], []

    rows: List[Dict[str, Any]] = []
    bloated: List[Dict[str, Any]] = []

    for unit, spec in specs.items():
        cg = app_slice / unit
        if not cg.is_dir():
            continue
        try:
            procs_fp = cg / "cgroup.procs"
            pids: List[int] = []
            if procs_fp.is_file():
                pids = [
                    int(ln.strip())
                    for ln in procs_fp.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if ln.strip().isdigit()
                ]
            if not pids:
                continue

            rss_mb = rss_anon_mb = rss_file_mb = mlock_mb = swap_mb = 0.0
            max_uptime_s = 0.0
            primary_pid = pids[0]
            primary_total = -1.0
            for pid in pids[:16]:
                pm = _facade_hook("_read_proc_mem_status", _read_proc_mem_status)(pid)
                rss_mb += pm["rss_mb"]
                rss_anon_mb += pm["rss_anon_mb"]
                rss_file_mb += pm["rss_file_mb"]
                mlock_mb += pm["mlock_mb"]
                swap_mb += pm["swap_mb"]
                tot_p = pm["rss_mb"] + pm["swap_mb"]
                if tot_p > primary_total:
                    primary_total = tot_p
                    primary_pid = pid
                up_p = _facade_hook("_read_proc_uptime_s", _read_proc_uptime_s)(pid)
                if up_p > max_uptime_s:
                    max_uptime_s = up_p

            cg_curr_mb = _facade_hook("_read_cgroup_bytes_mb", _read_cgroup_bytes_mb)(cg / "memory.current")
            cg_swap_mb = _facade_hook("_read_cgroup_bytes_mb", _read_cgroup_bytes_mb)(cg / "memory.swap.current")
            if cg_swap_mb is not None and cg_swap_mb > swap_mb:
                swap_mb = cg_swap_mb
            mem_high = (cg / "memory.high").read_text(encoding="utf-8", errors="ignore").strip() if (cg / "memory.high").is_file() else "max"
            mem_max = (cg / "memory.max").read_text(encoding="utf-8", errors="ignore").strip() if (cg / "memory.max").is_file() else "max"
            swap_max = (cg / "memory.swap.max").read_text(encoding="utf-8", errors="ignore").strip() if (cg / "memory.swap.max").is_file() else "max"

            total_mb = round(rss_mb + swap_mb, 1)
            rss_mb = round(rss_mb, 1)
            swap_mb = round(swap_mb, 1)

            swap_warn = float(spec.get("swap_warn_mb", 1024.0))
            swap_rec = float(spec.get("swap_recycle_mb", 2048.0))
            tot_rec = float(spec.get("total_recycle_mb", 9216.0))

            reasons: List[str] = []
            if swap_mb >= swap_rec:
                reasons.append(f"swap_bloat_critico ({swap_mb:.0f} MB >= {swap_rec:.0f} MB)")
            elif swap_mb >= swap_warn:
                reasons.append(f"swap_bloat_elevado ({swap_mb:.0f} MB >= {swap_warn:.0f} MB)")
            if total_mb >= tot_rec:
                reasons.append(f"rss_plus_swap_excedido ({total_mb:.0f} MB >= {tot_rec:.0f} MB)")

            is_bloated = bool(reasons)
            recycle_eligible = (swap_mb >= swap_rec) or (total_mb >= tot_rec)
            row = {
                "unit": unit,
                "main_pid": primary_pid,
                "pids_count": len(pids),
                "uptime_s": round(max_uptime_s, 1),
                "rss_mb": rss_mb,
                "rss_anon_mb": round(rss_anon_mb, 1),
                "rss_file_mb": round(rss_file_mb, 1),
                "mlock_mb": round(mlock_mb, 1),
                "swap_mb": swap_mb,
                "total_mb": total_mb,
                "cgroup_current_mb": cg_curr_mb,
                "cgroup_swap_mb": cg_swap_mb,
                "memory_high": mem_high,
                "memory_max": mem_max,
                "memory_swap_max": swap_max,
                "idle_kind": str(spec.get("idle_kind") or ""),
                "bloated": is_bloated,
                "recycle_eligible": recycle_eligible,
                "reasons": reasons,
            }
            rows.append(row)
            if is_bloated:
                bloated.append(row)
        except Exception:
            continue

    rows.sort(key=lambda r: (r["swap_mb"], r["total_mb"]), reverse=True)
    bloated.sort(key=lambda r: (r["swap_mb"], r["total_mb"]), reverse=True)
    return rows, bloated

def _is_service_idle_for_recycle(unit: str, idle_kind: str) -> Tuple[bool, str]:
    """
    Verificación fail-safe de inactividad antes de reciclar un servicio `llama-server`:
      - Veto absoluto ante llamada Telegram prioritaria activa.
      - `temporal_brain`: exige respuesta 200 de `/slots` en `/tmp/temporal_brain.sock` con 0 slots `is_processing`.
      - `ollama_11435`: exige 0 clientes TCP activos en `:11435`.
    """
    if _facade_hook("_is_call_active", _is_call_active)():
        return False, "telegram_call_active"

    if idle_kind == "temporal_brain":
        sock_path = Path("/tmp/temporal_brain.sock")
        if not sock_path.exists():
            return False, "temporal_brain_socket_missing"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)
                s.connect(str(sock_path))
                s.sendall(b"GET /slots HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                chunks: List[bytes] = []
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
            raw = b"".join(chunks).decode("utf-8", errors="ignore")
            hdr, _, body = raw.partition("\r\n\r\n")
            if "200 OK" not in hdr.splitlines()[0]:
                return False, "temporal_brain_slots_non_200"
            slots = json.loads(body)
            if not isinstance(slots, list) or not slots:
                return False, "temporal_brain_slots_empty"
            busy = [sl.get("id") for sl in slots if bool(sl.get("is_processing"))]
            if busy:
                return False, f"temporal_brain_slots_busy:{busy}"
            return True, "all_slots_idle"
        except Exception:
            return False, "temporal_brain_slots_unverified"

    if idle_kind == "ollama_11435":
        clients = _facade_hook("_find_ollama_port_clients", _find_ollama_port_clients)(11435)
        if clients:
            return False, f"ollama_11435_clients_active:{len(clients)}"
        return True, "no_active_clients_on_11435"

    return False, f"unsupported_idle_kind:{idle_kind}"

def _query_ollama_ps(port: int) -> List[Dict[str, Any]]:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ps", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            out = []
            for m in data.get("models") or []:
                out.append(
                    {
                        "name": str(m.get("name") or ""),
                        "size_mb": round(float(m.get("size") or 0) / (1024 * 1024), 1),
                        "size_vram_mb": round(float(m.get("size_vram") or 0) / (1024 * 1024), 1),
                        "expires_at": str(m.get("expires_at") or ""),
                    }
                )
            return out
    except Exception:
        return []

def _find_ollama_port_clients(port: int = 11434) -> List[Dict[str, Any]]:
    """Identifica procesos cliente con sockets TCP activos hacia el puerto Ollama indicado."""
    clients: List[Dict[str, Any]] = []
    seen_pids: set[int] = set()
    try:
        res = subprocess.run(
            ["ss", "-tnp", f"dport = :{int(port)}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode != 0:
            return clients

        for line in res.stdout.splitlines():
            for m in re.finditer(r'\("([^"]+)",pid=(\d+),fd=\d+\)', line):
                comm = m.group(1)
                pid = int(m.group(2))
                if pid in seen_pids or comm == "ollama":
                    continue
                seen_pids.add(pid)
                cmdline = ""
                cgroup = ""
                try:
                    cmdline = (
                        Path(f"/proc/{pid}/cmdline")
                        .read_bytes()
                        .replace(b"\x00", b" ")
                        .decode("utf-8", errors="ignore")
                        .strip()
                    )
                except Exception:
                    pass
                try:
                    cgroup = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8", errors="ignore").strip()
                except Exception:
                    pass
                unit = ""
                for seg in cgroup.split("/"):
                    if seg.endswith(".service"):
                        unit = seg
                clients.append(
                    {
                        "pid": pid,
                        "comm": comm,
                        "unit": unit,
                        "cmdline": cmdline[:180],
                    }
                )
    except Exception:
        pass
    return clients

def _is_call_active() -> bool:
    try:
        from core.telegram_call_priority import is_call_priority_active

        return bool(is_call_priority_active())
    except Exception:
        return False
