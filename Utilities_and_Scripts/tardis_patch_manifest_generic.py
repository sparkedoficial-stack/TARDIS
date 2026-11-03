#!/usr/bin/env python3
"""Recalcula el manifiesto SHA-256 de un árbol (USB) para los directorios indicados.

Uso: tardis_patch_manifest_generic.py <base> <dir1> [dir2 ...]
"""
import hashlib
import os
import sys

base = sys.argv[1]
dirs = sys.argv[2:]
man = os.path.join(base, "MANIFIESTO_SHA256.txt")

entries = {}
with open(man, "r", encoding="utf-8", errors="surrogateescape") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        h, _, p = line.partition("  ")
        if p:
            entries[p] = h


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


updated = added = 0
for d in dirs:
    root = os.path.join(base, d)
    if not os.path.isdir(root):
        continue
    for dp, _dn, fns in os.walk(root):
        for n in fns:
            full = os.path.join(dp, n)
            rel = os.path.relpath(full, base)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            h = sha(full)
            if rel in entries:
                if entries[rel] != h:
                    entries[rel] = h
                    updated += 1
            else:
                entries[rel] = h
                added += 1

with open(man, "w", encoding="utf-8", errors="surrogateescape") as fh:
    for p in sorted(entries):
        fh.write(f"{entries[p]}  {p}\n")

print(f"actualizadas={updated} anadidas={added} total={len(entries)}")
