# import os
# import chromadb
# import pandas as pd
# from chromadb.utils import embedding_functions
# from docx import Document
# import warnings
# warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
# from chromadb.utils.embedding_functions import GoogleVertexEmbeddingFunction
# # from agent.config_load import GetConf
# from agent.config_load import GetConf

# BLUEPRINT_AREAS = {
#     "security": "standard",
#     "secrets": "pattern",
#     "ingestion": "pattern",
#     "migration": "strategy",
#     "deployment_strategy": "strategy",
#     "cost": "nfr",
#     "nfr": "nfr",
#     "onprem": "deployment",
#     "gcp": "cloud",
#     "shared_services": "service",
#     "template": "template"
# }

# config = GetConf.load_configs()

# class BlueprintIngestor:
#     def __init__(self, db_path="./chroma_db", collection_name="architecture_standards"):
#         self.client = chromadb.PersistentClient(path=db_path)
# # 1. DELETE the old collection if it exists to resolve the conflict
#         try:
#             self.client.delete_collection(name=collection_name)
#             print(f"Deleted existing collection: {collection_name}")
#         except Exception:
#             # Collection didn't exist, which is fine
#             pass
                
#         # Initialize Vertex AI embeddings
#         # vertex_ef = GoogleVertexEmbeddingFunction(
#         #     project_id="vf-uk-churchill-alpha-lab",  # Replace with your GCP project ID
#         #     region="europe-west2",  # Replace with your GCP region
#         #     model_name="text-embedding-004" # Standard GCP embedding model
#         # )
#         vertex_ef = GoogleVertexEmbeddingFunction(
#             project_id=config.PROJECT_ID,  # Replace with your GCP project ID
#             region=config.REGION,  # Replace with your GCP region
#             model_name=config.embedding_model_name # Standard GCP embedding model
#         )        

#         self.collection = self.client.get_or_create_collection(
#             name=collection_name,
#             embedding_function=vertex_ef
#         )

#     def _extract_docx(self, file_path):
#         doc = Document(file_path)
#         chunks = [p.text for p in doc.paragraphs if p.text.strip()]
#         return "\n".join(chunks)

#     def _extract_xlsx(self, file_path):
#         xls = pd.ExcelFile(file_path, engine="openpyxl")
#         text = []

#         for sheet in xls.sheet_names:
#             if "template" in sheet.lower() or "architecture" in sheet.lower():
#                 df = pd.read_excel(xls, sheet_name=sheet)
#                 text.append(f"--- SHEET: {sheet} ---")
#                 text.append(df.astype(str).to_string(index=False))

#         return "\n".join(text) if text else ""

#     def load_blueprints(self, source_path):
#         for root, _, files in os.walk(source_path):

#             area = os.path.basename(root)
#             artifact_type = BLUEPRINT_AREAS.get(area, "general")

#             for file in files:
#                 full_path = os.path.join(root, file)
#                 ext = os.path.splitext(file)[1].lower()

#                 if ext not in {".docx", ".xlsx", ".json"}:
#                     continue

#                 try:
#                     if ext == ".docx":
#                         content = self._extract_docx(full_path)
#                     elif ext == ".xlsx":
#                         content = self._extract_xlsx(full_path)
#                     else:
#                         with open(full_path, "r") as f:
#                             content = f.read()

#                     if not content.strip():
#                         continue

#                     self.collection.upsert(
#                         documents=[content],
#                         ids=[f"{area}_{file}"],
#                         metadatas=[{
#                             "area": area,
#                             "artifact_type": artifact_type,
#                             "doc_type": "template" if area == "template" else "blueprint",
#                             "file": file,
#                             "source": "blueprints"
#                         }]
#                     )

#                     print(f"✅ Indexed [{area.upper()}] → {file}")

#                 except Exception as e:
#                     print(f"❌ Failed {file}: {e}")


# if __name__ == "__main__":
#     ingestor = BlueprintIngestor()
#     ingestor.load_blueprints("./agent/blueprints")

#     # Future GCS execution
#     # ingestor.load_blueprints("gs://your-org-metadata-bucket/blueprints")

import os
import json
import hashlib
import argparse
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sys
import chromadb
import pandas as pd
from docx import Document
from chromadb.utils.embedding_functions import GoogleVertexEmbeddingFunction

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config_load import GetConf

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")





config = GetConf.load_configs()



class BlueprintIngestor:
    """
    Fully generic ChromaDB ingestor.

    Design principles:
    - No hardcoded blueprint areas.
    - No hardcoded cloud names.
    - No hardcoded HLD sections.
    - No hardcoded folder classifications.
    - No service-specific keyword mapping.
    - Metadata is derived from:
        1. JSON/JSONL metadata
        2. JSON payload fields
        3. folder path
        4. file name
        5. file extension
    """

    def __init__(
        self,
        db_path: str,
        collection_name: str,
        project_id: str,
        region: str,
        model_name: str,
        reset_collection: bool = False,
        batch_size: int = 50,
        chunk_size: int = 12000,
        chunk_overlap: int = 800,
    ):
        self.db_path = db_path
        self.collection_name = collection_name
        self.project_id = project_id
        self.region = region
        self.model_name = model_name
        self.batch_size = batch_size
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.client = chromadb.PersistentClient(path=db_path)

        if reset_collection:
            self._delete_collection_if_exists(collection_name)

        embedding_function = GoogleVertexEmbeddingFunction(
            project_id=project_id,
            region=region,
            model_name=model_name,
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
        )

    # ------------------------------------------------------------------
    # Collection handling
    # ------------------------------------------------------------------
    def _delete_collection_if_exists(self, collection_name: str) -> None:
        try:
            self.client.delete_collection(name=collection_name)
            print(f"Deleted existing collection: {collection_name}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _safe_id(self, value: str) -> str:
        value = str(value).replace("\\", "/")
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]

        cleaned = []
        for char in value:
            if char.isalnum() or char in {"_", "-"}:
                cleaned.append(char)
            else:
                cleaned.append("_")

        cleaned_value = "".join(cleaned).strip("_")
        cleaned_value = cleaned_value[:140] if cleaned_value else "document"

        return f"{cleaned_value}_{digest}"

    def _to_scalar_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Chroma metadata values must be scalar.
        Lists and dicts are converted to JSON strings.
        """
        scalar = {}

        for key, value in metadata.items():
            if value is None:
                continue

            key = str(key)

            if isinstance(value, (str, int, float, bool)):
                scalar[key] = value
            elif isinstance(value, (list, tuple, set)):
                scalar[key] = json.dumps(list(value), ensure_ascii=False)
            elif isinstance(value, dict):
                scalar[key] = json.dumps(value, ensure_ascii=False)
            else:
                scalar[key] = str(value)

        return scalar

    def _tokenise_path(self, text: str) -> List[str]:
        """
        Generic token extraction from path/file names.
        No domain-specific keyword mapping.
        """
        text = str(text).replace("\\", "/")
        separators = ["/", "_", "-", ".", " "]

        for sep in separators:
            text = text.replace(sep, " ")

        tokens = []
        for token in text.split():
            token = token.strip().lower()
            if token:
                tokens.append(token)

        return sorted(set(tokens))

    # ------------------------------------------------------------------
    # Metadata derivation — generic only
    # ------------------------------------------------------------------
    def _derive_path_metadata(
        self,
        file_path: Path,
        source_path: Path,
    ) -> Dict[str, Any]:
        """
        Derive metadata only from actual path structure.
        No interpretation, no hardcoded folder meaning.
        """
        try:
            relative_path = file_path.relative_to(source_path)
        except Exception:
            relative_path = file_path

        parts = relative_path.parts
        folder_parts = list(parts[:-1])
        file_name = file_path.name

        metadata = {
            "relative_path": str(relative_path).replace("\\", "/"),
            "file_name": file_name,
            "file_stem": file_path.stem,
            "extension": file_path.suffix.lower(),
            "folder_depth": len(folder_parts),
            "folder_path": "/".join(folder_parts) if folder_parts else "",
            "path_tokens": self._tokenise_path(str(relative_path)),
        }

        # Add dynamic folder levels without naming assumptions.
        for index, folder in enumerate(folder_parts):
            metadata[f"folder_level_{index}"] = folder

        # Convenience fields only from position, not hardcoded names.
        metadata["top_folder"] = folder_parts[0] if len(folder_parts) >= 1 else ""
        metadata["parent_folder"] = folder_parts[-1] if folder_parts else ""

        return metadata

    def _derive_payload_metadata(self, payload: Any) -> Dict[str, Any]:
        """
        Pull useful metadata from any JSON object dynamically.

        This does not assume fixed field names, but safely extracts:
        - scalar top-level values
        - short lists
        - common identifier-like fields if present
        """
        metadata = {}

        if not isinstance(payload, dict):
            return metadata

        for key, value in payload.items():
            if value is None:
                continue

            # Keep scalar top-level fields.
            if isinstance(value, (str, int, float, bool)):
                metadata[f"json_{key}"] = value

            # Keep short lists of scalar values.
            elif isinstance(value, list):
                if len(value) <= 50 and all(
                    isinstance(item, (str, int, float, bool)) for item in value
                ):
                    metadata[f"json_{key}"] = value

            # For dicts/larger objects, only mark presence generically.
            elif isinstance(value, dict):
                metadata[f"has_json_{key}"] = True

        # Preserve common metadata keys without requiring them.
        for key in [
            "id",
            "name",
            "title",
            "type",
            "domain",
            "cloud",
            "category",
            "layer",
            "version",
            "schema_version",
            "blueprint_id",
            "pattern_id",
            "source_file",
            "priority",
        ]:
            if key in payload:
                metadata[key] = payload[key]

        return metadata

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def _extract_docx(self, file_path: Path) -> str:
        document = Document(str(file_path))
        paragraphs = []

        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if text:
                paragraphs.append(text)

        return "\n".join(paragraphs)

    def _extract_xlsx(self, file_path: Path) -> str:
        workbook = pd.ExcelFile(str(file_path), engine="openpyxl")
        output = []

        for sheet_name in workbook.sheet_names:
            try:
                dataframe = pd.read_excel(
                    workbook,
                    sheet_name=sheet_name,
                    engine="openpyxl",
                )

                if dataframe.empty:
                    continue

                output.append(f"--- SHEET: {sheet_name} ---")
                output.append(dataframe.astype(str).to_string(index=False))

            except Exception as error:
                print(f"Failed reading sheet {sheet_name} in {file_path}: {error}")

        return "\n".join(output)

    def _extract_json(self, file_path: Path) -> Tuple[str, Any]:
        with open(file_path, "r", encoding="utf-8") as file:
            payload = json.load(file)

        text = self._json_to_text(payload)
        return text, payload

    def _json_to_text(self, payload: Any) -> str:
        """
        Convert any JSON into searchable text.
        Generic approach:
        - Flatten important textual content recursively.
        - Append full pretty JSON.
        """
        flattened = []

        def walk(value: Any, prefix: str = ""):
            if isinstance(value, dict):
                for key, item in value.items():
                    next_prefix = f"{prefix}.{key}" if prefix else str(key)
                    walk(item, next_prefix)

            elif isinstance(value, list):
                for index, item in enumerate(value):
                    next_prefix = f"{prefix}[{index}]"
                    walk(item, next_prefix)

            else:
                if value is not None:
                    flattened.append(f"{prefix}: {value}")

        walk(payload)

        pretty_json = json.dumps(payload, indent=2, ensure_ascii=False)

        return "\n".join(flattened + ["", "--- FULL JSON ---", pretty_json])

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------
    def _chunk_text(self, text: str) -> List[str]:
        text = text.strip()

        if not text:
            return []

        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end].strip()

            if chunk:
                chunks.append(chunk)

            if end >= len(text):
                break

            start = max(0, end - self.chunk_overlap)

        return chunks

    # ------------------------------------------------------------------
    # JSONL support
    # ------------------------------------------------------------------
    def _discover_jsonl_files(self, source_path: Path) -> List[Path]:
        """
        Generic JSONL discovery.
        No hardcoded file name required.
        All JSONL files are discovered dynamically.
        """
        return sorted(source_path.rglob("*.jsonl"))

    def _read_jsonl(self, jsonl_path: Path) -> List[Dict[str, Any]]:
        records = []

        with open(jsonl_path, "r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()

                if not line:
                    continue

                try:
                    records.append(json.loads(line))
                except Exception as error:
                    print(f"Skipping invalid JSONL line {jsonl_path}:{line_number}: {error}")

        return records

    def _normalise_jsonl_record(
        self,
        record: Dict[str, Any],
        record_index: int,
        jsonl_path: Path,
        source_path: Path,
    ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """
        Accepts any reasonable JSONL shape.

        Supports these possible text fields:
        - document
        - text
        - content
        - page_content

        If none exists, converts the full record to JSON text.
        """
        raw_id = (
            record.get("id")
            or record.get("document_id")
            or record.get("key")
            or f"{jsonl_path}:{record_index}"
        )

        document = (
            record.get("document")
            or record.get("text")
            or record.get("content")
            or record.get("page_content")
        )

        if document is None:
            document = json.dumps(record, ensure_ascii=False)

        document = str(document).strip()

        if not document:
            return None

        path_metadata = self._derive_path_metadata(jsonl_path, source_path)

        record_metadata = {}
        if isinstance(record.get("metadata"), dict):
            record_metadata.update(record["metadata"])

        payload = record.get("payload")
        payload_metadata = self._derive_payload_metadata(payload)

        metadata = {
            **path_metadata,
            **record_metadata,
            **payload_metadata,
            "source_path": str(source_path),
            "ingestion_mode": "jsonl",
            "record_index": record_index,
        }

        doc_id = self._safe_id(str(raw_id))

        return doc_id, document, self._to_scalar_metadata(metadata)

    def _ingest_jsonl_file(self, jsonl_path: Path, source_path: Path) -> int:
        records = self._read_jsonl(jsonl_path)

        ids = []
        documents = []
        metadatas = []

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue

            normalised = self._normalise_jsonl_record(
                record=record,
                record_index=index,
                jsonl_path=jsonl_path,
                source_path=source_path,
            )

            if not normalised:
                continue

            doc_id, document, metadata = normalised

            ids.append(doc_id)
            documents.append(document)
            metadatas.append(metadata)

        self._upsert_batches(ids, documents, metadatas)

        print(f"Indexed JSONL file: {jsonl_path} | records: {len(ids)}")
        return len(ids)

    # ------------------------------------------------------------------
    # Regular file ingestion
    # ------------------------------------------------------------------
    def _is_supported_file(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in {".json", ".docx", ".xlsx"}

    def _ingest_regular_file(self, file_path: Path, source_path: Path) -> int:
        extension = file_path.suffix.lower()

        payload = None

        if extension == ".json":
            content, payload = self._extract_json(file_path)
        elif extension == ".docx":
            content = self._extract_docx(file_path)
        elif extension == ".xlsx":
            content = self._extract_xlsx(file_path)
        else:
            return 0

        if not content.strip():
            return 0

        path_metadata = self._derive_path_metadata(file_path, source_path)
        payload_metadata = self._derive_payload_metadata(payload)

        base_metadata = {
            **path_metadata,
            **payload_metadata,
            "source_path": str(source_path),
            "ingestion_mode": "file",
        }

        chunks = self._chunk_text(content)

        ids = []
        documents = []
        metadatas = []

        for chunk_index, chunk in enumerate(chunks):
            raw_id = f"{base_metadata.get('relative_path')}::chunk::{chunk_index}"

            metadata = {
                **base_metadata,
                "chunk_index": chunk_index,
                "chunk_count": len(chunks),
            }

            ids.append(self._safe_id(raw_id))
            documents.append(chunk)
            metadatas.append(self._to_scalar_metadata(metadata))

        self._upsert_batches(ids, documents, metadatas)

        print(f"Indexed file: {file_path} | chunks: {len(ids)}")
        return len(ids)

    def _ingest_regular_files(self, source_path: Path) -> int:
        total = 0

        for file_path in sorted(source_path.rglob("*")):
            if not file_path.is_file():
                continue

            if not self._is_supported_file(file_path):
                continue

            try:
                total += self._ingest_regular_file(file_path, source_path)
            except Exception as error:
                print(f"Failed indexing file {file_path}: {error}")

        return total

    # ------------------------------------------------------------------
    # Batch upsert
    # ------------------------------------------------------------------
    def _upsert_batches(
        self,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        if not ids:
            return

        for start in range(0, len(ids), self.batch_size):
            end = start + self.batch_size

            self.collection.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

    # ------------------------------------------------------------------
    # Public ingestion method
    # ------------------------------------------------------------------
    def load_blueprints(
        self,
        source_path: str,
        prefer_jsonl: bool = True,
        also_index_files: bool = False,
    ) -> None:
        source = Path(source_path)

        if not source.exists():
            raise FileNotFoundError(f"Source path does not exist: {source}")

        print("=" * 90)
        print("Starting generic blueprint ingestion")
        print(f"Source path     : {source.resolve()}")
        print(f"Chroma DB path  : {self.db_path}")
        print(f"Collection      : {self.collection_name}")
        print(f"Embedding model : {self.model_name}")
        print("=" * 90)

        total = 0
        jsonl_files = []

        if prefer_jsonl:
            jsonl_files = self._discover_jsonl_files(source)

            if jsonl_files:
                print("JSONL files discovered:")
                for jsonl_file in jsonl_files:
                    print(f" - {jsonl_file}")

                for jsonl_file in jsonl_files:
                    total += self._ingest_jsonl_file(jsonl_file, source)

            else:
                print("No JSONL files found. Regular file indexing will be used.")

        if also_index_files or not jsonl_files:
            total += self._ingest_regular_files(source)

        print("=" * 90)
        print(f"Generic blueprint ingestion completed. Total indexed documents: {total}")
        print("=" * 90)

    # ------------------------------------------------------------------
    # Query helper
    # ------------------------------------------------------------------
    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        kwargs = {
            "query_texts": [query_text],
            "n_results": n_results,
        }

        if where:
            kwargs["where"] = where

        return self.collection.query(**kwargs)

    def test_query(
        self,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> None:
        results = self.query(
            query_text=query_text,
            n_results=n_results,
            where=where,
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0] if "distances" in results else []

        print(f"\nQuery: {query_text}")

        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            distance = distances[index] if index < len(distances) else None

            print("\n" + "-" * 90)
            print(f"Result #{index + 1}")

            if distance is not None:
                print(f"Distance: {distance}")

            print("Metadata:")
            print(json.dumps(metadata, indent=2, ensure_ascii=False))

            print("\nDocument preview:")
            print(document[:1000])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generic blueprint ingestor for ChromaDB"
    )

    parser.add_argument(
        "--source-path",
        # default=os.getenv("BLUEPRINT_SOURCE_PATH"),
        default="./agent/blueprints",
        help="Path to blueprint folder. Can also be set using BLUEPRINT_SOURCE_PATH.",
    )

    parser.add_argument(
        "--db-path",
        default=os.getenv("CHROMA_DB_PATH", "./chroma_db"),
        help="ChromaDB persistent path.",
    )

    parser.add_argument(
        "--collection-name",
        default=os.getenv("CHROMA_COLLECTION", "architecture_standards"),
        help="ChromaDB collection name.",
    )

    parser.add_argument(
        "--project-id",
        default=os.getenv("GOOGLE_CLOUD_PROJECT") or config.PROJECT_ID,
        help="GCP project ID for Vertex embeddings.",
    )

    parser.add_argument(
        "--region",
        # default=os.getenv("GOOGLE_CLOUD_REGION") or config.REGION,
        default="europe-west2",
        help="GCP region for Vertex embeddings.",
    )

    parser.add_argument(
        "--model-name",
        default=config.EMBEDDING_MODEL_NAME,
        help="Vertex embedding model name.",
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        default=os.getenv("RESET_CHROMA_COLLECTION", "false").lower() == "true",
        help="Delete and recreate the collection before indexing.",
    )

    parser.add_argument(
        "--prefer-jsonl",
        action="store_true",
        default=os.getenv("PREFER_JSONL", "true").lower() == "true",
        help="Prefer JSONL files if available.",
    )

    parser.add_argument(
        "--also-index-files",
        action="store_true",
        default=os.getenv("ALSO_INDEX_FILES", "false").lower() == "true",
        help="Also index regular files even when JSONL files are found.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("CHROMA_BATCH_SIZE", "50")),
        help="Batch size for ChromaDB upserts.",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=int(os.getenv("BLUEPRINT_CHUNK_SIZE", "12000")),
        help="Maximum characters per chunk for regular files.",
    )

    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=int(os.getenv("BLUEPRINT_CHUNK_OVERLAP", "800")),
        help="Character overlap between chunks.",
    )

    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    missing = []

    if not args.source_path:
        missing.append("source-path or BLUEPRINT_SOURCE_PATH")

    if not args.project_id:
        missing.append("project-id or GOOGLE_CLOUD_PROJECT/GCP_PROJECT_ID")

    if not args.region:
        missing.append("region or GOOGLE_CLOUD_REGION/GCP_REGION")

    if missing:
        raise ValueError(
            "Missing required configuration: " + ", ".join(missing)
        )

    if not Path(args.source_path).exists():
        raise FileNotFoundError(f"Blueprint source path not found: {args.source_path}")


if __name__ == "__main__":
    args = parse_args()
    validate_args(args)

    ingestor = BlueprintIngestor(
        db_path=args.db_path,
        collection_name=args.collection_name,
        project_id=args.project_id,
        region=args.region,
        model_name=args.model_name,
        reset_collection=args.reset,
        batch_size=args.batch_size,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    ingestor.load_blueprints(
        source_path=args.source_path,
        prefer_jsonl=args.prefer_jsonl,
        also_index_files=args.also_index_files,
    )

    if os.getenv("RUN_INGESTION_TESTS", "false").lower() == "true":
        query_text = os.getenv(
            "TEST_QUERY",
            "architecture blueprint security observability connectivity data ingestion"
        )
        ingestor.test_query(query_text, n_results=5)