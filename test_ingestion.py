"""
test_ingestion.py — Quick test script for the ingestion pipeline.

Creates a sample PDF, uploads it via the /upload endpoint, and verifies the result.
Run with: python test_ingestion.py
"""

import os
import sys
import tempfile
from pathlib import Path

# Add backend to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def create_sample_pdf(path: str):
    """Create a simple multi-page PDF for testing."""
    c = canvas.Canvas(path, pagesize=letter)
    
    # Page 1
    c.drawString(100, 750, "VecQuery Intelligence Test Document")
    c.drawString(100, 730, "=" * 50)
    c.drawString(100, 700, "This is a test document for the ingestion pipeline.")
    c.drawString(100, 680, "It contains multiple pages with different content.")
    c.drawString(100, 660, "The system should chunk this text and embed it using Ollama.")
    c.showPage()
    
    # Page 2
    c.drawString(100, 750, "Page 2: Technical Details")
    c.drawString(100, 730, "=" * 50)
    c.drawString(100, 700, "VecQuery uses hybrid search combining pgvector and BM25.")
    c.drawString(100, 680, "The embedding model is nomic-embed-text running locally via Ollama.")
    c.drawString(100, 660, "All data is stored in Supabase PostgreSQL with the pgvector extension.")
    c.showPage()
    
    # Page 3
    c.drawString(100, 750, "Page 3: Architecture")
    c.drawString(100, 730, "=" * 50)
    c.drawString(100, 700, "Backend: FastAPI with Python")
    c.drawString(100, 680, "Frontend: React with Vite")
    c.drawString(100, 660, "Database: Supabase (PostgreSQL + pgvector)")
    c.drawString(100, 640, "LLM: Llama 3.1 8B via Ollama")
    c.showPage()
    
    c.save()
    print(f"✓ Created sample PDF: {path}")


def test_ingestion():
    """Test the full ingestion pipeline."""
    print("\n" + "="*60)
    print("VecQuery Ingestion Pipeline Test")
    print("="*60 + "\n")
    
    # Check if Ollama is running
    print("1. Checking Ollama connection...")
    import httpx
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=5)
        response.raise_for_status()
        print("   ✓ Ollama is running")
    except Exception as e:
        print(f"   ✗ Ollama is not running: {e}")
        print("   → Start Ollama with: ollama serve")
        return False
    
    # Check if nomic-embed-text is available
    print("2. Checking nomic-embed-text model...")
    try:
        models = response.json().get("models", [])
        has_nomic = any("nomic-embed-text" in m.get("name", "") for m in models)
        if has_nomic:
            print("   ✓ nomic-embed-text is available")
        else:
            print("   ✗ nomic-embed-text not found")
            print("   → Pull it with: ollama pull nomic-embed-text")
            return False
    except Exception as e:
        print(f"   ✗ Could not check models: {e}")
        return False
    
    # Check database connection
    print("3. Checking database connection...")
    from database import engine
    try:
        with engine.connect() as conn:
            result = conn.execute("SELECT 1")
            result.fetchone()
        print("   ✓ Database connection successful")
    except Exception as e:
        print(f"   ✗ Database connection failed: {e}")
        print("   → Check your DATABASE_URL in backend/.env")
        return False
    
    # Create sample PDF
    print("4. Creating sample PDF...")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = tmp.name
    try:
        create_sample_pdf(pdf_path)
    except ImportError:
        print("   ✗ reportlab not installed (optional for this test)")
        print("   → Install with: pip install reportlab")
        print("   → Or manually place a PDF in /tmp/test.pdf and update the script")
        return False
    
    # Run ingestion
    print("5. Running ingestion pipeline...")
    from database import SessionLocal
    from ingestion import ingest_file
    
    db = SessionLocal()
    try:
        result = ingest_file(
            file_path=pdf_path,
            file_name="test_document.pdf",
            db=db,
        )
        print(f"\n   ✓ Ingestion successful!")
        print(f"   → Document ID: {result['document_id']}")
        print(f"   → Chunks created: {result['chunk_count']}")
        print(f"   → File name: {result['file_name']}")
        
        # Verify data in database
        print("\n6. Verifying database records...")
        from database import Document, Chunk, Embedding
        
        doc = db.query(Document).filter(Document.id == result['document_id']).first()
        chunks = db.query(Chunk).filter(Chunk.document_id == doc.id).all()
        embeddings = db.query(Embedding).join(Chunk).filter(Chunk.document_id == doc.id).all()
        
        print(f"   ✓ Document record: {doc.name} ({doc.type})")
        print(f"   ✓ Chunk records: {len(chunks)}")
        print(f"   ✓ Embedding records: {len(embeddings)}")
        
        # Show first chunk
        if chunks:
            first_chunk = chunks[0]
            print(f"\n   First chunk preview:")
            print(f"   → Content: {first_chunk.content[:100]}...")
            print(f"   → Page: {first_chunk.page_number}")
            print(f"   → BM25 terms: {len(first_chunk.chunk_metadata.get('bm25_terms', {}))}")
        
        print("\n" + "="*60)
        print("✓ All tests passed! Ingestion pipeline is working.")
        print("="*60 + "\n")
        return True
        
    except Exception as e:
        print(f"\n   ✗ Ingestion failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()
        os.unlink(pdf_path)


if __name__ == "__main__":
    success = test_ingestion()
    sys.exit(0 if success else 1)
