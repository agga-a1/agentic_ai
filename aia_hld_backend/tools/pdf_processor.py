# import os
# import pdfplumber
# from pdf2image import convert_from_path
# import base64
# import io

# def read_pdf_hybrid(file_path: str):
#     if not os.path.exists(file_path):
#         return {"status": "Error", "message": f"File not found: {file_path}"}

#     results = {
#         "filename": os.path.basename(file_path),
#         "text": "", 
#         "pages_as_base64_images": [], 
#         "status": "Success"
#     }

#     try:
#         # 1. TEXT EXTRACTION (Keep up to 15 pages - text is very cheap)
#         with pdfplumber.open(file_path) as pdf:
#             pages_to_read = pdf.pages[:15] 
#             results["text"] = "\n".join([p.extract_text() for p in pages_to_read if p.extract_text()])

#         # 2. IMAGE EXTRACTION (The "Token Diet" Version)
#         # We drop DPI to 60 and only take the first 5 pages.
#         # This reduces image token cost by ~60% compared to your previous version.
#         # images = convert_from_path(
#         #     file_path, 
#         #     dpi=60,           # Reduced from 72 to 60
#         #     first_page=1, 
#         #     last_page=5       # Reduced from 10 to 5 (most HLDs are at the start)
#         # )
        
#         # for img in images:
#         #     buffered = io.BytesIO()
#         #     # Quality 40 is the 'Sweet Spot' - text in diagrams remains readable for Gemini
#         #     img.convert('RGB').save(buffered, format="JPEG", quality=40)
#         #     img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
#         #     results["pages_as_base64_images"].append(img_str)

#         return results
#     except Exception as e:
#         # Return a clean error so the Agent can explain it to the user
#         return {"status": "Error", "message": f"PDF Processing failed: {str(e)}"}

import os
import pdfplumber

def read_pdf_hybrid(file_path: str):
    """
    Simplified PDF Text Extractor.
    Images are now handled separately by the ingestion script.
    """
    if not os.path.exists(file_path):
        return {"status": "Error", "message": f"File not found: {file_path}"}

    results = {
        "filename": os.path.basename(file_path),
        "text": "", 
        "status": "Success"
    }

    try:
        # TEXT EXTRACTION 
        # We use pdfplumber for better structural layout retention (tables/headers)
        with pdfplumber.open(file_path) as pdf:
            # We read all pages for the Knowledge Base, but you can limit 
            # if the docs are massive (e.g., pdf.pages[:50])
            pages_to_read = pdf.pages 
            
            extracted_text = []
            for p in pages_to_read:
                page_text = p.extract_text()
                if page_text:
                    extracted_text.append(page_text)
            
            results["text"] = "\n\n".join(extracted_text)

        return results

    except Exception as e:
        return {"status": "Error", "message": f"PDF Text Extraction failed: {str(e)}"}