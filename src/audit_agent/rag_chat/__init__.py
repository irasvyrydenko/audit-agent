"""rag_chat — question answering over one 10-K with retrieval and citations.

Purpose: Answer an auditor's free-text question about one company-year. Filing paragraphs
    (Items 1A/7/8) are embedded and stored in MongoDB with Atlas Vector Search; XBRL KPIs and
    indicators are stored next to them as one document per company-year. A LangGraph agent
    plans the lookup (search query, Items to search, whether figures are needed), retrieves
    evidence, writes an answer whose sentences cite evidence ids, verifies every sentence by
    code and retries retrieval without the Item filter if nothing survived (D-018).
Input: question, ticker, fiscal_year; index built by `scripts/build_rag_index.py` from the
    cached `Filing`, `KPISet` and `Indicator` outputs.
Output: `ChatAnswer` (list[ChatStatement], each a CitedStatement) + the evidence used.
Calls a model: yes — planner + answer (≤ 3 calls per question, fixed model, cached);
    embeddings: local `rag.embedding_model` via fastembed (no API).
External tool: MongoDB (docker-compose.yml, `MONGODB_URI`).
Eval: evals/rag_chat — retrieval hit@k / recall@k / MRR vs a TF-IDF baseline on gold
    questions; answer faithfulness, citation correctness, uncited = 0, gold-evidence rate.
"""
