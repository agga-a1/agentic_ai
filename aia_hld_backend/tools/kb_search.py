# import os
# import chromadb
# from chromadb.utils import embedding_functions

# # Ensure this points to your separate chroma_db folder
# CHROMA_PATH = os.path.join(os.getcwd(), "chroma_db")
# COLLECTION_NAME = "architecture_docs"
# client = chromadb.PersistentClient(path=CHROMA_PATH)
# ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
# # collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)
# collection = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef)

# def search_knowledge_base(query: str):
#     """
#     Search the ChromaDB vector store for technical documentation snippets.
#     Use this tool whenever you need specific details about Teradata, 
#     Datahub, or GCP architecture.
#     """
#     try:
#         # Query the DB
#         results = collection.query(query_texts=[query], n_results=3)

#         if not results['documents'][0]:
#             return "No relevant documentation found in the vector database."

#         # Combine text and image metadata for the Agent
#         output = []
#         for i in range(len(results['documents'][0])):
#             text = results['documents'][0][i]
#             metadata = results['metadatas'][0][i]
#             imgs = metadata.get('image_refs', 'None')
            
#             chunk = f"SOURCE: {metadata.get('source')}\nCONTENT: {text}\nIMAGES: {imgs}"
#             output.append(chunk)

#         return "\n\n---\n\n".join(output)
#     except Exception as e:
#         return f"Error accessing ChromaDB: {str(e)}"

import os
import chromadb
from chromadb.utils import embedding_functions

# Config
CHROMA_PATH = os.path.join(os.getcwd(), "chroma_db")
COLLECTION_NAME = "architecture_docs"
IMAGE_DIR = "./agent/images" # Standard path for UI parsing

client = chromadb.PersistentClient(path=CHROMA_PATH)
ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef)

def search_knowledge_base(query: str):
    """
    Search the ChromaDB vector store for UK Market technical documentation.
    Extracts text context, associated image paths, and source metadata.
    """
    try:
        # Increase n_results slightly to ensure we capture enough "Context Pack" depth
        results = collection.query(query_texts=[query], n_results=5)

        if not results['documents'][0]:
            return "RESULT: NO_MARKET_CONTEXT_FOUND"

        output = []
        for i in range(len(results['documents'][0])):
            text = results['documents'][0][i]
            metadata = results['metadatas'][0][i]
            
            # --- IMAGE HANDLING ---
            # We format this exactly as the Retrieval Agent expects to 'clean' it
            raw_imgs = metadata.get('image_refs', 'None')
            formatted_imgs = ""
            if raw_imgs and raw_imgs != "None":
                # Split multiple images and prepend the standard directory path
                img_list = raw_imgs.split(',')
                formatted_imgs = "\n".join([f"IMAGE_REFERENCE: {os.path.join(IMAGE_DIR, img.strip())}" for img in img_list])
            
            # --- CONTEXT BLOCK ---
            chunk = (
                f"SOURCE_FILE: {metadata.get('source', 'Unknown')}\n"
                f"FILE_HASH: {metadata.get('file_hash', 'N/A')}\n"
                f"TECHNICAL_CONTENT: {text}\n"
                f"{formatted_imgs}"
            )
            output.append(chunk)

        # Join with a clear separator for the agent to distinguish chunks
        return "\n\n================================\n\n".join(output)

    except Exception as e:
        return f"Error accessing ChromaDB: {str(e)}"