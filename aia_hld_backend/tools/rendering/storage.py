# import logging
# from datetime import timedelta
# from pathlib import Path
# from typing import Dict, Optional
# from google.cloud import storage
# from google.auth import default
# from google.auth.credentials import Credentials
# logger=logging.getLogger(__name__)
# def upload_to_gcs(bucket_name: str, local_file_path: str, gcs_destination_path: str) -> str:
#     client=storage.Client(); blob=client.bucket(bucket_name).blob(gcs_destination_path); blob.upload_from_filename(local_file_path); return f'gs://{bucket_name}/{gcs_destination_path}'
# def can_sign_urls(creds: Credentials) -> bool: return hasattr(creds,'sign_bytes')
# def generate_signed_gcs_url(bucket_name: str, gcs_object_path: str, expires_minutes: int=30) -> Optional[str]:
#     try:
#         credentials,_=default()
#         if not can_sign_urls(credentials): logger.warning('Signed URL generation skipped: current credentials do not support signing.'); return None
#         blob=storage.Client(credentials=credentials).bucket(bucket_name).blob(gcs_object_path)
#         return blob.generate_signed_url(expiration=timedelta(minutes=expires_minutes),method='GET')
#     except Exception: logger.exception('Failed to generate signed GCS URL for %s/%s',bucket_name,gcs_object_path); return None
# def upload_outputs(bucket_name: str, project_folder: str, paths: Dict[str,str]) -> Dict[str,str]:
#     return {typ: upload_to_gcs(bucket_name,path,f'{project_folder}/{Path(path).name}') for typ,path in paths.items()}
# def generate_signed_urls(bucket_name: str, project_folder: str, paths: Dict[str,str]) -> Dict[str,Optional[str]]:
#     return {typ: generate_signed_gcs_url(bucket_name,f'{project_folder}/{Path(path).name}') for typ,path in paths.items()}

# import logging
# import re
# from datetime import timedelta
# from pathlib import Path
# from typing import Dict, Optional
# from urllib.parse import urlparse

# from google.auth import default
# from google.auth.credentials import Credentials
# from google.cloud import storage
# from google.api_core.exceptions import PreconditionFailed

# logger = logging.getLogger(__name__)


# _VERSION_RE_TEMPLATE = r"^{base}(?:_V(?P<version>\d+))?{suffix}$"


# def can_sign_urls(creds: Credentials) -> bool:
#     return hasattr(creds, "sign_bytes")


# def _split_gcs_path(gcs_uri: str) -> tuple[str, str]:
#     """
#     Converts gs://bucket/path/file.docx into bucket and object path.
#     """
#     if not gcs_uri.startswith("gs://"):
#         raise ValueError(f"Invalid GCS URI: {gcs_uri}")

#     parsed = urlparse(gcs_uri)
#     bucket_name = parsed.netloc
#     object_path = parsed.path.lstrip("/")

#     if not bucket_name or not object_path:
#         raise ValueError(f"Invalid GCS URI: {gcs_uri}")

#     return bucket_name, object_path


# def _get_next_versioned_gcs_path(
#     bucket: storage.Bucket,
#     desired_gcs_path: str,
# ) -> str:
#     """
#     Returns a safe destination path.

#     Example:
#         desired_gcs_path = project/HLD.docx

#         If no existing file:
#             project/HLD.docx

#         If project/HLD.docx exists:
#             project/HLD_V1.docx

#         If project/HLD.docx, project/HLD_V1.docx, project/HLD_V2.docx exist:
#             project/HLD_V3.docx
#     """
#     desired_path = Path(desired_gcs_path)

#     folder = desired_path.parent.as_posix()
#     file_name = desired_path.name
#     stem = desired_path.stem
#     suffix = desired_path.suffix

#     # GCS object prefix for listing possible matching files.
#     # Example: project/HLD
#     if folder == ".":
#         list_prefix = stem
#     else:
#         list_prefix = f"{folder}/{stem}"

#     escaped_base = re.escape(stem)
#     escaped_suffix = re.escape(suffix)

#     version_regex = re.compile(
#         _VERSION_RE_TEMPLATE.format(
#             base=escaped_base,
#             suffix=escaped_suffix,
#         )
#     )

#     max_version = -1
#     original_exists = False

#     logger.info(
#         "Checking existing GCS objects for versioning. bucket=%s prefix=%s",
#         bucket.name,
#         list_prefix,
#     )

#     for blob in bucket.list_blobs(prefix=list_prefix):
#         blob_path = Path(blob.name)

#         # Only compare files in the exact same folder.
#         blob_folder = blob_path.parent.as_posix()
#         if blob_folder == ".":
#             blob_folder = ""

#         expected_folder = "" if folder == "." else folder

#         if blob_folder != expected_folder:
#             continue

#         match = version_regex.match(blob_path.name)
#         if not match:
#             continue

#         version_value = match.group("version")

#         if version_value is None:
#             original_exists = True
#             max_version = max(max_version, 0)
#         else:
#             max_version = max(max_version, int(version_value))

#     # No original or versioned file found, use desired name as-is.
#     if not original_exists and max_version == -1:
#         logger.info("No existing file found. Using original GCS path: %s", desired_gcs_path)
#         return desired_gcs_path

#     next_version = max_version + 1

#     versioned_file_name = f"{stem}_V{next_version}{suffix}"

#     if folder == ".":
#         versioned_path = versioned_file_name
#     else:
#         versioned_path = f"{folder}/{versioned_file_name}"

#     logger.info(
#         "Existing file/version found. Using versioned GCS path: %s",
#         versioned_path,
#     )

#     return versioned_path


# def upload_to_gcs(
#     bucket_name: str,
#     local_file_path: str,
#     gcs_destination_path: str,
# ) -> str:
#     """
#     Uploads a file to GCS.

#     If the destination file already exists, uploads using next versioned filename.

#     Example:
#         report.docx
#         report_V1.docx
#         report_V2.docx
#     """
#     client = storage.Client()
#     bucket = client.bucket(bucket_name)

#     safe_destination_path = _get_next_versioned_gcs_path(
#         bucket=bucket,
#         desired_gcs_path=gcs_destination_path,
#     )

#     blob = bucket.blob(safe_destination_path)

#     try:
#         # if_generation_match=0 ensures we never overwrite an existing object.
#         blob.upload_from_filename(
#             local_file_path,
#             if_generation_match=0,
#         )

#         uploaded_uri = f"gs://{bucket_name}/{safe_destination_path}"

#         logger.info(
#             "Uploaded file to GCS. local=%s gcs=%s",
#             local_file_path,
#             uploaded_uri,
#         )

#         return uploaded_uri

#     except PreconditionFailed:
#         # This can happen if another process uploaded the same version between
#         # list_blobs and upload. Retry once by recalculating the next version.
#         logger.warning(
#             "GCS upload precondition failed because object already exists. "
#             "Retrying with next available version. bucket=%s path=%s",
#             bucket_name,
#             safe_destination_path,
#         )

#         safe_destination_path = _get_next_versioned_gcs_path(
#             bucket=bucket,
#             desired_gcs_path=gcs_destination_path,
#         )

#         blob = bucket.blob(safe_destination_path)

#         blob.upload_from_filename(
#             local_file_path,
#             if_generation_match=0,
#         )

#         uploaded_uri = f"gs://{bucket_name}/{safe_destination_path}"

#         logger.info(
#             "Uploaded file to GCS after retry. local=%s gcs=%s",
#             local_file_path,
#             uploaded_uri,
#         )

#         return uploaded_uri


# def generate_signed_gcs_url(
#     bucket_name: str,
#     gcs_object_path: str,
#     expires_minutes: int = 30,
# ) -> Optional[str]:
#     try:
#         credentials, _ = default()

#         if not can_sign_urls(credentials):
#             logger.warning(
#                 "Signed URL generation skipped: current credentials do not support signing."
#             )
#             return None

#         blob = storage.Client(credentials=credentials).bucket(bucket_name).blob(
#             gcs_object_path
#         )

#         return blob.generate_signed_url(
#             expiration=timedelta(minutes=expires_minutes),
#             method="GET",
#         )

#     except Exception:
#         logger.exception(
#             "Failed to generate signed GCS URL for %s/%s",
#             bucket_name,
#             gcs_object_path,
#         )
#         return None


# def generate_signed_gcs_url_from_uri(
#     gcs_uri: str,
#     expires_minutes: int = 30,
# ) -> Optional[str]:
#     """
#     Generates signed URL directly from gs:// URI.

#     This is useful because upload_to_gcs may rename the uploaded file to _V1/_V2.
#     """
#     try:
#         bucket_name, object_path = _split_gcs_path(gcs_uri)

#         return generate_signed_gcs_url(
#             bucket_name=bucket_name,
#             gcs_object_path=object_path,
#             expires_minutes=expires_minutes,
#         )

#     except Exception:
#         logger.exception(
#             "Failed to generate signed URL from GCS URI: %s",
#             gcs_uri,
#         )
#         return None


# def upload_outputs(
#     bucket_name: str,
#     project_folder: str,
#     paths: Dict[str, str],
# ) -> Dict[str, str]:
#     """
#     Uploads all output files to GCS.

#     Returns:
#         {
#             "docx": "gs://bucket/project/file.docx",
#             "pdf": "gs://bucket/project/file_V1.pdf"
#         }
#     """
#     uploaded_outputs: Dict[str, str] = {}

#     for typ, path in paths.items():
#         local_path = Path(path)

#         gcs_destination_path = f"{project_folder.rstrip('/')}/{local_path.name}"

#         uploaded_outputs[typ] = upload_to_gcs(
#             bucket_name=bucket_name,
#             local_file_path=str(local_path),
#             gcs_destination_path=gcs_destination_path,
#         )

#     return uploaded_outputs


# def generate_signed_urls_from_uploaded_outputs(
#     uploaded_outputs: Dict[str, str],
#     expires_minutes: int = 30,
# ) -> Dict[str, Optional[str]]:
#     """
#     Generates signed URLs from uploaded gs:// paths.

#     Recommended to use this after upload_outputs(), because the final uploaded
#     filename may be versioned dynamically.
#     """
#     signed_urls: Dict[str, Optional[str]] = {}

#     for typ, gcs_uri in uploaded_outputs.items():
#         signed_urls[typ] = generate_signed_gcs_url_from_uri(
#             gcs_uri=gcs_uri,
#             expires_minutes=expires_minutes,
#         )

#     return signed_urls


# def generate_signed_urls(
#     bucket_name: str,
#     project_folder: str,
#     paths: Dict[str, str],
# ) -> Dict[str, Optional[str]]:
#     """
#     Existing method kept for backward compatibility.

#     Note:
#         This method assumes files are uploaded with the original local filename.
#         If upload_to_gcs created _V1/_V2 files, prefer using:

#             uploaded_outputs = upload_outputs(...)
#             signed_urls = generate_signed_urls_from_uploaded_outputs(uploaded_outputs)
#     """
#     signed_urls: Dict[str, Optional[str]] = {}

#     for typ, path in paths.items():
#         object_path = f"{project_folder.rstrip('/')}/{Path(path).name}"

#         signed_urls[typ] = generate_signed_gcs_url(
#             bucket_name=bucket_name,
#             gcs_object_path=object_path,
#         )

#     return signed_urls


# from __future__ import annotations

# import logging
# import re
# from datetime import timedelta
# from pathlib import Path
# from typing import Dict, Optional
# from urllib.parse import urlparse

# from google.api_core.exceptions import PreconditionFailed
# from google.auth import default
# from google.auth.credentials import Credentials
# from google.cloud import storage

# logger = logging.getLogger(__name__)

# _VERSION_RE_TEMPLATE = r"^{base}(?:_V(?P<version>\d+))?{suffix}$"


# def can_sign_urls(creds: Credentials) -> bool:
#     """Return True if the active credentials can cryptographically sign URLs."""
#     return hasattr(creds, "sign_bytes")


# def _split_gcs_path(gcs_uri: str) -> tuple[str, str]:
#     """Convert gs://bucket/path/file.ext into bucket name and object path."""
#     if not gcs_uri.startswith("gs://"):
#         raise ValueError(f"Invalid GCS URI: {gcs_uri}")

#     parsed = urlparse(gcs_uri)
#     bucket_name = parsed.netloc
#     object_path = parsed.path.lstrip("/")

#     if not bucket_name or not object_path:
#         raise ValueError(f"Invalid GCS URI: {gcs_uri}")

#     return bucket_name, object_path


# def _safe_project_folder(project_folder: str) -> str:
#     """Normalize a GCS folder prefix without leading/trailing slashes."""
#     folder = str(project_folder or "hld").strip().strip("/")
#     folder = re.sub(r"/+", "/", folder)
#     return folder or "hld"


# def _get_next_versioned_gcs_path(
#     bucket: storage.Bucket,
#     desired_gcs_path: str,
# ) -> str:
#     """
#     Return a safe non-overwriting destination path.

#     Example:
#         desired_gcs_path = project/HLD.docx

#         If no existing file:
#             project/HLD.docx

#         If project/HLD.docx exists:
#             project/HLD_V1.docx

#         If project/HLD.docx, project/HLD_V1.docx, project/HLD_V2.docx exist:
#             project/HLD_V3.docx
#     """
#     desired_path = Path(desired_gcs_path)

#     folder = desired_path.parent.as_posix()
#     file_name = desired_path.name
#     stem = desired_path.stem
#     suffix = desired_path.suffix

#     if folder == ".":
#         list_prefix = stem
#     else:
#         list_prefix = f"{folder}/{stem}"

#     version_regex = re.compile(
#         _VERSION_RE_TEMPLATE.format(
#             base=re.escape(stem),
#             suffix=re.escape(suffix),
#         )
#     )

#     max_version = -1
#     original_exists = False

#     logger.info(
#         "Checking existing GCS objects for versioning. bucket=%s prefix=%s file=%s",
#         bucket.name,
#         list_prefix,
#         file_name,
#     )

#     expected_folder = "" if folder == "." else folder

#     for blob in bucket.list_blobs(prefix=list_prefix):
#         blob_path = Path(blob.name)
#         blob_folder = blob_path.parent.as_posix()
#         if blob_folder == ".":
#             blob_folder = ""

#         if blob_folder != expected_folder:
#             continue

#         match = version_regex.match(blob_path.name)
#         if not match:
#             continue

#         version_value = match.group("version")

#         if version_value is None:
#             original_exists = True
#             max_version = max(max_version, 0)
#         else:
#             max_version = max(max_version, int(version_value))

#     if not original_exists and max_version == -1:
#         logger.info("No existing file found. Using original GCS path: %s", desired_gcs_path)
#         return desired_gcs_path

#     next_version = max_version + 1
#     versioned_file_name = f"{stem}_V{next_version}{suffix}"

#     if folder == ".":
#         versioned_path = versioned_file_name
#     else:
#         versioned_path = f"{folder}/{versioned_file_name}"

#     logger.info("Existing file/version found. Using versioned GCS path: %s", versioned_path)
#     return versioned_path


# def upload_to_gcs(
#     bucket_name: str,
#     local_file_path: str,
#     gcs_destination_path: str,
# ) -> str:
#     """
#     Upload a local file to GCS without overwriting existing objects.

#     If the destination already exists, a version suffix is added automatically:
#         report.pdf -> report_V1.pdf -> report_V2.pdf
#     """
#     local_path = Path(local_file_path)
#     if not local_path.exists() or not local_path.is_file():
#         raise FileNotFoundError(f"Local file does not exist or is not a file: {local_file_path}")

#     client = storage.Client()
#     bucket = client.bucket(bucket_name)

#     safe_destination_path = _get_next_versioned_gcs_path(
#         bucket=bucket,
#         desired_gcs_path=gcs_destination_path,
#     )

#     blob = bucket.blob(safe_destination_path)

#     try:
#         blob.upload_from_filename(str(local_path), if_generation_match=0)
#         uploaded_uri = f"gs://{bucket_name}/{safe_destination_path}"
#         logger.info("Uploaded file to GCS. local=%s gcs=%s", local_path, uploaded_uri)
#         return uploaded_uri

#     except PreconditionFailed:
#         # Race condition protection: another process may have uploaded the same
#         # version between list_blobs and upload. Recalculate and retry once.
#         logger.warning(
#             "GCS upload precondition failed because object already exists. "
#             "Retrying with next available version. bucket=%s path=%s",
#             bucket_name,
#             safe_destination_path,
#         )

#         safe_destination_path = _get_next_versioned_gcs_path(
#             bucket=bucket,
#             desired_gcs_path=gcs_destination_path,
#         )

#         blob = bucket.blob(safe_destination_path)
#         blob.upload_from_filename(str(local_path), if_generation_match=0)

#         uploaded_uri = f"gs://{bucket_name}/{safe_destination_path}"
#         logger.info("Uploaded file to GCS after retry. local=%s gcs=%s", local_path, uploaded_uri)
#         return uploaded_uri


# def generate_signed_gcs_url(
#     bucket_name: str,
#     gcs_object_path: str,
#     expires_minutes: int = 30,
# ) -> Optional[str]:
#     """Generate a signed GET URL for an object path inside a GCS bucket."""
#     try:
#         credentials, _ = default()

#         if not can_sign_urls(credentials):
#             logger.warning(
#                 "Signed URL generation skipped: current credentials do not support signing. "
#                 "bucket=%s object=%s",
#                 bucket_name,
#                 gcs_object_path,
#             )
#             return None

#         blob = storage.Client(credentials=credentials).bucket(bucket_name).blob(gcs_object_path)

#         return blob.generate_signed_url(
#             expiration=timedelta(minutes=expires_minutes),
#             method="GET",
#         )

#     except Exception:
#         logger.exception("Failed to generate signed GCS URL for %s/%s", bucket_name, gcs_object_path)
#         return None


# def generate_signed_gcs_url_from_uri(
#     gcs_uri: str,
#     expires_minutes: int = 30,
# ) -> Optional[str]:
#     """
#     Generate a signed URL directly from a gs:// URI.

#     This is important because upload_to_gcs may rename the final uploaded file
#     to _V1/_V2/etc. Signing must use the actual uploaded URI, not the original
#     intended filename.
#     """
#     try:
#         bucket_name, object_path = _split_gcs_path(gcs_uri)
#         return generate_signed_gcs_url(
#             bucket_name=bucket_name,
#             gcs_object_path=object_path,
#             expires_minutes=expires_minutes,
#         )
#     except Exception:
#         logger.exception("Failed to generate signed URL from GCS URI: %s", gcs_uri)
#         return None


# def upload_outputs(
#     bucket_name: str,
#     project_folder: str,
#     paths: Dict[str, str],
# ) -> Dict[str, str]:
#     """
#     Upload all output files to GCS.

#     This method intentionally supports dynamic artifact keys, including:
#         pdf, docx, md, html,
#         diagram_*_dot, diagram_*_svg, diagram_*_png, diagram_*_drawio

#     Returns actual uploaded gs:// URIs. These may include _V1/_V2 suffixes.
#     """
#     uploaded_outputs: Dict[str, str] = {}
#     folder = _safe_project_folder(project_folder)

#     for typ, path in paths.items():
#         if not path:
#             logger.debug("Skipping empty output path for key=%s", typ)
#             continue

#         local_path = Path(path)
#         if not local_path.exists() or not local_path.is_file():
#             logger.warning("Skipping missing/non-file output. key=%s path=%s", typ, path)
#             continue

#         gcs_destination_path = f"{folder}/{local_path.name}"

#         uploaded_outputs[typ] = upload_to_gcs(
#             bucket_name=bucket_name,
#             local_file_path=str(local_path),
#             gcs_destination_path=gcs_destination_path,
#         )

#     return uploaded_outputs


# def generate_signed_urls_from_uploaded_outputs(
#     uploaded_outputs: Dict[str, str],
#     expires_minutes: int = 30,
# ) -> Dict[str, Optional[str]]:
#     """
#     Generate signed URLs from actual uploaded gs:// paths.

#     Recommended after upload_outputs(), because the final uploaded filename may
#     be versioned dynamically by upload_to_gcs().
#     """
#     signed_urls: Dict[str, Optional[str]] = {}

#     for typ, gcs_uri in uploaded_outputs.items():
#         signed_urls[typ] = generate_signed_gcs_url_from_uri(
#             gcs_uri=gcs_uri,
#             expires_minutes=expires_minutes,
#         )

#     return signed_urls


# def generate_signed_urls(
#     bucket_name: str,
#     project_folder: str,
#     paths: Dict[str, str],
#     uploaded_outputs: Optional[Dict[str, str]] = None,
# ) -> Dict[str, Optional[str]]:
#     """
#     Generate signed URLs for outputs.

#     Preferred usage:
#         uploaded_outputs = upload_outputs(...)
#         signed_urls = generate_signed_urls(..., uploaded_outputs=uploaded_outputs)

#     Backward-compatible usage:
#         signed_urls = generate_signed_urls(bucket, folder, paths)

#     If uploaded_outputs is provided, signed URLs are generated from actual
#     uploaded gs:// URIs. This correctly handles _V1/_V2 versioned uploads.
#     Without uploaded_outputs, this function signs the original intended object
#     names based on local filenames.
#     """
#     if uploaded_outputs is not None:
#         return generate_signed_urls_from_uploaded_outputs(uploaded_outputs)

#     signed_urls: Dict[str, Optional[str]] = {}
#     folder = _safe_project_folder(project_folder)

#     for typ, path in paths.items():
#         if not path:
#             signed_urls[typ] = None
#             continue

#         object_path = f"{folder}/{Path(path).name}"
#         signed_urls[typ] = generate_signed_gcs_url(
#             bucket_name=bucket_name,
#             gcs_object_path=object_path,
#         )

#     return signed_urls

from __future__ import annotations

"""
storage.py

GCS upload and signed URL helpers for generated HLD artefacts.

Responsibilities
----------------
1. Upload generated files to Google Cloud Storage without overwriting existing
   objects.
2. Apply automatic version suffixes when destination objects already exist:
      file.pdf -> file_V1.pdf -> file_V2.pdf
3. Generate signed URLs for the actual uploaded object names.
4. Support dynamic artefact keys generically, including diagram assets:
      pdf, docx, md, html,
      diagram_*_dot, diagram_*_svg, diagram_*_png,
      diagram_*_drawio, diagram_*_vsdx

Design notes
------------
- This module does not know or care which renderer produced a file.
- This module does not hardcode service names, section names, or diagram names.
- Upload and signing are intentionally decoupled:
      upload_outputs(...) -> gs:// URIs
      generate_signed_urls(..., uploaded_outputs=...) -> signed URLs
- If upload_to_gcs(...) versions/renames an object, signed URLs are generated
  from the actual uploaded gs:// URI, not from the originally intended name.
"""

import logging
import mimetypes
import re
from datetime import timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse

from google.api_core.exceptions import PreconditionFailed
from google.auth import default
from google.auth.credentials import Credentials
from google.cloud import storage

logger = logging.getLogger(__name__)

_VERSION_RE_TEMPLATE = r"^{base}(?:_V(?P<version>\d+))?{suffix}$"
DEFAULT_SIGNED_URL_EXPIRY_MINUTES = 30


# =============================================================================
# Credential/signing helpers
# =============================================================================
def can_sign_urls(creds: Credentials) -> bool:
    """Return True if the active credentials can cryptographically sign URLs."""
    return hasattr(creds, "sign_bytes")


def _get_storage_client(credentials: Optional[Credentials] = None) -> storage.Client:
    """Create a storage client. Kept separate for easy testing/mocking."""
    return storage.Client(credentials=credentials) if credentials else storage.Client()


# =============================================================================
# Path helpers
# =============================================================================
def _split_gcs_path(gcs_uri: str) -> Tuple[str, str]:
    """Convert gs://bucket/path/file.ext into bucket name and object path."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")

    parsed = urlparse(gcs_uri)
    bucket_name = parsed.netloc
    object_path = parsed.path.lstrip("/")

    if not bucket_name or not object_path:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")

    return bucket_name, object_path


def _safe_project_folder(project_folder: str) -> str:
    """Normalize a GCS folder prefix without leading/trailing slashes."""
    folder = str(project_folder or "hld").strip().strip("/")
    folder = re.sub(r"/+", "/", folder)
    return folder or "hld"


def _safe_local_path(path: str) -> Path:
    """Validate and return a local file path."""
    local_path = Path(path)
    if not local_path.exists() or not local_path.is_file():
        raise FileNotFoundError(f"Local file does not exist or is not a file: {path}")
    return local_path


def _object_name_for_local_file(project_folder: str, local_file_path: str) -> str:
    """Build the intended object path for a local artefact."""
    folder = _safe_project_folder(project_folder)
    local_path = Path(local_file_path)
    return f"{folder}/{local_path.name}"


def _content_type_for_file(path: Path) -> Optional[str]:
    """Best-effort MIME type detection for uploaded artefacts."""
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type


# =============================================================================
# GCS versioning helpers
# =============================================================================
def _get_next_versioned_gcs_path(
    bucket: storage.Bucket,
    desired_gcs_path: str,
) -> str:
    """
    Return a safe non-overwriting destination path.

    Example:
        desired_gcs_path = project/HLD.docx

        If no existing file:
            project/HLD.docx

        If project/HLD.docx exists:
            project/HLD_V1.docx

        If project/HLD.docx, project/HLD_V1.docx, project/HLD_V2.docx exist:
            project/HLD_V3.docx
    """
    desired_path = Path(desired_gcs_path)

    folder = desired_path.parent.as_posix()
    file_name = desired_path.name
    stem = desired_path.stem
    suffix = desired_path.suffix

    list_prefix = stem if folder == "." else f"{folder}/{stem}"

    version_regex = re.compile(
        _VERSION_RE_TEMPLATE.format(
            base=re.escape(stem),
            suffix=re.escape(suffix),
        )
    )

    max_version = -1
    original_exists = False

    logger.info(
        "Checking existing GCS objects for versioning. bucket=%s prefix=%s file=%s",
        bucket.name,
        list_prefix,
        file_name,
    )

    expected_folder = "" if folder == "." else folder

    for blob in bucket.list_blobs(prefix=list_prefix):
        blob_path = Path(blob.name)
        blob_folder = blob_path.parent.as_posix()
        if blob_folder == ".":
            blob_folder = ""

        if blob_folder != expected_folder:
            continue

        match = version_regex.match(blob_path.name)
        if not match:
            continue

        version_value = match.group("version")

        if version_value is None:
            original_exists = True
            max_version = max(max_version, 0)
        else:
            max_version = max(max_version, int(version_value))

    if not original_exists and max_version == -1:
        logger.info("No existing file found. Using original GCS path: %s", desired_gcs_path)
        return desired_gcs_path

    next_version = max_version + 1
    versioned_file_name = f"{stem}_V{next_version}{suffix}"
    versioned_path = versioned_file_name if folder == "." else f"{folder}/{versioned_file_name}"

    logger.info("Existing file/version found. Using versioned GCS path: %s", versioned_path)
    return versioned_path


# =============================================================================
# Upload helpers
# =============================================================================
def upload_to_gcs(
    bucket_name: str,
    local_file_path: str,
    gcs_destination_path: str,
) -> str:
    """
    Upload a local file to GCS without overwriting existing objects.

    If the destination already exists, a version suffix is added automatically:
        report.pdf -> report_V1.pdf -> report_V2.pdf
    """
    local_path = _safe_local_path(local_file_path)

    client = _get_storage_client()
    bucket = client.bucket(bucket_name)

    safe_destination_path = _get_next_versioned_gcs_path(
        bucket=bucket,
        desired_gcs_path=gcs_destination_path,
    )

    content_type = _content_type_for_file(local_path)

    try:
        blob = bucket.blob(safe_destination_path)
        blob.upload_from_filename(
            str(local_path),
            if_generation_match=0,
            content_type=content_type,
        )
        uploaded_uri = f"gs://{bucket_name}/{safe_destination_path}"
        logger.info("Uploaded file to GCS. local=%s gcs=%s", local_path, uploaded_uri)
        return uploaded_uri

    except PreconditionFailed:
        # Race condition protection: another process may have uploaded the same
        # version between list_blobs and upload. Recalculate and retry once.
        logger.warning(
            "GCS upload precondition failed because object already exists. "
            "Retrying with next available version. bucket=%s path=%s",
            bucket_name,
            safe_destination_path,
        )

        retry_destination_path = _get_next_versioned_gcs_path(
            bucket=bucket,
            desired_gcs_path=gcs_destination_path,
        )

        blob = bucket.blob(retry_destination_path)
        blob.upload_from_filename(
            str(local_path),
            if_generation_match=0,
            content_type=content_type,
        )

        uploaded_uri = f"gs://{bucket_name}/{retry_destination_path}"
        logger.info("Uploaded file to GCS after retry. local=%s gcs=%s", local_path, uploaded_uri)
        return uploaded_uri


def upload_outputs(
    bucket_name: str,
    project_folder: str,
    paths: Dict[str, str],
) -> Dict[str, str]:
    """
    Upload all existing output files to GCS.

    Supports dynamic artifact keys, including:
        pdf, docx, md, html,
        diagram_*_dot, diagram_*_svg, diagram_*_png,
        diagram_*_drawio, diagram_*_vsdx

    Returns actual uploaded gs:// URIs. These may include _V1/_V2 suffixes.
    """
    uploaded_outputs: Dict[str, str] = {}
    folder = _safe_project_folder(project_folder)

    for output_key, path in paths.items():
        if not path:
            logger.debug("Skipping empty output path for key=%s", output_key)
            continue

        local_path = Path(path)
        if not local_path.exists() or not local_path.is_file():
            logger.warning("Skipping missing/non-file output. key=%s path=%s", output_key, path)
            continue

        gcs_destination_path = f"{folder}/{local_path.name}"

        uploaded_outputs[output_key] = upload_to_gcs(
            bucket_name=bucket_name,
            local_file_path=str(local_path),
            gcs_destination_path=gcs_destination_path,
        )

    return uploaded_outputs


# =============================================================================
# Signed URL helpers
# =============================================================================
def generate_signed_gcs_url(
    bucket_name: str,
    gcs_object_path: str,
    expires_minutes: int = DEFAULT_SIGNED_URL_EXPIRY_MINUTES,
) -> Optional[str]:
    """Generate a signed GET URL for an object path inside a GCS bucket."""
    try:
        credentials, _ = default()

        if not can_sign_urls(credentials):
            logger.warning(
                "Signed URL generation skipped: current credentials do not support signing. "
                "bucket=%s object=%s",
                bucket_name,
                gcs_object_path,
            )
            return None

        blob = _get_storage_client(credentials=credentials).bucket(bucket_name).blob(gcs_object_path)

        return blob.generate_signed_url(
            expiration=timedelta(minutes=expires_minutes),
            method="GET",
        )

    except Exception:
        logger.exception("Failed to generate signed GCS URL for %s/%s", bucket_name, gcs_object_path)
        return None


def generate_signed_gcs_url_from_uri(
    gcs_uri: str,
    expires_minutes: int = DEFAULT_SIGNED_URL_EXPIRY_MINUTES,
) -> Optional[str]:
    """
    Generate a signed URL directly from a gs:// URI.

    This is important because upload_to_gcs may rename the final uploaded file
    to _V1/_V2/etc. Signing must use the actual uploaded URI, not the original
    intended filename.
    """
    try:
        bucket_name, object_path = _split_gcs_path(gcs_uri)
        return generate_signed_gcs_url(
            bucket_name=bucket_name,
            gcs_object_path=object_path,
            expires_minutes=expires_minutes,
        )
    except Exception:
        logger.exception("Failed to generate signed URL from GCS URI: %s", gcs_uri)
        return None


def generate_signed_urls_from_uploaded_outputs(
    uploaded_outputs: Dict[str, str],
    expires_minutes: int = DEFAULT_SIGNED_URL_EXPIRY_MINUTES,
) -> Dict[str, Optional[str]]:
    """
    Generate signed URLs from actual uploaded gs:// paths.

    Recommended after upload_outputs(), because the final uploaded filename may
    be versioned dynamically by upload_to_gcs().
    """
    signed_urls: Dict[str, Optional[str]] = {}

    for output_key, gcs_uri in uploaded_outputs.items():
        signed_urls[output_key] = generate_signed_gcs_url_from_uri(
            gcs_uri=gcs_uri,
            expires_minutes=expires_minutes,
        )

    return signed_urls


def generate_signed_urls_from_local_paths(
    bucket_name: str,
    project_folder: str,
    paths: Dict[str, str],
    expires_minutes: int = DEFAULT_SIGNED_URL_EXPIRY_MINUTES,
) -> Dict[str, Optional[str]]:
    """
    Backward-compatible signed URL generation from intended local filenames.

    Use this only when upload_outputs(...) has not been called or when object
    names are guaranteed not to be versioned/renamed.
    """
    signed_urls: Dict[str, Optional[str]] = {}
    folder = _safe_project_folder(project_folder)

    for output_key, path in paths.items():
        if not path:
            signed_urls[output_key] = None
            continue

        object_path = f"{folder}/{Path(path).name}"
        signed_urls[output_key] = generate_signed_gcs_url(
            bucket_name=bucket_name,
            gcs_object_path=object_path,
            expires_minutes=expires_minutes,
        )

    return signed_urls


def generate_signed_urls(
    bucket_name: str,
    project_folder: str,
    paths: Dict[str, str],
    uploaded_outputs: Optional[Dict[str, str]] = None,
    expires_minutes: int = DEFAULT_SIGNED_URL_EXPIRY_MINUTES,
) -> Dict[str, Optional[str]]:
    """
    Generate signed URLs for outputs.

    Preferred usage:
        uploaded_outputs = upload_outputs(...)
        signed_urls = generate_signed_urls(..., uploaded_outputs=uploaded_outputs)

    Backward-compatible usage:
        signed_urls = generate_signed_urls(bucket, folder, paths)

    If uploaded_outputs is provided, signed URLs are generated from actual
    uploaded gs:// URIs. This correctly handles _V1/_V2 versioned uploads.
    Without uploaded_outputs, this function signs the original intended object
    names based on local filenames.
    """
    if uploaded_outputs is not None:
        return generate_signed_urls_from_uploaded_outputs(
            uploaded_outputs=uploaded_outputs,
            expires_minutes=expires_minutes,
        )

    return generate_signed_urls_from_local_paths(
        bucket_name=bucket_name,
        project_folder=project_folder,
        paths=paths,
        expires_minutes=expires_minutes,
    )


# =============================================================================
# Optional convenience helpers
# =============================================================================
def filter_existing_paths(paths: Dict[str, str]) -> Dict[str, str]:
    """
    Return only entries whose local file exists.

    This helper is intentionally optional; orchestrator.py already performs this
    filtering. It is provided here for reuse by tests or future render flows.
    """
    existing: Dict[str, str] = {}
    for key, path in paths.items():
        if path and Path(path).exists() and Path(path).is_file():
            existing[key] = path
    return existing


def list_supported_dynamic_keys_hint() -> Iterable[str]:
    """
    Human-readable hint for supported key patterns.

    This does not drive runtime logic. Runtime logic accepts any key as long as
    the value points to an existing local file.
    """
    return (
        "pdf",
        "docx",
        "md",
        "html",
        "diagram_*_dot",
        "diagram_*_svg",
        "diagram_*_png",
        "diagram_*_drawio",
        "diagram_*_vsdx",
    )
