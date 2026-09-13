-- Allow semantic fusion vectors in the embeddings table.
ALTER TABLE embeddings DROP CONSTRAINT embeddings_embedding_type_check;
ALTER TABLE embeddings ADD CONSTRAINT embeddings_embedding_type_check
  CHECK (embedding_type = ANY (ARRAY['audio-track'::text, 'audio-window'::text, 'lyrics'::text,
    'voice-gender'::text, 'semantic_fusion'::text]));
