"""Orchestration du pipeline de production d'un Short (Phase 2-3).

Ordre prévu : script -> voix -> visuels -> sous-titres -> montage -> export.
Chaque étape met à jour le statut du projet (voir database.db.STATUSES) pour
pouvoir reprendre à l'étape en erreur sans tout recommencer.
"""
