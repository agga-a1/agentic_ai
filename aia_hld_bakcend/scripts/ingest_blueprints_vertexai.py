import os
import chromadb
import pandas as pd
from chromadb.utils import embedding_functions
from docx import Document
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
from chromadb.utils.embedding_functions import GoogleVertexEmbeddingFunction
# from agent.config_load import GetConf

BLUEPRINT_AREAS = {
    "security": "standard",
    "secrets": "pattern",
    "ingestion": "pattern",
    "migration": "strategy",
    "deployment_strategy": "strategy",
    "cost": "nfr",
    "nfr": "nfr",
    "onprem": "deployment",
    "gcp": "cloud",
    "shared_services": "service",
    "template": "template"
}

# config = GetConf.load_configs()

class BlueprintIngestor:
    def __init__(self, db_path="./chroma_db", collection_name="architecture_standards"):
        self.client = chromadb.PersistentClient(path=db_path)
# 1. DELETE the old collection if it exists to resolve the conflict
        try:
            self.client.delete_collection(name=collection_name)
            print(f"Deleted existing collection: {collection_name}")
        except Exception:
            # Collection didn't exist, which is fine
            pass
                
        # Initialize Vertex AI embeddings
        vertex_ef = GoogleVertexEmbeddingFunction(
            project_id="<project-name>",  # Replace with your GCP project ID
            region="europe-west2",  # Replace with your GCP region
            model_name="text-embedding-004" # Standard GCP embedding model
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=vertex_ef
        )

    def _extract_docx(self, file_path):
        doc = Document(file_path)
        chunks = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(chunks)

    def _extract_xlsx(self, file_path):
        xls = pd.ExcelFile(file_path, engine="openpyxl")
        text = []

        for sheet in xls.sheet_names:
            if "template" in sheet.lower() or "architecture" in sheet.lower():
                df = pd.read_excel(xls, sheet_name=sheet)
                text.append(f"--- SHEET: {sheet} ---")
                text.append(df.astype(str).to_string(index=False))

        return "\n".join(text) if text else ""

    def load_blueprints(self, source_path):
        for root, _, files in os.walk(source_path):

            area = os.path.basename(root)
            artifact_type = BLUEPRINT_AREAS.get(area, "general")

            for file in files:
                full_path = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()

                if ext not in {".docx", ".xlsx", ".json"}:
                    continue

                try:
                    if ext == ".docx":
                        content = self._extract_docx(full_path)
                    elif ext == ".xlsx":
                        content = self._extract_xlsx(full_path)
                    else:
                        with open(full_path, "r") as f:
                            content = f.read()

                    if not content.strip():
                        continue

                    self.collection.upsert(
                        documents=[content],
                        ids=[f"{area}_{file}"],
                        metadatas=[{
                            "area": area,
                            "artifact_type": artifact_type,
                            "doc_type": "template" if area == "template" else "blueprint",
                            "file": file,
                            "source": "blueprints"
                        }]
                    )

                    print(f"✅ Indexed [{area.upper()}] → {file}")

                except Exception as e:
                    print(f"❌ Failed {file}: {e}")


if __name__ == "__main__":
    ingestor = BlueprintIngestor()
    ingestor.load_blueprints("./agent/blueprints")

    # Future GCS execution
    # ingestor.load_blueprints("gs://your-org-metadata-bucket/blueprints")