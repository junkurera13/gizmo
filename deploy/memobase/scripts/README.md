The memory service uses Fal's OpenAI-compatible endpoint for Claude Haiku 4.5 and Qwen3 Embedding 8B (1536 dimensions). Set `MEMOBASE_LLM_API_KEY` to the Fal key through Railway secrets. Embedding credentials and URL inherit the LLM configuration.

For migration from the previous Google embeddings:

1. Set `MEMOBASE_ENABLE_EVENT_EMBEDDING=false` and deploy the new Fal configuration. Wait for the old deployment to stop. Profile/context access continues; vector search is briefly unavailable.
2. Run `/app/.venv/bin/python /app/gizmo_scripts/reembed_fal.py` inside Memobase. It locks the event tables, preserves backup copies, regenerates vectors, and commits everything together. Any failure rolls back all replacements.
3. Set `MEMOBASE_ENABLE_EVENT_EMBEDDING=true` and explicitly redeploy. Confirm startup embedding validation succeeds.
4. Run the script with `--only-missing` to index records written during the deployment. Verify original event content and timestamps against the backup tables and exercise memory insert, flush, and context retrieval.

Backup tables `user_events_before_fal_20260909` and `user_event_gists_before_fal_20260909` remain in the same private database. Do not mix vectors from different models even when their dimensions match.
