<!-- Generado por GODWORKS SYSTEM Auto-Improvement Loop el 2026-11-23T22:11:34.645412 -->
<!-- Directiva para Antigravity IDE y Arquitecto -->

# Optimización Autónoma de Resource Governor Ring 0

## Archivo Objetivo
`core/tardis_resource_governor.py`

## Severidad
MEDIUM

## Problema
CPU PSI60=32.39%, RAM libre=12681.5 MB.

## Propuesta Técnica
Estabilizar presión ORANGE (CPU PSI avg60 moderado (32.4%); Temperatura CPU elevada (83°C)) ejecutando reclamación de modelos duplicados y throttling.

## Verificación
```bash
tardis-governor reclaim
```
