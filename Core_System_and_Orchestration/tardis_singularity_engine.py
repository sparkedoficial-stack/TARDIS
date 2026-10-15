"""
tardis_singularity_engine.py
============================
Motor cuántico de evolución, progreso y análisis de 'Cell to Singularity'
diseñado para TARDIS.

Permite:
1. Inspeccionar el estado de la simulación en tiempo real.
2. Calcular la brecha evolutiva hacia la Singularidad.
3. Desbloquear y optimizar progresivamente los nodos filogenéticos,
   la simulación de dinosaurios (Valle Mesozoico), El Más Allá (The Beyond),
   y los nanobots autónomos.
4. Generar el reporte de descubrimientos científicos y lore para el Arquitecto.
"""

import os
import shutil
import struct
import time
import json
from datetime import datetime
from tardis_evolutionary_codex import get_lore_for_node, EVOLUTIONARY_LORE

SAVE_DIR = "/home/timemachine/.local/share/Steam/steamapps/compatdata/977400/pfx/drive_c/users/steamuser/AppData/LocalLow/Computer Lunch/Cell to Singularity"
SAVE_PATH = os.path.join(SAVE_DIR, "savedGames.gd")
BACKUP_DIR = "/home/timemachine/.ftl/cell_backups"
STATE_JSON = "/home/timemachine/.ftl/tardis_singularity_state.json"
REPORT_MD = "/home/timemachine/Escritorio/TARDIS_SINGULARITY_DISCOVERIES.md"

# Nodos evolutivos ordenados cronológicamente por ramas principales
CHRONOLOGICAL_EVOLUTION_TREE = [
    # --- RAMA PRINCIPAL: ABIOGÉNESIS Y VIDA CELULAR ---
    ("item_amino_acid", "Aminoácidos", 100, 0),
    ("item_dna", "ADN Primordial", 80, 0),
    ("item_prokaryotic_cell", "Célula Procariota", 60, 0),
    ("znew_item_cyanobacteria", "Cianobacterias & Fotosíntesis Oxigénica", 50, 0),
    ("item_eukayoitc_cell", "Célula Eucariota & Endosimbiosis", 40, 0),
    
    # --- EXPLOSIÓN CÁMBRICA Y MARINO ---
    ("item_sponge", "Esponjas (Porifera)", 30, 0),
    ("item_jelly_fish", "Medusas (Cnidaria)", 25, 0),
    ("item_flat_worm", "Platelmintos & Cefalización", 20, 0),
    ("item_fish", "Peces & Mandíbulas (Gnatostomados)", 18, 0),
    
    # --- COLONIZACIÓN TERRESTRE ---
    ("item_amphibians", "Anfibios", 15, 0),
    ("item_modern_reptiles", "Reptiles & Huevo Amniótico", 15, 0),
    ("item_mammal", "Mamíferos Basales & Endotermia", 12, 0),
    
    # --- PRIMATES Y HOMINIZACIÓN ---
    ("item_primate", "Primates", 10, 0),
    ("man_homo_australopithecus", "Australopithecus (Bipedalismo)", 6, 0),
    ("man_homo_habilis", "Homo habilis (Herramientas líticas)", 5, 0),
    ("man_homo_erectus", "Homo erectus (Dominio del fuego)", 4, 0),
    ("achievement_first_human", "Homo sapiens (Revolución Cognitiva)", 1, 0),
    
    # --- CIVILIZACIÓN Y TECNOLOGÍA ---
    ("tech_fire", "Control del Fuego", 1, 0),
    ("tech_bronze", "Edad de Bronce & Metalurgia", 1, 0),
    ("tech_iron", "Edad de Hierro", 1, 0),
    ("tech_steam_engine", "Máquina de Vapor & Revolución Industrial", 1, 0),
    ("tech_atomic_bomb", "Era Atómica & Energía Nuclear", 1, 0),
    ("tech_ai", "Inteligencia Artificial", 1, 0),
    
    # --- LA SINGULARIDAD Y POST-HUMANISMO ---
    ("tech_singularity", "La Singularidad Tecnológica", 1, 0),
    ("i_cyborg", "Integración Cyborg", 20, 0),
    ("t_android", "Androides Sintéticos", 20, 0),
    ("t_moon_mission", "Misión Lunar Apolo", 1, 0),
    ("t_mars_mission", "Colonización Marciana", 1, 0),
    ("znew_dyson", "Enjambre de Dyson", 5, 0),
    
    # --- EL MÁS ALLÁ (THE BEYOND) Y VALLE MESOZOICO ---
    ("item_sun", "El Sol & Astrofísica Estelar", 20, 0),
    ("item_moon", "La Luna & Dinámica de Mareas", 15, 0),
    ("stat_beyond_rank", "Rango Cósmico en The Beyond", 25, 0),
    ("stat_dino_rank", "Rango de Dinosaurios en Valle Mesozoico", 50, 0),
    ("stat_dino_prestige", "Prestigio del Valle Mesozoico", 10, 0)
]


# Nanobots upgrades
NANOBOT_UPGRADES = [
    ("a_nano", "Nanobots Base", 1, 0, 1),
    ("a_nanobot_0", "Unidad Nanobot 0", 1, 0, 1),
    ("a_nano_buy", "Nanobot Modo Compra (Buyer Route)", 1, 0, 1),
    ("a_nanobot_auto_start", "Nanobot Auto-Start", 1, 0, 1),
    ("a_nanobot_tap_power_0", "Nanobot Potencia de Clic 0", 10, 0, 1),
    ("a_nanobot_tap_speed_0", "Nanobot Velocidad de Clic 0", 10, 0, 1),
    ("a_nanobot_buy_speed_0", "Nanobot Velocidad de Compra 0", 10, 0, 1),
    ("a_nanobot_move_speed_0", "Nanobot Velocidad de Desplazamiento", 10, 0, 1),
    ("a_nanobot_side_sim_enabled", "Nanobot Habilitado en Valle Mesozoico & Beyond", 1, 0, 1)
]


class TardisSingularityEngine:
    def __init__(self, save_path=SAVE_PATH):
        self.save_path = save_path
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self.buf = None
        self.item_offsets = {}
        self.items_state = {}
        self.load_save()

    def load_save(self):
        if not os.path.exists(self.save_path):
            raise FileNotFoundError(f"Archivo de guardado no encontrado en: {self.save_path}")
        
        with open(self.save_path, "rb") as f:
            self.buf = bytearray(f.read())
        
        # Mapear strings y val_ids
        kv_pairs = {}
        pos = 0
        L = len(self.buf)
        while pos < L - 10:
            if self.buf[pos] == 6: # BinaryObjectString
                key_id = struct.unpack("<I", self.buf[pos+1:pos+5])[0]
                idx = pos + 5
                length = 0
                shift = 0
                while idx < L:
                    b = self.buf[idx]
                    idx += 1
                    length |= (b & 0x7f) << shift
                    if not (b & 0x80):
                        break
                    shift += 7
                if 0 < length < 100 and idx + length + 5 <= L:
                    name_bytes = self.buf[idx:idx+length]
                    if self.buf[idx+length] == 9: # MemberReference
                        val_id = struct.unpack("<I", self.buf[idx+length+1:idx+length+5])[0]
                        try:
                            kv_pairs[name_bytes.decode("utf-8")] = val_id
                        except:
                            pass
            pos += 1

        # Mapear ClassWithId para ItemSaveData (meta_id == 34)
        pos = 0
        items_by_id = {}
        while pos < L - 40:
            if self.buf[pos] == 1:
                obj_id, meta_id = struct.unpack("<II", self.buf[pos+1:pos+9])
                if meta_id == 34:
                    idx = pos + 9
                    owned, ownedExp, prog, dVar1 = struct.unpack("<dqdd", self.buf[idx:idx+32])
                    ref_type = self.buf[idx+32]
                    ref_offset = idx + 33 + (4 if ref_type == 9 else 0)
                    auto_lvl = struct.unpack("<i", self.buf[ref_offset:ref_offset+4])[0]
                    items_by_id[obj_id] = {
                        "offset": pos + 9,
                        "owned": owned,
                        "ownedExp": ownedExp,
                        "progress": prog,
                        "dVar1": dVar1,
                        "autoLevel": auto_lvl
                    }
            pos += 1

        self.item_offsets = {}
        self.items_state = {}
        for name, vid in kv_pairs.items():
            if vid in items_by_id:
                data = items_by_id[vid]
                self.item_offsets[name] = data["offset"]
                self.items_state[name] = data

    def backup_save(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(BACKUP_DIR, f"savedGames_{ts}.gd.bak")
        shutil.copy2(self.save_path, dest)
        return dest

    def set_item_value(self, item_name, owned=None, ownedExp=None, autoLevel=None):
        if item_name not in self.item_offsets:
            return False
        offset = self.item_offsets[item_name]
        if owned is not None:
            self.buf[offset:offset+8] = struct.pack("<d", float(owned))
            self.items_state[item_name]["owned"] = float(owned)
        if ownedExp is not None:
            self.buf[offset+8:offset+16] = struct.pack("<q", int(ownedExp))
            self.items_state[item_name]["ownedExp"] = int(ownedExp)
        if autoLevel is not None:
            ref_type = self.buf[offset+32]
            ref_offset = offset + 33 + (4 if ref_type == 9 else 0)
            self.buf[ref_offset:ref_offset+4] = struct.pack("<i", int(autoLevel))
            self.items_state[item_name]["autoLevel"] = int(autoLevel)
        return True

    def commit_changes(self):
        self.backup_save()
        with open(self.save_path, "wb") as f:
            f.write(self.buf)
        # Sincronizar copias espejo secundarias de Cell to Singularity
        mirror = os.path.join(SAVE_DIR, "savedGames2.gd")
        if os.path.exists(mirror):
            with open(mirror, "wb") as f:
                f.write(self.buf)

    def advance_to_singularity(self):
        """
        Ejecuta el avance cuántico hacia la Singularidad:
        1. Aumenta la entropía y las ideas a flujos astronómicos para sostener el árbol.
        2. Desbloquea y optimiza todos los nodos evolutivos en CHRONOLOGICAL_EVOLUTION_TREE.
        3. Activa y maximiza los nanobots autónomos.
        4. Registra los descubrimientos científicos de cada hito.
        """
        discoveries = []
        
        # 1. Asegurar reservas energéticas de Entropía e Ideas
        self.set_item_value("stat_entropy", owned=9.99, ownedExp=24) # ~10^25 entropía
        self.set_item_value("stat_entropy_this_sim", owned=9.99, ownedExp=24)
        self.set_item_value("stat_science", owned=9.99, ownedExp=24) # Ideas
        self.set_item_value("stat_idea_this_sim", owned=9.99, ownedExp=24)
        self.set_item_value("stat_currency", owned=5000.0, ownedExp=0) # Darwinium
        
        # 2. Desbloquear Nanobots
        for n_key, n_name, qty, exp, auto in NANOBOT_UPGRADES:
            if n_key in self.item_offsets:
                cur = self.items_state.get(n_key, {}).get("owned", 0)
                if cur < qty:
                    self.set_item_value(n_key, owned=qty, ownedExp=exp, autoLevel=auto)
                    discoveries.append({
                        "node_key": n_key,
                        "type": "NANOBOT_SYSTEM",
                        "title": f"Nanotecnología Autónoma: {n_name}",
                        "desc": "Nanomáquinas autoreplicantes programadas en modo comprador y recolector continuo.",
                        "lore": get_lore_for_node(n_key)
                    })

        # 3. Evolucionar los Nodos Cronológicos
        for node_key, node_name, target_qty, target_exp in CHRONOLOGICAL_EVOLUTION_TREE:
            if node_key in self.item_offsets:
                cur = self.items_state.get(node_key, {}).get("owned", 0)
                if cur < target_qty:
                    self.set_item_value(node_key, owned=target_qty, ownedExp=target_exp, autoLevel=1)
                    lore = get_lore_for_node(node_key)
                    discoveries.append({
                        "node_key": node_key,
                        "type": "EVOLUTIONARY_MILESTONE",
                        "title": node_name,
                        "desc": lore["scientific_discovery"],
                        "lore": lore
                    })

        # 4. Desbloquear logro de Singularidad y ascensión
        self.set_item_value("achievement_singularity", owned=1.0, ownedExp=0)
        self.set_item_value("stat_ascend", owned=4.0, ownedExp=0)
        self.set_item_value("primary_lock_level", owned=12.0, ownedExp=0)

        # 5. Guardar cambios en disco
        self.commit_changes()

        # 6. Actualizar reporte y estado en disco
        self.update_discovery_report(discoveries)
        return discoveries

    def update_discovery_report(self, discoveries):
        # Guardar estado JSON
        state_data = {
            "last_updated": datetime.now().isoformat(),
            "total_items_resolved": len(self.items_state),
            "singularity_unlocked": bool(self.items_state.get("tech_singularity", {}).get("owned", 0) > 0),
            "nanobots_active": bool(self.items_state.get("a_nano", {}).get("owned", 0) > 0),
            "entropy_exponent": self.items_state.get("stat_entropy", {}).get("ownedExp", 0),
            "recent_discoveries_count": len(discoveries)
        }
        with open(STATE_JSON, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2, ensure_ascii=False)

        # Generar o actualizar Master Report en Markdown para el Arquitecto
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report = f"""# 🛸 TARDIS :: BITÁCORA DE INVESTIGACIÓN Y DESCUBRIMIENTOS EVOLUTIVOS
**Juego:** Cell to Singularity: Evolution Never Ends  
**Autoridad:** El Arquitecto (₪)  
**Operador Autónomo:** TARDIS (Núcleo de Inferencia Cuántica & Daemon FTL)  
**Última Actualización:** {now_str}  
**Estado de la Simulación:** SINGULARIDAD ALCANZADA & NANOBOTS ACTIVADOS

---

## 🔬 SÍNTESIS DE TELEMETRÍA Y CONTROL AUTÓNOMO
* **Estado de la Singularidad:** Desbloqueada y estabilizada.
* **Control de Nanobots:** Modo Compra (`Buyer Route`) y Modo Clic activados con auto-arranque permanente.
* **Flujo Energético:** Entropía e Ideas estabilizadas en órdenes supra-exponenciales (~$10^{{25}}$).
* **Nivel de Bloqueo Primario:** Nivel 12 (Cosmológico y Consciencia Sintética).

---

## 🧬 ANÁLISIS CIENTÍFICO Y LORE DE LOS NODOS EVOLUTIVOS ALCANZADOS

"""
        for d in discoveries:
            lore = d["lore"]
            report += f"""### 🌟 {lore['name']}
* **Era / Escala Temporal:** `{lore.get('era', 'No especificada')}`
* **Rama Filogenética / Tecnológica:** `{lore.get('branch', 'Tronco Común')}`
* **Mecánica de Juego:** {lore.get('game_mechanics', '')}

> **Fundamentación Científica e Investigación:**  
> {lore.get('scientific_discovery', d.get('desc', ''))}

---
"""

        with open(REPORT_MD, "w", encoding="utf-8") as f:
            f.write(report)

if __name__ == "__main__":
    engine = TardisSingularityEngine()
    print(f"TardisSingularityEngine inicializado. Total items: {len(engine.items_state)}")
    disc = engine.advance_to_singularity()
    print(f"Evolución completada. Total descubrimientos registrados: {len(disc)}")
    print(f"Reporte generado en: {REPORT_MD}")
