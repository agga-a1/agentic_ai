## This Program is to upload the vector entries into the chromaDB vector database. 
## It is used in the AIA environment to store the vector representations of the data for later retrieval and use in various applications.
import chromadb
import os

# test if the chromaDB client can be created successfully with the downgraded telemetry packages
try:
    client = chromadb.EphemeralClient()
    print("✅ ChromaDB is working with the downgraded telemetry packages!")
except Exception as e:
    print(f"❌ Error: {e}")


# # This line creates a folder in your CURRENT project directory
# chroma_client = chromadb.PersistentClient(path="./chroma_db")

db_path = os.path.join(os.getcwd(), "chroma_db")
# Initialize the client
client = chromadb.PersistentClient(path=db_path)

#Print the actual path to the chromaDB database folder
db_path = "./chroma_db"
print(f"📍 Your AIA Database is located at: {os.path.abspath(db_path)}")