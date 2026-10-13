"""
tests/test_transversal_rag_vault.py - Validación Integral de la Bóveda Transversal,
Grafo de Conocimiento Soberano y Pipeline RAG de Vanguardia (CRAG + RAPTOR + GraphRAG).
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from core.knowledge_graph import KnowledgeGraph
from core.rag_vault import RAGVault


class TestTransversalKnowledgeGraph(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_kg.db"
        self.kg = KnowledgeGraph(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_add_nodes_and_edges(self):
        nid1 = self.kg.add_node("TemporalEngine", entity_type="subsystem", description="Motor de sincronización temporal")
        nid2 = self.kg.add_node("TunnelBridge", entity_type="network", description="Puente cifrado de enlace")
        self.assertGreater(nid1, 0)
        self.assertGreater(nid2, 0)

        eid = self.kg.add_edge("TemporalEngine", "TunnelBridge", relation="optimiza", weight=1.5, evidence="Reduce latencia")
        self.assertGreater(eid, 0)

        node = self.kg.get_node("TemporalEngine")
        self.assertEqual(node["entity_type"], "subsystem")

        neighbors = self.kg.get_neighbors("TemporalEngine", direction="out")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0]["target_name"], "TunnelBridge")
        self.assertEqual(neighbors[0]["relation"], "optimiza")

    def test_transversal_shortest_path(self):
        # Cadena transversal: A -> B -> C -> D
        self.kg.add_edge("QuantumEnergy", "TemporalEngine", relation="alimenta")
        self.kg.add_edge("TemporalEngine", "TunnelBridge", relation="sincroniza")
        self.kg.add_edge("TunnelBridge", "TardisPocket", relation="conecta_con")

        path = self.kg.find_shortest_path("QuantumEnergy", "TardisPocket", max_depth=4)
        self.assertIsNotNone(path)
        self.assertEqual(len(path), 4)
        self.assertEqual(path[0]["node"]["name"], "QuantumEnergy")
        self.assertEqual(path[-1]["node"]["name"], "TardisPocket")

    def test_conceptual_bridges(self):
        self.kg.add_edge("PhysicsDomain", "MathematicalModel", relation="formaliza")
        self.kg.add_edge("MathematicalModel", "CompilerEngine", relation="ejecuta")

        bridges = self.kg.find_conceptual_bridges(["PhysicsDomain"], ["CompilerEngine"])
        self.assertEqual(len(bridges), 1)
        self.assertIn("MathematicalModel", bridges[0]["intermediate"])

    def test_community_detection(self):
        # Grupo 1
        self.kg.add_edge("A1", "A2", relation="conecta")
        self.kg.add_edge("A2", "A3", relation="conecta")
        self.kg.add_edge("A3", "A1", relation="conecta")

        # Grupo 2
        self.kg.add_edge("B1", "B2", relation="conecta")
        self.kg.add_edge("B2", "B3", relation="conecta")
        self.kg.add_edge("B3", "B1", relation="conecta")

        communities = self.kg.detect_communities(max_iterations=10)
        self.assertGreaterEqual(len(communities), 2)


class TestTransversalRAGVault(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.vault_db = Path(self.test_dir) / "test_rag_vault.db"
        self.kg_db = Path(self.test_dir) / "test_kg.db"

        self.vault = RAGVault.get_instance()
        self.vault.db_path = self.vault_db
        self.vault.kg = KnowledgeGraph(db_path=self.kg_db)
        self.vault._mat = None
        self.vault._ids = []
        self.vault._mat_dirty = True
        self.vault._init_db()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_semantic_extraction(self):
        sample_text = (
            "TemporalBrain se define como el motor central de control neural soberano. "
            "El componente TemporalBrain conecta con TunnelBridge para asegurar la operacion 24/7. "
            "Asimismo, TunnelBridge optimiza TardisPocket reduciendo la latencia de paquetes."
        )
        rels, defs = self.vault.extract_relations_and_terms(sample_text)
        self.assertTrue(any("temporalbrain" in t[0].lower() for t in defs))
        self.assertTrue(any(r["relation"] in ("conecta_con", "optimiza") for r in rels))

    @patch.object(RAGVault, "embed")
    def test_ingest_and_hybrid_search(self, mock_embed):
        # Simular embedding de dimension 384
        dummy_vec = np.ones((1, 384), dtype=np.float32)
        dummy_vec /= np.linalg.norm(dummy_vec)
        mock_embed.return_value = dummy_vec

        text = (
            "TemporalBrain se define como el nucleo soberano de computo. "
            "TemporalBrain conecta con TunnelBridge directamente."
        )
        res = self.vault.ingest(text, source="test", title="Arquitectura Temporal")
        self.assertTrue(res["ok"])
        self.assertGreater(res["stored"], 0)

        # Buscar por BM25 / Denso
        hits = self.vault.search("TemporalBrain", k=3)
        self.assertGreater(len(hits), 0)
        self.assertIn("TemporalBrain", hits[0]["text"])

    def test_crag_confidence_evaluation(self):
        # Caso sin resultados
        crag_empty = self.vault.evaluate_confidence([])
        self.assertEqual(crag_empty["status"], "MISSING")
        self.assertEqual(crag_empty["action"], "web_fallback")

        # Caso con resultado de alta confianza
        high_hits = [{"fused_score": 0.05, "dense_score": 0.85}]
        crag_high = self.vault.evaluate_confidence(high_hits)
        self.assertEqual(crag_high["status"], "CORRECT")
        self.assertEqual(crag_high["action"], "generate")

        # Caso con resultado ambiguo
        ambig_hits = [{"fused_score": 0.028, "dense_score": 0.55}]
        crag_ambig = self.vault.evaluate_confidence(ambig_hits)
        self.assertEqual(crag_ambig["status"], "AMBIGUOUS")
        self.assertEqual(crag_ambig["action"], "refine_or_web")

    def test_raptor_hierarchical_summaries(self):
        sid = self.vault.add_summary(
            title="Sintesis Holistica del Sistema",
            summary="El sistema opera de forma soberana integrando el cerebro temporal con el enlace de tuneles cifrados.",
            level=2,
            cluster_tag="macro_architecture"
        )
        self.assertGreater(sid, 0)
        summaries = self.vault.get_summaries(level=2)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["title"], "Sintesis Holistica del Sistema")

    @patch.object(RAGVault, "embed")
    def test_transversal_retrieve_and_augment(self, mock_embed):
        dummy_vec = np.ones((1, 384), dtype=np.float32)
        dummy_vec /= np.linalg.norm(dummy_vec)
        mock_embed.return_value = dummy_vec

        # Ingerir relaciones y definiciones
        self.vault.ingest(
            "TemporalBrain conecta con TunnelBridge. "
            "TunnelBridge optimiza TardisPocket.",
            source="manual",
            title="Red Soberana"
        )
        self.vault.add_summary("Vision General", "Cohesion de sistemas", level=1)

        # Consulta transversal
        t_res = self.vault.transversal_retrieve("TemporalBrain TunnelBridge", k=2, allow_web=False)
        self.assertIn("hits", t_res)
        self.assertIn("graph_connections", t_res)
        self.assertIn("summaries", t_res)

        # Probar aumento de mensajes para el LLM
        messages = [{"role": "user", "content": "¿Como interactuan TemporalBrain y TunnelBridge?"}]
        augmented = self.vault.augment_messages(messages, k=2, allow_web=False)
        self.assertEqual(len(augmented), 2)
        self.assertEqual(augmented[0]["role"], "system")
        self.assertIn("CONTEXTO COGNITIVO TRANSVERSAL", augmented[0]["content"])
        self.assertIn("TunnelBridge", augmented[0]["content"])


if __name__ == "__main__":
    unittest.main()
