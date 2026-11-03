#!/usr/bin/env python3
"""Parchea el manifiesto SHA-256 del respaldo recalculando solo las entradas
cuyo archivo cambió después de una marca temporal (los archivos vivos del
sistema TARDIS que se reescriben constantemente)."""
import hashlib
import os
import sys
import time

base = "/run/media/timemachine/Hyper jump/GODWORKS_TARDIS_BACKUP_2026-11-03"
man = os.path.join(base, "MANIFIESTO_SHA256.txt")
cutoff = float(sys.argv[1]) if len(sys.argv) > 1 else time.time() - 3600
dirs = ["01_GODWORKS_SYSTEM", "02_HOME_COMPLETO", "03_SISTEMA",
        "04_RECONSTRUCCION", "05_LOGS"]

entries = {}
order = []
with open(man, "r", encoding="utf-8", errors="surrogateescape") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        h, _, p = line.partition("  ")
        if not p:
            continue
        entries[p] = h
        order.append(p)

updated = added = removed = 0


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


seen = set()
for d in dirs:
    root = os.path.join(base, d)
    if not os.path.isdir(root):
        continue
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base)
            if rel == "MANIFIESTO_SHA256.txt":
                continue
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            seen.add(rel)
            if st.st_mtime < cutoff:
                continue
            try:
                new = sha(full)
            except OSError:
                continue
            if rel in entries:
                if entries[rel] != new:
                    entries[rel] = new
                    updated += 1
            else:
                entries[rel] = new
                order.append(rel)
                added += 1

missing = [p for p in order if p not in seen and os.path.exists(os.path.join(base, p)) is False]
for p in missing:
    entries.pop(p, None)
    removed += 1

with open(man, "w", encoding="utf-8", errors="surrogateescape") as fh:
    for p in sorted(entries):
        fh.write(f"{entries[p]}  {p}\n")

print(f"actualizadas={updated} anadidas={added} eliminadas={removed} total={len(entries)}")
