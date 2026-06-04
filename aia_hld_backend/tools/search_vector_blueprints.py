# import os
# import math
# import logging
# import chromadb
# import re
# from chromadb.utils import embedding_functions
# from typing import List, Dict, Any, Optional
# from google.adk.tools import FunctionTool

# # IMPORTANT: import the Python function (NOT the FunctionTool) so we can persist deterministically
# from tools.state_store import store_in_state  

# logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)


# class BlueprintRepository:
#     def __init__(self, db_path: Optional[str] = None, collection_name: str = "architecture_standards"):
#         resolved_db_path = db_path or os.getenv("CHROMA_DB_PATH", "./chroma_db")
#         self.client = chromadb.PersistentClient(path=resolved_db_path)
        
#         # 1. Initialize Vertex AI embeddings with your specific GCP project
#         vertex_ef = embedding_functions.GoogleVertexEmbeddingFunction(
#             project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
#             region="europe-west2",  # Adjust if needed
#             model_name="text-embedding-004" # Standard GCP embedding model
#         )

#         # 2. Pass the Vertex embedding function to Chroma
#         self.collection = self.client.get_or_create_collection(
#             name=collection_name,
#             embedding_function=vertex_ef,
#         )
        
#         try:
#             logger.info(
#                 f"[BLUEPRINTS] db_path={resolved_db_path} collection={collection_name} count={self.collection.count()}"
#             )
#         except Exception as e:
#             logger.warning(f"[BLUEPRINTS] count() failed: {e}")
            
#     def _query(self, query_text: str, n_results: int, where: Optional[Dict[str, Any]]):
#         return self.collection.query(
#             query_texts=[query_text],
#             n_results=n_results,
#             where=where,
#             include=["documents", "metadatas", "distances"],
#         )

#     def _rows(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
#         docs = (results.get("documents") or [[]])[0] or []
#         metas = (results.get("metadatas") or [[]])[0] or []
#         dists = (results.get("distances") or [[]])[0] or []
#         ids = (results.get("ids") or [[]])[0] or []

#         out: List[Dict[str, Any]] = []
#         for i, content in enumerate(docs):
#             dist = dists[i] if i < len(dists) else None
#             meta = metas[i] if i < len(metas) else {}
#             doc_id = ids[i] if i < len(ids) else None

#             score = None
#             if isinstance(dist, (int, float)):
#                 score = round(math.exp(-float(dist)), 6)

#             out.append({
#                 "id": doc_id,
#                 "distance": dist,
#                 "relevance_score": score,
#                 "content": content or "",
#                 "metadata": {
#                     "area": meta.get("area"),
#                     "artifact_type": meta.get("artifact_type"),
#                     "doc_type": meta.get("doc_type"),
#                     "file": meta.get("file"),
#                     "source": meta.get("source"),
#                 }
#             })

#         out.sort(key=lambda x: (x["distance"] is None, x["distance"]))
#         return out

#     def search_blueprint_bundle(
#         self,
#         query_text: str,
#         n_results_overall: int = 5,
#         n_per_area: int = 2,
#         tool_context=None,
#         **kwargs,
#     ) -> Dict[str, Any]:
#         try:
#             if self.collection.count() == 0:
#                 raise RuntimeError("Blueprint collection is empty. Index blueprints first.")
#         except Exception as e:
#             logger.warning(f"[BLUEPRINTS] collection.count() failed or empty-check exception: {e}")

#         bundle: List[Dict[str, Any]] = []

#         # 1) Search Logic
#         bundle.extend(self._rows(self._query(query_text, n_results_overall, where=None)))

#         for area in (
#             "ingestion", "secrets", "security", "nfr", "deployment_strategy",
#             "gcp", "migration", "cost", "onprem", "shared_services"
#         ):
#             bundle.extend(self._rows(self._query(query_text, n_per_area, where={"area": area})))

#         # 2) Deduplicate
#         seen = set()
#         deduped: List[Dict[str, Any]] = []
#         for m in bundle:
#             mid = m.get("id")
#             if mid and mid not in seen:
#                 seen.add(mid)
#                 deduped.append(m)

#         # 3) Selection Logic (Top Match)
#         best_match = deduped[0] if deduped else None

#         # 4) Persistent Backend State Update
#         if tool_context is not None:
#             try:
#                 # Store full results for reference
#                 store_in_state(
#                     key="blueprint_results",
#                     value=deduped,
#                     confirmed=True,
#                     tool_context=tool_context,
#                 )
                
#                 # Store the primary selected blueprint for the Architect
#                 if best_match:
#                     store_in_state(
#                         key="blueprint_selected",
#                         value=best_match,
#                         confirmed=True,
#                         tool_context=tool_context,
#                     )

#                 # CRITICAL: Signal completion to workflow
#                 store_in_state(
#                     key="blueprint_search_done",
#                     value=True,
#                     confirmed=True,
#                     tool_context=tool_context,
#                 )
                
#                 logger.info(f"[BLUEPRINTS] Backend state updated. Found {len(deduped)} blueprints.")
#             except Exception as e:
#                 logger.warning(f"[BLUEPRINTS] Failed to store via StateStore: {e}")

#         # 5) Lightweight Return to Model (Prevents Malformed Function Call)
#         # We only return metadata/summaries to the model so it doesn't choke on tokens
#         return {
#             "status": "success",
#             "total_found": len(deduped),
#             "top_match": best_match.get("id") if best_match else None,
#             "message": "Blueprints stored in system state. Architect will access full data from there."
#         }


# _repo = BlueprintRepository()
# search_blueprint_bundle_tool = FunctionTool(func=_repo.search_blueprint_bundle)

import os
import math
import json
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple

import chromadb
from chromadb.utils import embedding_functions
from google.adk.tools import FunctionTool

# IMPORTANT: import the Python function, not FunctionTool
from tools.state_store import store_in_state


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BlueprintRepository:
    """
    Generic Blueprint Repository for ChromaDB.

    Design:
    - No hardcoded area list.
    - No hardcoded HLD sections.
    - No hardcoded folder names.
    - Dynamically uses available metadata from ChromaDB.
    - Supports JSONL-ingested blueprint documents and regular file-ingested documents.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        collection_name: Optional[str] = None,
        project_id: Optional[str] = None,
        region: Optional[str] = None,
        model_name: Optional[str] = None,
        metadata_scan_limit: int = 5000,
    ):
        self.db_path = db_path or os.getenv("CHROMA_DB_PATH", "./chroma_db")
        self.collection_name = collection_name or os.getenv(
            "CHROMA_COLLECTION",
            "architecture_standards",
        )

        self.project_id = (
            project_id
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCP_PROJECT_ID")
            or os.getenv("PROJECT_ID")
        )

        self.region = (
            region
            or os.getenv("GOOGLE_CLOUD_REGION")
            or os.getenv("GCP_REGION")
            or os.getenv("REGION")
            or "europe-west2"
        )

        self.model_name = (
            model_name
            or os.getenv("EMBEDDING_MODEL_NAME")
            or os.getenv("EMBEDDING_MODEL")
            or "text-embedding-004"
        )

        self.metadata_scan_limit = metadata_scan_limit
        self._metadata_value_cache: Optional[List[Tuple[str, Any]]] = None

        if self.project_id:
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", self.project_id)
            os.environ.setdefault("GOOGLE_CLOUD_QUOTA_PROJECT", self.project_id)

        self.client = chromadb.PersistentClient(path=self.db_path)

        vertex_ef = embedding_functions.GoogleVertexEmbeddingFunction(
            project_id=self.project_id,
            region=self.region,
            model_name=self.model_name,
        )

        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=vertex_ef,
        )

        try:
            logger.info(
                "[BLUEPRINTS] db_path=%s collection=%s count=%s",
                self.db_path,
                self.collection_name,
                self.collection.count(),
            )
        except Exception as error:
            logger.warning("[BLUEPRINTS] count() failed: %s", error)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _normalise_text(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _safe_hash(self, value: str) -> str:
        return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:16]

    def _is_scalar_metadata_value(self, value: Any) -> bool:
        return isinstance(value, (str, int, float, bool))

    def _shorten(self, text: str, max_chars: int = 1200) -> str:
        text = text or ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    def _score_from_distance(self, distance: Any) -> Optional[float]:
        if isinstance(distance, (int, float)):
            return round(math.exp(-float(distance)), 6)
        return None

    # ------------------------------------------------------------------
    # Query wrappers
    # ------------------------------------------------------------------
    def _query(
        self,
        query_text: str,
        n_results: int,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        kwargs = {
            "query_texts": [query_text],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }

        if where:
            kwargs["where"] = where

        return self.collection.query(**kwargs)

    def _rows(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        docs = (results.get("documents") or [[]])[0] or []
        metas = (results.get("metadatas") or [[]])[0] or []
        dists = (results.get("distances") or [[]])[0] or []
        ids = (results.get("ids") or [[]])[0] or []

        rows: List[Dict[str, Any]] = []

        for index, content in enumerate(docs):
            distance = dists[index] if index < len(dists) else None
            metadata = metas[index] if index < len(metas) else {}
            doc_id = ids[index] if index < len(ids) else None

            fallback_id = self._safe_hash(
                f"{content[:500]}::{json.dumps(metadata, sort_keys=True, default=str)}"
            )

            rows.append(
                {
                    "id": doc_id or fallback_id,
                    "distance": distance,
                    "relevance_score": self._score_from_distance(distance),
                    "content": content or "",
                    "metadata": metadata or {},
                    "content_preview": self._shorten(content or "", max_chars=1000),
                }
            )

        rows.sort(key=lambda item: (item["distance"] is None, item["distance"]))
        return rows

    # ------------------------------------------------------------------
    # Dynamic metadata discovery
    # ------------------------------------------------------------------
    def _load_metadata_value_cache(self) -> List[Tuple[str, Any]]:
        """
        Dynamically discovers metadata keys and scalar values already present
        in ChromaDB. No fixed folder/area/service list is required.
        """
        if self._metadata_value_cache is not None:
            return self._metadata_value_cache

        discovered: List[Tuple[str, Any]] = []

        try:
            result = self.collection.get(
                limit=self.metadata_scan_limit,
                include=["metadatas"],
            )

            metadatas = result.get("metadatas") or []

            seen = set()

            for metadata in metadatas:
                if not isinstance(metadata, dict):
                    continue

                for key, value in metadata.items():
                    if value is None:
                        continue

                    if not self._is_scalar_metadata_value(value):
                        continue

                    value_text = str(value).strip()

                    # Avoid very long metadata values as exact filters.
                    if not value_text or len(value_text) > 120:
                        continue

                    pair_key = (str(key), value_text)

                    if pair_key in seen:
                        continue

                    seen.add(pair_key)
                    discovered.append((str(key), value))

            logger.info(
                "[BLUEPRINTS] Discovered %s metadata key/value pairs dynamically",
                len(discovered),
            )

        except Exception as error:
            logger.warning("[BLUEPRINTS] Metadata discovery failed: %s", error)

        self._metadata_value_cache = discovered
        return discovered

    def _infer_metadata_filters_from_query(
        self,
        query_text: str,
        max_filters: int = 8,
    ) -> List[Dict[str, Any]]:
        """
        Generic filter inference:
        - Scans indexed metadata values.
        - If metadata value appears in query text, create an exact where filter.
        - No hardcoded area/cloud/domain list.
        """
        query_lower = self._normalise_text(query_text)
        filters: List[Dict[str, Any]] = []

        if not query_lower:
            return filters

        for key, value in self._load_metadata_value_cache():
            value_lower = self._normalise_text(value)

            if not value_lower:
                continue

            # Match only meaningful values.
            if len(value_lower) < 3:
                continue

            if value_lower in query_lower:
                filters.append({key: value})

            if len(filters) >= max_filters:
                break

        return filters

    def _normalise_user_filters(
        self,
        metadata_filters: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Converts optional user/tool filters into Chroma where filters.

        Example input:
            {"cloud": "gcp", "domain": "architecture_patterns"}

        Output:
            [{"cloud": "gcp"}, {"domain": "architecture_patterns"}]
        """
        if not metadata_filters:
            return []

        filters = []

        for key, value in metadata_filters.items():
            if value is None:
                continue

            if self._is_scalar_metadata_value(value):
                filters.append({str(key): value})

        return filters

    # ------------------------------------------------------------------
    # Deduplication and context shaping
    # ------------------------------------------------------------------
    def _dedupe_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        deduped: List[Dict[str, Any]] = []

        for row in rows:
            row_id = row.get("id")

            if not row_id:
                row_id = self._safe_hash(row.get("content", ""))

            if row_id in seen:
                continue

            seen.add(row_id)
            deduped.append(row)

        deduped.sort(key=lambda item: (item["distance"] is None, item["distance"]))
        return deduped

    def _build_context_text(
        self,
        rows: List[Dict[str, Any]],
        max_items: int = 8,
        max_chars_per_item: int = 2500,
    ) -> str:
        """
        Creates compact text context for downstream architect agent.
        Full rows are also stored separately.
        """
        parts = []

        for index, row in enumerate(rows[:max_items], start=1):
            metadata = row.get("metadata") or {}

            metadata_preview = {
                key: metadata.get(key)
                for key in sorted(metadata.keys())
                if metadata.get(key) is not None
            }

            parts.append(
                "\n".join(
                    [
                        f"### Blueprint Match {index}",
                        f"ID: {row.get('id')}",
                        f"Relevance Score: {row.get('relevance_score')}",
                        f"Distance: {row.get('distance')}",
                        f"Metadata: {json.dumps(metadata_preview, ensure_ascii=False)}",
                        "Content:",
                        self._shorten(row.get("content", ""), max_chars=max_chars_per_item),
                    ]
                )
            )

        return "\n\n".join(parts).strip()

    def _summarise_for_model(
        self,
        rows: List[Dict[str, Any]],
        max_items: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Lightweight return only. Avoid sending full blueprint content to LLM tool response.
        """
        summary = []

        for row in rows[:max_items]:
            metadata = row.get("metadata") or {}

            summary.append(
                {
                    "id": row.get("id"),
                    "relevance_score": row.get("relevance_score"),
                    "distance": row.get("distance"),
                    "metadata": metadata,
                    "preview": row.get("content_preview"),
                }
            )

        return summary

    # ------------------------------------------------------------------
    # Public tool method
    # ------------------------------------------------------------------
    def search_blueprint_bundle(
        self,
        query_text: str,
        n_results_overall: int = 8,
        n_per_filter: int = 3,
        max_total: int = 20,
        metadata_filters: Optional[Dict[str, Any]] = None,
        tool_context=None,
    ) -> Dict[str, Any]:
        """
        Generic blueprint search.

        Search strategy:
        1. Broad semantic search.
        2. Optional metadata-filtered search from caller-provided filters.
        3. Dynamic metadata-filtered search inferred from query text.
        4. Deduplicate and rank.
        5. Store full results in state.
        6. Return lightweight summary.
        """
        try:
            count = self.collection.count()
            if count == 0:
                raise RuntimeError("Blueprint collection is empty. Index blueprints first.")
        except Exception as error:
            logger.warning("[BLUEPRINTS] collection.count() failed: %s", error)

        if not query_text or not str(query_text).strip():
            return {
                "status": "error",
                "message": "query_text is required for blueprint search.",
                "total_found": 0,
                "top_match": None,
            }

        query_text = str(query_text).strip()
        bundle: List[Dict[str, Any]] = []

        executed_filters: List[Dict[str, Any]] = []

        try:
            # 1. Broad search — always run.
            bundle.extend(
                self._rows(
                    self._query(
                        query_text=query_text,
                        n_results=n_results_overall,
                        where=None,
                    )
                )
            )

            # 2. Caller-provided filters — fully dynamic.
            user_filters = self._normalise_user_filters(metadata_filters)

            # 3. Query-inferred filters from existing Chroma metadata — dynamic.
            inferred_filters = self._infer_metadata_filters_from_query(query_text)

            combined_filters = user_filters + inferred_filters

            # Deduplicate filter dictionaries.
            filter_seen = set()
            unique_filters = []

            for where_filter in combined_filters:
                signature = json.dumps(where_filter, sort_keys=True, default=str)

                if signature in filter_seen:
                    continue

                filter_seen.add(signature)
                unique_filters.append(where_filter)

            for where_filter in unique_filters:
                try:
                    executed_filters.append(where_filter)

                    bundle.extend(
                        self._rows(
                            self._query(
                                query_text=query_text,
                                n_results=n_per_filter,
                                where=where_filter,
                            )
                        )
                    )

                except Exception as filter_error:
                    logger.warning(
                        "[BLUEPRINTS] Filtered query failed where=%s error=%s",
                        where_filter,
                        filter_error,
                    )

            deduped = self._dedupe_rows(bundle)
            selected = deduped[:max_total]
            best_match = selected[0] if selected else None

            blueprint_context_text = self._build_context_text(selected)

            # 4. Persist full results for downstream agents.
            if tool_context is not None:
                try:
                    store_in_state(
                        key="blueprint_results",
                        value=selected,
                        confirmed=True,
                        tool_context=tool_context,
                    )

                    store_in_state(
                        key="blueprint_context_text",
                        value=blueprint_context_text,
                        confirmed=True,
                        tool_context=tool_context,
                    )

                    if best_match:
                        store_in_state(
                            key="blueprint_selected",
                            value=best_match,
                            confirmed=True,
                            tool_context=tool_context,
                        )

                    store_in_state(
                        key="blueprint_search_done",
                        value=True,
                        confirmed=True,
                        tool_context=tool_context,
                    )

                    logger.info(
                        "[BLUEPRINTS] State updated. total=%s selected=%s",
                        len(selected),
                        best_match.get("id") if best_match else None,
                    )

                except Exception as state_error:
                    logger.warning(
                        "[BLUEPRINTS] Failed to store blueprint results in state: %s",
                        state_error,
                    )

            return {
                "status": "success",
                "total_found": len(selected),
                "top_match": best_match.get("id") if best_match else None,
                "executed_filters": executed_filters,
                "results_summary": self._summarise_for_model(selected),
                "message": (
                    "Blueprint results were retrieved dynamically and stored in system state. "
                    "Use blueprint_context_text / blueprint_results from state for architecture generation."
                ),
            }

        except Exception as error:
            logger.exception("[BLUEPRINTS] Search failed: %s", error)

            if tool_context is not None:
                try:
                    store_in_state(
                        key="blueprint_search_done",
                        value=False,
                        confirmed=True,
                        tool_context=tool_context,
                    )

                    store_in_state(
                        key="blueprint_search_error",
                        value=str(error),
                        confirmed=True,
                        tool_context=tool_context,
                    )
                except Exception:
                    pass

            return {
                "status": "error",
                "total_found": 0,
                "top_match": None,
                "message": str(error),
            }


# ----------------------------------------------------------------------
# Lazy singleton wrapper
# ----------------------------------------------------------------------
_REPO: Optional[BlueprintRepository] = None


def get_blueprint_repository() -> BlueprintRepository:
    """
    Lazy initialization avoids creating Vertex/Chroma objects at module import time.
    This is safer for ADK startup and unit testing.
    """
    global _REPO

    if _REPO is None:
        _REPO = BlueprintRepository()

    return _REPO


def search_blueprint_bundle(
    query_text: str,
    n_results_overall: int = 8,
    n_per_filter: int = 3,
    max_total: int = 20,
    metadata_filters: Optional[Dict[str, Any]] = None,
    tool_context=None,
) -> Dict[str, Any]:
    """
    ADK FunctionTool entrypoint.

    Keep this as a standalone function rather than binding a method directly.
    This avoids repository initialization during import.
    """
    repo = get_blueprint_repository()

    return repo.search_blueprint_bundle(
        query_text=query_text,
        n_results_overall=n_results_overall,
        n_per_filter=n_per_filter,
        max_total=max_total,
        metadata_filters=metadata_filters,
        tool_context=tool_context,
    )


search_blueprint_bundle_tool = FunctionTool(func=search_blueprint_bundle)