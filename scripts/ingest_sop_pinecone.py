import os
import hashlib
import json
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
import pypdf

# Pinecone client and spec for vector database management
from pinecone import Pinecone, ServerlessSpec

# LangChain components for vector embeddings and storage integration
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Suppress Hugging Face symlink warnings on platforms like Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "true"


# =====================================================================
# 1. PATH RESOLUTION, ENVIRONMENT & CACHE SETUP
# =====================================================================
# Resolve dynamic paths relative to the current file location
# This prevents broken file references regardless of where the script is executed from
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent

# Load environment variables (.env) from the root directory
load_dotenv(project_root / ".env")

# Verify Pinecone credentials exist before attempting any vector operations
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
if not PINECONE_API_KEY:
    raise ValueError("Missing PINECONE_API_KEY in .env file.")

# Define and ensure existence of local directory for ingestion cache
cache_dir = project_root / "data" / "cache"
cache_dir.mkdir(parents=True, exist_ok=True)
HASH_CACHE_FILE = cache_dir / "ingestion_hash_cache.json"

# Load the prior run's MD5 file hash table to enable incremental indexing
hash_cache = {}
if HASH_CACHE_FILE.exists():
    try:
        with open(HASH_CACHE_FILE, "r", encoding="utf-8") as f:
            hash_cache = json.load(f)
    except Exception:
        # If cache JSON is corrupt or unreadable, fall back to empty state
        hash_cache = {}
        print("Hash cache initialized as empty due to read error.")


# =====================================================================
# 2. DYNAMIC EMBEDDING MODEL ROUTING
# =====================================================================

# Determine whether to use remote OpenAI APIs or local CPU/GPU Hugging Face models
EMBEDDINGS_MODEL_SETTING = os.getenv("Embeddings_model", "LOCAL").strip().upper()
BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")

if EMBEDDINGS_MODEL_SETTING == "OPENAI":
    # 1536 dimensions match OpenAI's text-embedding-ada-002 or text-embedding-3-small
    print("Mode: Utilizing Cloud OpenAI Embeddings (1536 Dim)...")
    embeddings = OpenAIEmbeddings(api_key=API_KEY,base_url=BASE_URL,model="text-embedding-3-small")
    INDEX_NAME = "sop-index-openai"
    TARGET_DIMENSION = 1536

else:
    # Default to BAAI/bge-m3: multi-lingual, high accuracy, 1024 embedding dimension
    local_model_target = os.getenv("Local_Embedding_Model", "BAAI/bge-m3").strip()
    print(f"Mode: Local HuggingFace Embedding Activated. Loading [{local_model_target}] (1024 Dim)...")
    from langchain_huggingface import HuggingFaceEmbeddings

    embeddings = HuggingFaceEmbeddings(
        model_name=local_model_target,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},  # Enables standard cosine similarity search
    )
    INDEX_NAME = "sop-index-local"
    TARGET_DIMENSION = 1024


# =====================================================================
# 3. PINECONE PROVISIONING & SELF-HEALING
# =====================================================================

print(f"Connecting to Pinecone target index: [{INDEX_NAME}]...")
pc = Pinecone(api_key=PINECONE_API_KEY)

# Fetch all existing index names in the Pinecone project
existing_indexes = pc.list_indexes().names()

# Self-healing check: If the index exists with an incompatible dimension, drop it
if INDEX_NAME in existing_indexes:
    desc = pc.describe_index(INDEX_NAME)
    if desc.dimension != TARGET_DIMENSION:
        print(f"Dimension mismatch detected (Found: {desc.dimension}, Needed: {TARGET_DIMENSION}). Recreating index...")
        pc.delete_index(INDEX_NAME)
        existing_indexes = [name for name in existing_indexes if name != INDEX_NAME]

# Provision a new serverless index if it doesn't already exist
if INDEX_NAME not in existing_indexes:
    print(f"Creating isolated Serverless index: {INDEX_NAME} ({TARGET_DIMENSION} Dim)...")
    pc.create_index(
        name=INDEX_NAME,
        dimension=TARGET_DIMENSION,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )

# Connect to the target index client and bind it into LangChain's vector store abstraction
index_client = pc.Index(INDEX_NAME)
vector_store = PineconeVectorStore(index=index_client, embedding=embeddings)


# =====================================================================
# 4. POLYMORPHIC PARSER & CHUNKING ENGINE
# =====================================================================

def parse_and_chunk_document(doc_path: Path) -> list[Document]:
    """
    Parses documents based on file extension (.md, .txt, .pdf, .csv, .xlsx)
    and splits them into semantically cohesive LangChain Document objects.
    """
    ext = doc_path.suffix.lower()
    raw_chunks: list[Document] = []
    
    # Generic chunking configuration for non-tabular text
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)

    # Markdown: Split hierarchically by headers first to preserve section context
    if ext == ".md":
        headers_to_split_on = [("#", "Header_1"), ("##", "Header_2"), ("###", "Header_3")]
        md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        raw_text = doc_path.read_text(encoding="utf-8")
        header_docs = md_splitter.split_text(raw_text)
        raw_chunks = text_splitter.split_documents(header_docs)

    # Plain text: Direct character-recursive splitting
    elif ext == ".txt":
        raw_text = doc_path.read_text(encoding="utf-8")
        raw_docs = [Document(page_content=raw_text)]
        raw_chunks = text_splitter.split_documents(raw_docs)

    # PDF: Extract page-by-page and attach page number metadata
    elif ext == ".pdf":
        pdf_docs = []
        try:
            with open(doc_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                for page_num, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        pdf_docs.append(
                            Document(
                                page_content=page_text,
                                metadata={"page_number": page_num + 1},
                            )
                        )
            raw_chunks = text_splitter.split_documents(pdf_docs)
        except Exception as e:
            print(f"  Error reading PDF {doc_path.name}: {e}")
            return []

    # Tabular (CSV / Excel): Convert individual rows into key-value pairs
    elif ext in [".csv", ".xlsx"]:
        try:
            df = pd.read_csv(doc_path) if ext == ".csv" else pd.read_excel(doc_path)
        except Exception as e:
            print(f"  Error reading spreadsheet {doc_path.name}: {e}")
            return []

        for idx, row in df.iterrows():
            row_dict = row.to_dict()
            # Retain non-null columns and format as "Column: Value"
            row_items = [
                f"{col}: {val}"
                for col, val in row_dict.items()
                if pd.notna(val) and str(val).strip() != ""
            ]
            if row_items:
                row_text = " | ".join(row_items)
                doc_item = Document(page_content=row_text, metadata={"row_index": int(idx)})
                raw_chunks.append(doc_item)

    # Sanity filter: Discard empty, whitespace-only chunks
    valid_chunks = []
    for chunk in raw_chunks:
        clean_text = chunk.page_content.strip()
        if clean_text:
            chunk.page_content = clean_text
            valid_chunks.append(chunk)

    return valid_chunks


# =====================================================================
# 5. INCREMENTAL PIPELINE WITH BATCHED UPSERT & VECTOR PRUNING
# =====================================================================

# Define input policy directory and ensure it exists
policy_dir = project_root / "data" / "policy"
policy_dir.mkdir(parents=True, exist_ok=True)
target_patterns = ["*.md", "*.txt", "*.pdf", "*.csv", "*.xlsx"]

# Scan directory for all eligible document files
current_files = {}
for pattern in target_patterns:
    for filepath in policy_dir.glob(pattern):
        current_files[filepath.name] = filepath

print(f"Found {len(current_files)} policy file(s) in {policy_dir}...")

# Track state changes for caching
updated_cache = dict(hash_cache)
cache_modified = False

cached_filenames = set(hash_cache.keys())
current_filenames = set(current_files.keys())

# Step 5a: Identify files removed from local disk since the previous run
deleted_files = cached_filenames - current_filenames


def delete_file_chunks(file_identifier: str):
    """
    Deletes all vector chunks associated with a source file.
    Tries metadata filtering first; if serverless doesn't support filter deletes,
    falls back to pagination using deterministic ID prefixes.
    """
    try:
        index_client.delete(filter={"source_file": {"$eq": file_identifier}})
    except Exception:
        # Fallback: Query and delete vector IDs by prefix
        for ids_batch in index_client.list(prefix=f"{file_identifier}-chunk-"):
            if ids_batch:
                index_client.delete(ids=ids_batch)


# Purge deleted files from the Pinecone vector index and update cache
for deleted_file in deleted_files:
    print(f"Purging deleted document from Pinecone: {deleted_file}...")
    try:
        delete_file_chunks(deleted_file)
        updated_cache.pop(deleted_file, None)
        cache_modified = True
    except Exception as e:
        print(f"  Failed to purge {deleted_file}: {e}")

# Step 5b: Process new and modified files
for file_name, file_path in current_files.items():
    # Compute MD5 checksum to detect content modifications
    file_bytes = file_path.read_bytes()
    file_hash = hashlib.md5(file_bytes).hexdigest()

    # Skip files whose contents have not changed since last run
    if hash_cache.get(file_name) == file_hash:
        print(f"Skipped (Unchanged): {file_name}")
        continue

    print(f"Processing updates: {file_name}...")
    cache_modified = True

    try:
        # Purge older vector versions of this file prior to re-indexing
        delete_file_chunks(file_name)

        # Parse and chunk document
        chunks = parse_and_chunk_document(file_path)
        if not chunks:
            print(f"  No valid text extracted from {file_name}. Skipping upsert.")
            continue

        # Attach standardized metadata and build deterministic chunk IDs
        explicit_ids = []
        for idx, chunk in enumerate(chunks):
            chunk.metadata["source_file"] = file_name
            chunk.metadata["file_format"] = file_path.suffix.replace(".", "").upper()
            chunk.metadata["document_type"] = "Compliance Asset"
            explicit_ids.append(f"{file_name}-chunk-{idx}")

        # Batch upsert to prevent HTTP payload size timeouts
        batch_size = 100
        total_chunks = len(chunks)
        print(f"  Upserting {total_chunks} chunk(s) in batches of {batch_size}...")

        for i in range(0, total_chunks, batch_size):
            batch_docs = chunks[i : i + batch_size]
            batch_ids = explicit_ids[i : i + batch_size]
            vector_store.add_documents(documents=batch_docs, ids=batch_ids)

        # Record new hash in cache upon successful ingestion
        updated_cache[file_name] = file_hash

    except Exception as e:
        print(f"Error during ingestion of {file_name}: {e}")
        # Ensure failure does not store corrupt state in cache
        updated_cache.pop(file_name, None)

# Persist cache to disk if any creations, updates, or deletions occurred
if cache_modified:
    with open(HASH_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_cache, f, indent=4)
    print("Ingestion and cache update complete.")
else:
    print("Index is already up-to-date.")