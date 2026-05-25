-- セマンティックキャッシュテーブル
CREATE TABLE IF NOT EXISTS semantic_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_embedding vector(1024) NOT NULL,
    query_text VARCHAR(1000) NOT NULL,
    search_results JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    ttl_seconds INTEGER NOT NULL DEFAULT 3600
);

-- HNSW インデックス（コサイン類似度用）
CREATE INDEX IF NOT EXISTS idx_semantic_cache_embedding
    ON semantic_cache
    USING hnsw (query_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- TTL クリーンアップ用インデックス
CREATE INDEX IF NOT EXISTS idx_semantic_cache_created_at
    ON semantic_cache (created_at);
