# Vector Maintenance

## Drift

Indexes rot when note content changes but the embeddings stay stale. A vault maintenance process should detect drift, delete obsolete vectors, and reindex the affected notes.

## Safe Repair

Cleaning the archive means handling both markdown state and vector state together instead of treating the embedding index as disposable.
