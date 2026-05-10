import os
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = os.path.join(os.getcwd(), "chroma_db")
COLLECTION_NAME = "architecture_docs"

def run_test_query(user_query: str):
    print(f"\n🔍 Testing ChromaDB for: '{user_query}'")
    print("-" * 50)

    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)

        results = collection.query(
            query_texts=[user_query],
            n_results=1 
        )

        if not results['documents'][0]:
            print("❌ No matches found. Did you run ingest_docs.py first?")
            return

        for i, text in enumerate(results['documents'][0]):
            metadata = results['metadatas'][0][i]
            source = metadata.get('source', 'Unknown')
            distance = results['distances'][0][i] if 'distances' in results else "N/A"
            
            # --- IMAGE CHECKING LOGIC ---
            has_images = metadata.get('contains_images', False)
            image_refs = metadata.get('image_refs', "None")

            print(f"MATCH #{i+1} (Source: {source} | Similarity: {distance:.4f})")
            
            if has_images:
                print(f"🖼️  IMAGE DETECTED: {image_refs}")
            else:
                print("📝 No images linked to this chunk.")

            print("-" * 30)
            print(f"FULL CONTENT:\n{text}")
            print("-" * 50)

    except Exception as e:
        print(f"❌ Error during test: {e}")

if __name__ == "__main__":
    my_query = "what is meregeco?"
    run_test_query(my_query)