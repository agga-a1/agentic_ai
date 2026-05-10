import os
import math
import logging
import chromadb
import re
from chromadb.utils import embedding_functions
from typing import List, Dict, Any, Optional
from google.adk.tools import FunctionTool

# IMPORTANT: import the Python function (NOT the FunctionTool) so we can persist deterministically
from tools.state_store import store_in_state  

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BlueprintRepository:
    # def __init__(self, db_path: Optional[str] = None, collection_name: str = "architecture_standards"):
    #     resolved_db_path = db_path or os.getenv("CHROMA_DB_PATH", "./chroma_db")
    #     self.client = chromadb.PersistentClient(path=resolved_db_path)
    #     self.collection = self.client.get_or_create_collection(
    #         name=collection_name,
    #         embedding_function=embedding_functions.DefaultEmbeddingFunction(),
    #     )
    #     try:
    #         logger.info(
    #             f"[BLUEPRINTS] db_path={resolved_db_path} collection={collection_name} count={self.collection.count()}"
    #         )
    #     except Exception as e:
    #         logger.warning(f"[BLUEPRINTS] count() failed: {e}")
    def __init__(self, db_path: Optional[str] = None, collection_name: str = "architecture_standards"):
        resolved_db_path = db_path or os.getenv("CHROMA_DB_PATH", "./chroma_db")
        self.client = chromadb.PersistentClient(path=resolved_db_path)
        
        # 1. Initialize Vertex AI embeddings with your specific GCP project
        vertex_ef = embedding_functions.GoogleVertexEmbeddingFunction(
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
            region="europe-west2",  # Adjust if needed
            model_name="text-embedding-004" # Standard GCP embedding model
        )

        # 2. Pass the Vertex embedding function to Chroma
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=vertex_ef,
        )
        
        try:
            logger.info(
                f"[BLUEPRINTS] db_path={resolved_db_path} collection={collection_name} count={self.collection.count()}"
            )
        except Exception as e:
            logger.warning(f"[BLUEPRINTS] count() failed: {e}")
            
    def _query(self, query_text: str, n_results: int, where: Optional[Dict[str, Any]]):
        return self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    def _rows(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        docs = (results.get("documents") or [[]])[0] or []
        metas = (results.get("metadatas") or [[]])[0] or []
        dists = (results.get("distances") or [[]])[0] or []
        ids = (results.get("ids") or [[]])[0] or []

        out: List[Dict[str, Any]] = []
        for i, content in enumerate(docs):
            dist = dists[i] if i < len(dists) else None
            meta = metas[i] if i < len(metas) else {}
            doc_id = ids[i] if i < len(ids) else None

            score = None
            if isinstance(dist, (int, float)):
                score = round(math.exp(-float(dist)), 6)

            out.append({
                "id": doc_id,
                "distance": dist,
                "relevance_score": score,
                "content": content or "",
                "metadata": {
                    "area": meta.get("area"),
                    "artifact_type": meta.get("artifact_type"),
                    "doc_type": meta.get("doc_type"),
                    "file": meta.get("file"),
                    "source": meta.get("source"),
                }
            })

        out.sort(key=lambda x: (x["distance"] is None, x["distance"]))
        return out

    def search_blueprint_bundle(
        self,
        query_text: str,
        n_results_overall: int = 5,
        n_per_area: int = 2,
        tool_context=None,
        **kwargs,
    ) -> Dict[str, Any]:
        try:
            if self.collection.count() == 0:
                raise RuntimeError("Blueprint collection is empty. Index blueprints first.")
        except Exception as e:
            logger.warning(f"[BLUEPRINTS] collection.count() failed or empty-check exception: {e}")

        bundle: List[Dict[str, Any]] = []

        # 1) Search Logic
        bundle.extend(self._rows(self._query(query_text, n_results_overall, where=None)))

        for area in (
            "ingestion", "secrets", "security", "nfr", "deployment_strategy",
            "gcp", "migration", "cost", "onprem", "shared_services"
        ):
            bundle.extend(self._rows(self._query(query_text, n_per_area, where={"area": area})))

        # 2) Deduplicate
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for m in bundle:
            mid = m.get("id")
            if mid and mid not in seen:
                seen.add(mid)
                deduped.append(m)

        # 3) Selection Logic (Top Match)
        best_match = deduped[0] if deduped else None

        # 4) Persistent Backend State Update
        if tool_context is not None:
            try:
                # Store full results for reference
                store_in_state(
                    key="blueprint_results",
                    value=deduped,
                    confirmed=True,
                    tool_context=tool_context,
                )
                
                # Store the primary selected blueprint for the Architect
                if best_match:
                    store_in_state(
                        key="blueprint_selected",
                        value=best_match,
                        confirmed=True,
                        tool_context=tool_context,
                    )

                # CRITICAL: Signal completion to workflow
                store_in_state(
                    key="blueprint_search_done",
                    value=True,
                    confirmed=True,
                    tool_context=tool_context,
                )
                
                logger.info(f"[BLUEPRINTS] Backend state updated. Found {len(deduped)} blueprints.")
            except Exception as e:
                logger.warning(f"[BLUEPRINTS] Failed to store via StateStore: {e}")

        # 5) Lightweight Return to Model (Prevents Malformed Function Call)
        # We only return metadata/summaries to the model so it doesn't choke on tokens
        return {
            "status": "success",
            "total_found": len(deduped),
            "top_match": best_match.get("id") if best_match else None,
            "message": "Blueprints stored in system state. Architect will access full data from there."
        }


_repo = BlueprintRepository()
search_blueprint_bundle_tool = FunctionTool(func=_repo.search_blueprint_bundle)