# Pipeline RAG One Moov V1

Le RAG V1 est maintenant complet sur le plan technique :

1. **Source** : documents officiels dans `app/donnees/procedures.json` ou futurs connecteurs/API.
2. **Ingestion** : `scripts/ingerer_rag.py`.
3. **Normalisation** : nettoyage des espaces et conservation des sections.
4. **Chunking** : `app/services/chunker.py`, chunks d'environ 1200 caractères avec chevauchement.
5. **Embeddings** : `app/services/embeddings.py`.
   - Mistral `mistral-embed` par défaut, 1024 dimensions.
   - OpenAI et modèle local restent possibles.
   - Le modèle est enregistré avec chaque vecteur.
6. **Stockage** : PostgreSQL + pgvector dans `passage.embedding`.
7. **Index vectoriel** : HNSW + cosine distance.
8. **Recherche hybride** : vectorielle + plein texte français, fusion RRF.
9. **Filtrage métier** : phase et pays.
10. **Contexte** : `app/services/rag.py` formate les passages et leurs sources.
11. **Génération** : l'Agent 1 Roadmap fournit le contexte RAG au LLM.
12. **Citations** : les numéros utilisés par le modèle sont traduits vers les vraies sources.
13. **Traçabilité** : document, version, URL, organisme, hash du chunk et modèle d'embedding.
14. **Fallback** : si les embeddings sont indisponibles, la recherche plein texte reste utilisable.

## Initialisation

```bash
python -m scripts.migrer
python -m scripts.ingerer_rag
python -m scripts.reembedder
```

Pour tester le retrieval :

```bash
python -m scripts.tester_rag "quelles pièces préparer pour le visa" --phase visa
```

## Important avant lancement

Le corpus fourni est un corpus d'amorçage. Il doit être complété et vérifié à
partir des sources officielles avant de l'utiliser pour de vraies décisions
étudiantes. Le RAG ne doit pas être considéré comme une garantie de fraîcheur :
les procédures, dates, quotas et montants doivent rester dans les tables de
faits critiques ou être récupérés depuis les sources officielles appropriées.
