"""
Mach-O Engine for Xcode on Linux
Deep binary parser, load command analyzer, and architecture inspector.
Part of Xcode for Linux (xcode-linux).
"""

import struct
import os
import sys

# Mach-O constants
MH_MAGIC = 0xfeedface
MH_CIGAM = 0xcefaedfe
MH_MAGIC_64 = 0xfeedfacf
MH_CIGAM_64 = 0xcffaedfe
FAT_MAGIC = 0xcafebabe
FAT_CIGAM = 0xbebafeca

CPU_TYPES = {
    7: "x86",
    0x01000007: "x86_64",
    12: "ARM",
    0x0100000c: "ARM64",
    0x0200000c: "ARM64_32",
}

LOAD_COMMANDS = {
    0x1: "LC_SEGMENT",
    0x2: "LC_SYMTAB",
    0xc: "LC_LOAD_DYLIB",
    0xe: "LC_LOAD_DYLINKER",
    0x19: "LC_SEGMENT_64",
    0x1b: "LC_UUID",
    0x1d: "LC_CODE_SIGNATURE",
    0x21: "LC_ENCRYPTION_INFO",
    0x28: "LC_MAIN",
    0x2c: "LC_ENCRYPTION_INFO_64",
    0x32: "LC_BUILD_VERSION",
}

PLATFORMS = {
    1: "macOS",
    2: "iOS",
    3: "tvOS",
    4: "watchOS",
    5: "bridgeOS",
    6: "MacCatalyst",
    7: "iOSSimulator",
    11: "visionOS",
}

def parse_macho(path):
    """Parses a Mach-O or Universal/Fat binary and returns structured metadata."""
    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}

    info = {
        "file": os.path.abspath(path),
        "size": os.path.getsize(path),
        "slices": [],
        "is_fat": False,
        "uuid": None,
        "min_os": None,
        "platform": None,
        "dylibs": [],
        "is_encrypted": False,
        "has_codesig": False,
    }

    with open(path, "rb") as f:
        magic_bytes = f.read(4)
        if len(magic_bytes) < 4:
            return {"error": "Binary too small"}

        magic = struct.unpack(">I", magic_bytes)[0]
        
        slices_to_parse = []
        if magic in (FAT_MAGIC, FAT_CIGAM):
            info["is_fat"] = True
            f.seek(4)
            nfat_arch = struct.unpack(">I", f.read(4))[0]
            for _ in range(nfat_arch):
                cputype, cpusubtype, offset, size, align = struct.unpack(">IIIII", f.read(20))
                slices_to_parse.append((cputype, offset, size))
        elif magic in (MH_MAGIC_64, MH_CIGAM_64, MH_MAGIC, MH_CIGAM):
            f.seek(0)
            cputype = struct.unpack("<I" if magic in (MH_MAGIC, MH_MAGIC_64) else ">I", f.read(8)[4:8])[0]
            slices_to_parse.append((cputype, 0, info["size"]))
        else:
            return {"error": f"Not a valid Mach-O binary (magic: {hex(magic)})"}

        for cputype, offset, size in slices_to_parse:
            arch_name = CPU_TYPES.get(cputype, f"Unknown ({hex(cputype)})")
            slice_info = {
                "arch": arch_name,
                "offset": offset,
                "size": size,
                "commands": [],
            }
            
            f.seek(offset)
            m_bytes = f.read(4)
            if not m_bytes:
                continue
            m_magic = struct.unpack(">I", m_bytes)[0]
            is_64 = m_magic in (MH_MAGIC_64, MH_CIGAM_64)
            endian = "<" if m_magic in (MH_MAGIC, MH_MAGIC_64) else ">"
            
            header_fmt = endian + "IIIIIII" if is_64 else endian + "IIIIII"
            header_size = struct.calcsize(header_fmt)
            f.seek(offset)
            header_data = f.read(header_size)
            if len(header_data) < header_size:
                continue
            header = struct.unpack(header_fmt, header_data)
            ncmds = header[4]
            sizeofcmds = header[5]
            
            # Read load commands
            f.seek(offset + header_size)
            for _ in range(ncmds):
                cmd_header = f.read(8)
                if len(cmd_header) < 8:
                    break
                cmd, cmdsize = struct.unpack(endian + "II", cmd_header)
                cmd_data = f.read(cmdsize - 8)
                cmd_name = LOAD_COMMANDS.get(cmd, f"CMD_{hex(cmd)}")
                slice_info["commands"].append(cmd_name)
                
                # LC_UUID
                if cmd == 0x1b and len(cmd_data) >= 16:
                    info["uuid"] = cmd_data[:16].hex()
                # LC_ENCRYPTION_INFO / LC_ENCRYPTION_INFO_64
                elif cmd in (0x21, 0x2c) and len(cmd_data) >= 8:
                    cryptid = struct.unpack(endian + "I", cmd_data[4:8])[0]
                    if cryptid != 0:
                        info["is_encrypted"] = True
                # LC_CODE_SIGNATURE
                elif cmd == 0x1d:
                    info["has_codesig"] = True
                # LC_LOAD_DYLIB
                elif cmd == 0xc and len(cmd_data) >= 16:
                    str_offset = struct.unpack(endian + "I", cmd_data[:4])[0] - 8
                    dylib_str = cmd_data[str_offset:].split(b"\x00")[0].decode("utf-8", "ignore")
                    if dylib_str and dylib_str not in info["dylibs"]:
                        info["dylibs"].append(dylib_str)
                # LC_BUILD_VERSION
                elif cmd == 0x32 and len(cmd_data) >= 16:
                    platform, minos, sdk = struct.unpack(endian + "III", cmd_data[:12])
                    info["platform"] = PLATFORMS.get(platform, f"Platform_{platform}")
                    major = (minos >> 16) & 0xffff
                    minor = (minos >> 8) & 0xff
                    patch = minos & 0xff
                    info["min_os"] = f"{major}.{minor}.{patch}"

            info["slices"].append(slice_info)

    return info

def print_macho_summary(info):
    """Prints a beautiful summary of Mach-O binary info."""
    if "error" in info:
        print(f"[!] Error: {info['error']}")
        return
    print("==========================================================")
    print("             XCODE MACH-O BINARY INSPECTOR                ")
    print("==========================================================")
    print(f"File:         {info['file']}")
    print(f"Size:         {info['size']:,} bytes ({info['size']/1024/1024:.2f} MB)")
    print(f"Format:       {'Universal / FAT' if info['is_fat'] else 'Single Architecture'}")
    archs = ", ".join(s["arch"] for s in info["slices"])
    print(f"Architectures: {archs}")
    print(f"Platform:     {info['platform'] or 'iOS/Darwin'}")
    print(f"Target SDK:   {info['min_os'] or 'N/A'}")
    print(f"UUID:         {info['uuid'] or 'N/A'}")
    print(f"Code Signed:  {'Yes' if info['has_codesig'] else 'No'}")
    print(f"Encrypted:    {'Yes (FairPlay DRM active)' if info['is_encrypted'] else 'No (Decrypted / Ready)'}")
    print(f"Dependencies: {len(info['dylibs'])} dynamic libraries linked")
    for d in info['dylibs'][:8]:
        print(f"  -> {d}")
    if len(info['dylibs']) > 8:
        print(f"  ... and {len(info['dylibs']) - 8} more.")
    print("==========================================================")
