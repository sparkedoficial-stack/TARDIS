"""
tardis_evolutionary_codex.py
============================
Enciclopedia científica y base de conocimientos evolutivos de TARDIS para
'Cell to Singularity: Evolution Never Ends'.

Contiene la fundamentación científica en biología evolutiva, abiogénesis,
paleontología, antropología, astrofísica y teoría de la singularidad tecnológica
asociada a cada nodo de investigación y avance del juego.
"""

EVOLUTIONARY_LORE = {
    # --- ETAPA 1: ABIOGÉNESIS Y QUÍMICA PREBIÓTICA ---
    "item_amino_acid": {
        "name": "Aminoácidos (Amino Acids)",
        "era": "Hádico / Arcaico (~4.0 Ga)",
        "branch": "Abiogénesis / Sopa Primordial",
        "scientific_discovery": "Los aminoácidos son los monómeros fundamentales de las proteínas. En 1952, el experimento de Miller-Urey demostró que descargas eléctricas a través de una mezcla de metano, amoníaco, hidrógeno y vapor de agua sintetizan aminoácidos esenciales espontáneamente. En fuentes hidrotermales alcalinas submarinas, los gradientes electroquímicos de protones entre el fluido hidrotermal alcalino y el agua de mar ácida rica en CO2 proveyeron la energía libre de Gibbs para la polimerización prebiótica.",
        "game_mechanics": "Primer generador basal de entropía en el juego. Representa la transición de la geoquímica a la bioquímica orgánica."
    },
    "item_dna": {
        "name": "Ácido Desoxirribonucleico (DNA)",
        "era": "Arcaico (~3.8 Ga)",
        "branch": "Genética Molecular",
        "scientific_discovery": "La transición del hipotético 'Mundo de ARN' (donde el ARN catalizaba reacciones como ribozima y almacenaba información genética) hacia el ADN proporcionó una molécula de doble hélice químicamente mucho más estable gracias a la desoxirribosa y la timina. Esto redujo drásticamente las tasas de mutación letal, permitiendo genomas exponencialmente más extensos.",
        "game_mechanics": "Desbloquea multiplicadores masivos de tasa de recolección de entropía y habilita la ramificación hacia el código genético completo."
    },
    "item_prokaryotic_cell": {
        "name": "Célula Procariota (Prokaryotes / LUCA)",
        "era": "Arcaico (~3.8 - 3.5 Ga)",
        "branch": "Citología Basal",
        "scientific_discovery": "El Último Ancestro Común Universal (LUCA) y las células procariotas primitivas. Células anoxigénicas protegidas por peptidoglicano, dotadas de ribosomas 70S y replicación circular sin envoltura cariotécica, dominando la Tierra primitiva mediante gradientes quimiotróficos.",
        "game_mechanics": "Generador clave de la simulación celular. Abre las ramas metabólicas procariotas."
    },
    "znew_item_cyanobacteria": {
        "name": "Cianobacterias y la Gran Oxidación",
        "era": "Paleoproterozoico (~2.4 Ga)",
        "branch": "Bioenergética y Fotosíntesis Oxigénica",
        "scientific_discovery": "Las cianobacterias desarrollaron el fotosistema II capaz de fotolizar la molécula de agua (H2O), liberando dioxígeno (O2) molecular a la atmósfera. Este evento desencadenó la Gran Oxidación (GOE), provocando la precipitación de formaciones de hierro bandeado y la glaciación Huroniana, transformando irreversiblemente la geoquímica terrestre.",
        "game_mechanics": "Incrementa el rendimiento de la atmósfera primordial y abre el camino a la respiración celular eficiente."
    },
    "item_eukayoitc_cell": {
        "name": "Célula Eucariota & Endosimbiosis (Eukaryotes)",
        "era": "Mesoproterozoico (~1.8 - 1.6 Ga)",
        "branch": "Endosimbiosis Seriada (Lynn Margulis)",
        "scientific_discovery": "Fagocitosis simbiótica donde una arquea del superfilo Asgard incorporó una alfa-proteobacteria que derivó en la mitocondria. La compartimentación nuclear y el retículo endoplasmático posibilitaron la transcripción desacoplada de la traducción y el 'splicing' alternativo de intrones.",
        "game_mechanics": "Multiplicador crítico de entropía. Desbloquea la meiosis y el camino hacia la multicelularidad."
    },

    # --- ETAPA 2: MULTICELULARIDAD Y EXPLOSIÓN CÁMBRICA ---
    "item_sponge": {
        "name": "Esponjas (Porifera)",
        "era": "Ediacárico (~600 Ma)",
        "branch": "Metazoos Basales",
        "scientific_discovery": "Animales sésiles sin tejidos verdaderos ni órganos diferenciados, estructurados alrededor de coanocitos flagelados que bombean agua a través de un sistema de poros y cámaras para filtrar bacterias y materia orgánica. Representan el linaje animal divergente más antiguo.",
        "game_mechanics": "Primer peldaño metazoo en el árbol del reino animal marino."
    },
    "item_jelly_fish": {
        "name": "Medusas y Cnidarios (Cnidaria)",
        "era": "Ediacárico / Cámbrico (~580 Ma)",
        "branch": "Animales Diblásticos",
        "scientific_discovery": "Evolución de dos capas germinativas (ectodermo y endodermo), simetría radial y una red nerviosa difusa. Desarrollaron cnidocitos con nematocistos urticantes para la depredación activa, marcando la aparición de la locomoción propulsiva por contracción mioepitelial.",
        "game_mechanics": "Acelera la producción de entropía acuática y desbloquea el desarrollo del sistema nervioso sensorial."
    },
    "item_flat_worm": {
        "name": "Platelmintos & Cefalización (Flatworms)",
        "era": "Cámbrico Temprano (~540 Ma)",
        "branch": "Bilaterales y Cefalización",
        "scientific_discovery": "Aparición de la simetría bilateral y el tercer tejido embrionario (mesodermo triblástico), que posibilitó la diferenciación de órganos internos verdaderos, musculatura compleja y la cefalización: la concentración de órganos sensoriales e interneuronas en un extremo anterior (cabeza y cerebro primordial).",
        "game_mechanics": "Desbloquea la generación de 'Ideas' neuronales a partir de la entropía animal."
    },
    "item_fish": {
        "name": "Peces y Primeros Cordados (Fish)",
        "era": "Cámbrico / Ordovícico (~500 Ma)",
        "branch": "Vertebrados",
        "scientific_discovery": "Evolución de la notocorda cartilaginosa, tubo neural dorsal y hendiduras branquiales faríngeas (ej. Haikouichthys y Pikaia). Posteriormente, en el Silúrico/Devónico, los arcos branquiales anteriores se modificaron evolutivamente para dar origen a las mandíbulas articuladas (Gnatostomados), inaugurando la era de los depredadores ápice marinos.",
        "game_mechanics": "Generador de alto flujo. Desbloquea la transición marina hacia tierra firme."
    },

    # --- ETAPA 3: CONQUISTA DE LA TIERRA FIRME Y TETRÁPODOS ---
    "item_amphibians": {
        "name": "Anfibios (Amphibians)",
        "era": "Carbonífero (~350 Ma)",
        "branch": "Vertebrados Semiterrestres",
        "scientific_discovery": "Primeros vertebrados terrestres consolidados, adaptados a la respiración pulmonar y cutánea pero dependientes del medio acuático para la fecundación y desarrollo de huevos anamniotas y larvas con branquias.",
        "game_mechanics": "Nodo puente hacia los amniotas y diversificación de linajes terrestres."
    },
    "item_modern_reptiles": {
        "name": "Reptiles y el Huevo Amniótico",
        "era": "Carbonífero Tardío (~310 Ma)",
        "branch": "Amniotas Terrestres",
        "scientific_discovery": "Innovación macroevolutiva del huevo amniótico con membranas extraembrionarias (amnios, alantoides y corion) y cáscara semipermeable que protegió al embrión de la desecación, independizando completamente a los vertebrados de los cuerpos de agua para la reproducción.",
        "game_mechanics": "Multiplicador de radiación terrestre. Precursor evolutivo de dinosaurios, aves y sinápsidos."
    },
    "item_mammal": {
        "name": "Mamíferos (Mammalia / Cinodontos)",
        "era": "Triásico Tardío (~220 Ma)",
        "branch": "Sinápsidos Terrestres",
        "scientific_discovery": "Surgidos de los terápsidos cinodontos durante el Triásico. Desarrollaron endotermia (sangre caliente), pelaje aislante, glándulas mamarias para nutrición láctea de crías, oído medio con tres huesecillos (martillo, yunque y estribo derivados de la mandíbula reptiliana) y un neocórtex cerebral altamente expandido.",
        "game_mechanics": "Incrementa sustancialmente la capacidad de procesamiento de Ideas e inteligencia biológica."
    },

    # --- ETAPA 4: PRIMATES Y HOMINIZACIÓN ---
    "item_primate": {
        "name": "Primates (Primates)",
        "era": "Paleógeno (~55 Ma)",
        "branch": "Radiación Euarcontoglire",
        "scientific_discovery": "Adaptación a la vida arborícola caracterizada por pulgares oponibles, uñas planas en lugar de garras, visión estereoscópica frontal en color (tricromática en simios catarrinos) para calcular distancias entre ramas y evaluar madurez de frutos, y una plasticidad neuronal social altamente desarrollada.",
        "game_mechanics": "Nodo de inflexión: la generación de Ideas comienza a competir con el flujo de entropía biológica."
    },
    "man_homo_australopithecus": {
        "name": "Australopithecus afarensis",
        "era": "Plioceno (~3.9 - 2.9 Ma)",
        "branch": "Bipedalismo Habitual",
        "scientific_discovery": "Transición biomecánica hacia el bipedalismo obligado (foramen magnum adelantado, pelvis ensanchada en cuenco y fémures angulados con valgo), permitiendo liberar las manos para el transporte de recursos y el forrajeo en sabanas abiertas (fósil icónico 'Lucy' y huellas de Laetoli).",
        "game_mechanics": "Primer nodo homínido. Dispara la velocidad de generación de ideas."
    },
    "man_homo_habilis": {
        "name": "Homo habilis",
        "era": "Pleistoceno Temprano (~2.4 - 1.4 Ma)",
        "branch": "Tecnología Lítica Olduvayense",
        "scientific_discovery": "Primer hominino con capacidad craneal expandida (>600 cc) y manufactura sistemática de herramientas de piedra tallada (Modo 1 / Olduvai: núcleos y lascas para descarnar y fracturar huesos para extraer tuétano graso de alto valor calórico).",
        "game_mechanics": "Abre el nodo de herramientas compuestas y memoria técnica acumulativa."
    },
    "man_homo_erectus": {
        "name": "Homo erectus",
        "era": "Pleistoceno (~1.9 Ma - 110 ka)",
        "branch": "Control del Fuego y Modo Achelense",
        "scientific_discovery": "Domesticación controlada del fuego para cocción de alimentos, lo que redujo el costo metabólico digestivo de masticación y digestión, permitiendo la reducción del tracto intestinal y canalizando la energía metabólica hacia una encefalización explosiva (~900 - 1100 cc). Primer hominino en dispersarse fuera de África por toda Eurasia.",
        "game_mechanics": "Multiplicador de civilización. Abre las ramas de lenguaje y migración global."
    },
    "achievement_first_human": {
        "name": "Homo sapiens y la Revolución Cognitiva",
        "era": "Pleistoceno Tardío (~300 ka - Presente)",
        "branch": "Consciencia Simbólica y Lenguaje Sintáctico",
        "scientific_discovery": "Capacidad cerebral de ~1350-1400 cc con lóbulo parietal y corteza prefrontal altamente interconectadas. La evolución de un lenguaje con sintaxis recursiva posibilitó la ficción compartida: mitos, religiones, leyes y corporaciones abstractas capaces de coordinar a millones de individuos no emparentados genéticamente.",
        "game_mechanics": "Final de la evolución estrictamente biológica; inicia la evolución exosomática y tecnológica."
    },

    # --- ETAPA 5: ERAS DE LA CIVILIZACIÓN Y TECNOLOGÍA ---
    "tech_fire": {
        "name": "Domesticación del Fuego",
        "era": "Paleolítico (~1.0 Ma - 400 ka)",
        "branch": "Tecnología Energética Primordial",
        "scientific_discovery": "Primer control antrópico de la liberación exotérmica de energía química almacenada. Proveyó protección nocturna contra megafauna, extensión de las horas de actividad diurna y procesamiento de materiales líticos y arcillas.",
        "game_mechanics": "Acelera el ritmo de supervivencia del clan humano."
    },
    "tech_bronze": {
        "name": "Edad de Bronce",
        "era": "~3300 - 1200 a.C.",
        "branch": "Metalurgia y Aleaciones",
        "scientific_discovery": "Desarrollo de la pirometalurgia para fundir y alear cobre (90%) con estaño (10%). La aleación resultante posee una dureza significativamente superior y menor punto de fusión, revolucionando el arado, la arquitectura monumental y las armas ceremoniales y militares.",
        "game_mechanics": "Impulso sustancial a la infraestructura de las ciudades antiguas."
    },
    "tech_iron": {
        "name": "Edad de Hierro",
        "era": "~1200 - 500 a.C.",
        "branch": "Metalurgia Ferrosa",
        "scientific_discovery": "La invención del fuelle de alta temperatura permitió alcanzar los ~1538 °C necesarios para forjar el hierro esponja y carburo de hierro (acero primitivo). El hierro, infinitamente más abundante que el estaño, democratizó las herramientas agrícolas (arados de reja de hierro) multiplicando las densidades demográficas globales.",
        "game_mechanics": "Expande la escala de las civilizaciones clásicas en el árbol."
    },
    "tech_steam_engine": {
        "name": "Revolución Industrial y Máquina de Vapor",
        "era": "Siglo XVIII - XIX (1769)",
        "branch": "Termodinámica y Mecanización",
        "scientific_discovery": "La máquina de condensador separado de James Watt convirtió la energía térmica del carbón en trabajo mecánico rotativo continuo, desacoplando por primera vez la producción humana de los límites biológicos musculares de hombres y animales de tiro.",
        "game_mechanics": "Incremento de orden de magnitud en la producción automatizada de Ideas."
    },
    "tech_atomic_bomb": {
        "name": "Era Atómica y Física Cuántica",
        "era": "Siglo XX (1945)",
        "branch": "Energía Nuclear y Mecánica Cuántica",
        "scientific_discovery": "El descubrimiento de la fisión nuclear inducida del U-235 por Otto Hahn, Fritz Strassmann y Lise Meitner, junto a la ecuación relativista E=mc2. Liberación de la energía del defecto de masa nuclear, inaugurando reactores atómicos y la carrera espacial.",
        "game_mechanics": "Nodo pre-singularidad que dispara los multiplicadores de la Reality Engine."
    },
    "tech_ai": {
        "name": "Inteligencia Artificial y Computación",
        "era": "Siglo XX - XXI",
        "branch": "Cibernética y Redes Neuronales",
        "scientific_discovery": "Sistemas de cálculo mediante arquitecturas de von Neumann, transistores de silicio a escala nanométrica y aprendizaje profundo (Deep Learning / Transformers). La cognición deja de ser un monopolio biológico y se convierte en un proceso algorítmico universal computable.",
        "game_mechanics": "Desbloquea el camino irreversible hacia la Singularidad Tecnológica."
    },

    # --- ETAPA 6: LA SINGULARIDAD TECNOLÓGICA Y POST-HUMANISMO ---
    "tech_singularity": {
        "name": "La Singularidad Tecnológica (The Singularity)",
        "era": "Siglo XXI+ (Horizonte de Sucesos Cognitivo)",
        "branch": "Superinteligencia y Auto-mejora Recursiva",
        "scientific_discovery": "Postulada por John von Neumann, Vernor Vinge y Ray Kurzweil: el momento crítico en que una inteligencia artificial alcanza el nivel humano y es capaz de rediseñarse a sí misma de manera recursiva, generando una explosión de inteligencia exponencial donde los avances científicos de milenios ocurren en segundos. Representa el fin del árbol de evolución terrestre clásico y el reinicio cuántico de la simulación mediante Metabits.",
        "game_mechanics": "Culminación del primer bucle principal. Permite reiniciar la simulación con la Reality Engine, obteniendo Metabits para comprar mejoras universales eternas."
    },
    "i_cyborg": {
        "name": "Cyborgs e Integración Bio-Digital",
        "era": "Post-Singularidad",
        "branch": "Transhumanismo",
        "scientific_discovery": "Fusión simbiótica entre tejidos biológicos y prótesis biónicas de interfaz neuronal directa (BCI), aumentando el ancho de banda sináptico y eliminando la degradación senescente biológica.",
        "game_mechanics": "Multiplicador de producción de ideas en la simulación post-reinicio."
    },
    "t_android": {
        "name": "Androides y Consciencia Sintética",
        "era": "Post-Singularidad",
        "branch": "Vida Artificial",
        "scientific_discovery": "Plataformas robóticas humanoides autónomas que poseen sustratos cognitivos de estado sólido, libres de vulnerabilidades orgánicas, constituyendo una nueva especie consciente.",
        "game_mechanics": "Nodo de alta entropía que desbloquea la colonización marciana y el enjambre de Dyson."
    },
    "t_moon_mission": {
        "name": "Programa Espacial Apolo & Exploración Lunar",
        "era": "1969 - Actualidad",
        "branch": "Astronáutica y Vuelo Interplanetario",
        "scientific_discovery": "Escape del pozo gravitatorio terrestre mediante cohetes de múltiples etapas impulsados por queroseno/hidrógeno líquido (Saturno V). Primera vez que la biosfera terrestre pisa un cuerpo celeste extraterrestre.",
        "game_mechanics": "Nodo de enlace que abre la rama del cosmos y viajes interplanetarios."
    },
    "t_mars_mission": {
        "name": "Colonización y Terraformación de Marte",
        "era": "Era Interplanetaria",
        "branch": "Ciencia Planetaria Aplicada",
        "scientific_discovery": "Establecimiento de hábitats presurizados en el regolito marciano, utilización in situ de recursos (ISRU) mediante reacción de Sabatier para generar CH4 y O2 a partir de CO2 atmosférico e hielo subterráneo, asegurando una especie multiplanetaria.",
        "game_mechanics": "Desbloquea multiplicadores de civilización espacial en el Reality Tree."
    },
    "znew_dyson": {
        "name": "Enjambre de Dyson (Dyson Sphere)",
        "era": "Escala de Kardashev Tipo II",
        "branch": "Megainfraestructuras Astro-Energéticas",
        "scientific_discovery": "Enjambre de satélites solares y colectores fotovoltaicos masivos en órbita heliocéntrica que interceptan la totalidad de la potencia radiativa del Sol (~3.846 × 10^26 vatios), elevando la civilización al Tipo II en la escala de Kardashev.",
        "game_mechanics": "Generador cósmico supremo de la rama de civilización espacial."
    },

    # --- ETAPA 7: EL MÁS ALLÁ (THE BEYOND) Y ASTROFÍSICA ---
    "item_sun": {
        "name": "El Sol (The Sun)",
        "era": "Cosmológica (~4.6 Ga)",
        "branch": "Astrofísica Estelar",
        "scientific_discovery": "Estrella de secuencia principal de tipo espectral G2V (enana amarilla). En su núcleo, a 15.7 millones de Kelvin y 250 mil millones de atmósferas, la cadena protón-protón fusiona 600 millones de toneladas de hidrógeno en helio por segundo, radiando la luz y calor que energizan toda la biosfera.",
        "game_mechanics": "Núcleo gravitacional y primer ancla de recolección en 'The Beyond'."
    },
    "item_moon": {
        "name": "La Luna (The Moon)",
        "era": "Hádico (~4.5 Ga)",
        "branch": "Mecánica Celeste y Geología Lunar",
        "scientific_discovery": "Originada tras el impacto gigante entre la proto-Tierra y el protoplaneta Theia. La Luna estabiliza la oblicuidad axial terrestre (evitando fluctuaciones climáticas caóticas extremas) e induce las mareas oceánicas que promovieron la colonización de zonas intermareales por la vida marina temprana.",
        "game_mechanics": "Segundo cuerpo celeste desbloqueado en el sistema Tierra-Luna de The Beyond."
    },
    "stat_beyond_rank": {
        "name": "El Más Allá: Rango Astronómico Cósmico",
        "era": "Cosmología Profunda",
        "branch": "Astrogénesis & Relatividad General",
        "scientific_discovery": "Exploración de la estructura del sistema solar exterior (Gigantes gaseosos, Cinturón de Kuiper, Nube de Oort) y el medio interestelar (sistema triple de Alpha Centauri, estrellas de neutrones y agujeros negros supermasivos).",
        "game_mechanics": "Nivel máximo de investigación astronómica (Rango 25 alcanzado)."
    },

    # --- ETAPA 8: VALLE MESOZOICO (DINOSAURIOS) ---
    "stat_dino_rank": {
        "name": "Valle Mesozoico: Dominio Dinosauriano",
        "era": "Era Mesozoica (Triásico - Jurásico - Cretácico: 252 - 66 Ma)",
        "branch": "Paleontología de Arcosaurios",
        "scientific_discovery": "Radiación adaptativa de los dinosaurios ornitisquios y saurisquios. Desarrollo de postura bípeda erecta, metabolismo homeotermo derivado, sacos aéreos respiratorios avianos y evolución del plumaje aerodinámico antes del impacto del asteroide Chicxulub.",
        "game_mechanics": "Rango máximo de investigación paleontológica (Rango 50 alcanzado)."
    },
    "stat_dino_prestige": {
        "name": "Prestigio y Extinción Masiva Mesozoica",
        "era": "Límite K-Pg (Cretácico-Paleógeno)",
        "branch": "Eventos de Extinción y Selección Cladística",
        "scientific_discovery": "El impacto de Chicxulub liberó el equivalente a 100 millones de megatones de TNT, desencadenando lluvia ácida de sulfatos y un invierno nuclear de varios años. Este colapso fotosintético erradicó a los dinosaurios no avianos y amonites, liberando todos los nichos ecológicos globales para la radiación explosiva de los mamíferos placentarios.",
        "game_mechanics": "Prestigio 10 alcanzado. Provee los mayores multiplicadores globales de simulación."
    },

    # --- NANOBOTS AUTÓNOMOS ---
    "a_nano": {
        "name": "Enjambre de Nanobots Autónomos (Reality Engine)",
        "era": "Post-Singularidad / Nanotecnología Molecular",
        "branch": "Mecánica Molecular de Drexler",
        "scientific_discovery": "Ensambladores moleculares autorreplicantes capaces de manipular la materia átomo a átomo. Operan en bucle cerrado de retroalimentación temporal, optimizando la transducción de entropía en trabajo computable.",
        "game_mechanics": "Permite recolectar entropía e ideas de forma continua sin fatiga biológica ni límites de interfaz humana."
    },
    "a_nano_buy": {
        "name": "Nanobots: Ruta de Compra Automatizada (Buyer Route)",
        "era": "Automatización Completa",
        "branch": "Algoritmos Greedy de Asignación Óptima",
        "scientific_discovery": "Subrutina de compra autónoma de mejoras evolutivas que escanea la frontera filogenética y adquiere instantáneamente cualquier nodo disponible tan pronto como el coste de entropía/ideas es cubierto.",
        "game_mechanics": "Elimina la necesidad de clics manuales en el árbol genealógico."
    },
    "a_nanobot_auto_start": {
        "name": "Nanobots: Auto-Arranque Continuo",
        "era": "Operación Ininterrumpida",
        "branch": "Daemon Autoregenerativo",
        "scientific_discovery": "Control de disparo persistente que activa automáticamente el ciclo de aceleración de los nanobots en cuanto finaliza su período de enfriamiento cuántico.",
        "game_mechanics": "Garantiza tiempo de actividad de nanobots cercano al 100%."
    }
}

def get_lore_for_node(node_key: str) -> dict:
    """Devuelve la ficha científica del nodo si existe, o genera un resumen analítico."""
    if node_key in EVOLUTIONARY_LORE:
        return EVOLUTIONARY_LORE[node_key]
    
    # Análisis heurístico por prefijo y nombre
    name_clean = node_key.replace("item_", "").replace("tech_", "").replace("man_", "").replace("a_", "").replace("stat_", "").replace("_", " ").title()
    return {
        "name": name_clean,
        "era": "Era Transversal de la Simulación",
        "branch": "Evolución Adaptativa",
        "scientific_discovery": f"Nodo evolutivo clave '{name_clean}'. Representa una innovación adaptativa en la biosfera o la matriz tecnológica que incrementa la sintropía y la complejidad informacional del sistema.",
        "game_mechanics": "Incrementa multiplicadores de producción o desbloquea dependencias filogenéticas adyacentes."
    }
