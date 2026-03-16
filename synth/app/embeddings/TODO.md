# Embeddings TODO

## Bugs to Fix

1. **StructureChunker error**
   - Error: `'list' object has no attribute 'metadata'`
   - Happens with some files when using structure chunking
   - Need to investigate and fix the chunking logic

2. **Ollama instability**
   - Ollama API returns 500 for texts > ~1500 chars
   - Currently workaround: use small chunk sizes (≤50)
   - Possible solutions:
     - Add automatic text splitting for large chunks
     - Use different embedding model
     - Add more retries with backoff

3. **Large index creation**
   - Cannot create index for full Obsidian (~123 files)
   - Chunk size must be very small to work

## Features to Add

1. **Batch embedding support**
   - Use Ollama batch API if available
   - Reduce number of API calls

2. **Better error handling**
   - Show progress during index creation
   - Handle Ollama errors gracefully

3. **Version management**
   - When creating index with same name, increment version
   - Already implemented in storage

4. **Rate limiting**
   - Add delay between embedding requests to avoid Ollama 500 errors

5. **CLI improvements**
   - Add progress bar during index creation
   - Add confirmation before delete

## Testing Needed

1. Test with different chunk sizes
2. Test structure chunking (after bug fix)
3. Test RAG with different queries
4. Test UI with many indexes
5. Test delete functionality
