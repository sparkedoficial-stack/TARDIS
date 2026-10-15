import struct
import os

def parse_cell_save(filepath):
    with open(filepath, "rb") as f:
        buf = f.read()

    kv_pairs = {}
    pos = 0
    L = len(buf)
    while pos < L - 10:
        if buf[pos] == 6:
            key_id = struct.unpack("<I", buf[pos+1:pos+5])[0]
            idx = pos + 5
            length = 0
            shift = 0
            while idx < L:
                b = buf[idx]
                idx += 1
                length |= (b & 0x7f) << shift
                if not (b & 0x80):
                    break
                shift += 7
            if 0 < length < 100 and idx + length + 5 <= L:
                name = buf[idx:idx+length]
                next_byte = buf[idx+length]
                if next_byte == 9:
                    val_id = struct.unpack("<I", buf[idx+length+1:idx+length+5])[0]
                    try:
                        name_str = name.decode("utf-8")
                        kv_pairs[name_str] = val_id
                    except:
                        pass
        pos += 1

    items_by_id = {}
    pos = 0
    while pos < L - 40:
        if buf[pos] == 1:
            obj_id = struct.unpack("<I", buf[pos+1:pos+5])[0]
            meta_id = struct.unpack("<I", buf[pos+5:pos+9])[0]
            if meta_id == 34:
                idx = pos + 9
                owned, ownedExp, prog, dVar1 = struct.unpack("<dqdd", buf[idx:idx+32])
                idx += 32

                ref_type = buf[idx]
                idx += 1
                if ref_type == 9:
                    idx += 4
                auto_lvl = struct.unpack("<i", buf[idx:idx+4])[0]
                items_by_id[obj_id] = {
                    "owned": owned,
                    "ownedExp": ownedExp,
                    "progress": prog,
                    "dVar1": dVar1,
                    "autoLevel": auto_lvl
                }
        pos += 1

    game_state = {}
    for k, vid in kv_pairs.items():
        if vid in items_by_id:
            game_state[k] = items_by_id[vid]

    return game_state

if __name__ == "__main__":
    save_path = "/home/timemachine/.local/share/Steam/steamapps/compatdata/977400/pfx/drive_c/users/steamuser/AppData/LocalLow/Computer Lunch/Cell to Singularity/savedGames.gd"
    st = parse_cell_save(save_path)
    print(f"Total resolved items: {len(st)}")
    
    # Check important progression metrics
    checks = [
        "stat_currency", "stat_entropy", "stat_science", "stat_dino_rank", "stat_dino_prestige",
        "stat_beyond_rank", "stat_reboot_count", "stat_total_reboots", "tech_singularity",
        "achievement_singularity", "stat_entropy_this_sim", "stat_total_entropy_bits_total_earned_lifetime",
        "a_nanobot_auto_start", "a_nanobot_buy_speed_0", "stat_highest_generator_index_main",
        "stat_highest_generator_index_dino", "stat_highest_generator_index_beyond"
    ]
    print("\n--- ACTIVE/OWNED ITEMS ---")
    active = {k: v for k, v in st.items() if v["owned"] > 0 or v["ownedExp"] > 0 or v["autoLevel"] > 0}
    print(f"Total active/owned items: {len(active)}")
    for k, v in sorted(active.items())[:60]:
        print(f"  {k:40}: owned={v['owned']} exp={v['ownedExp']} auto={v['autoLevel']}")

