import time
import io
import logging
import asyncio
import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from typing import List
from fastapi import FastAPI, HTTPException, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# Uvicorn runs this file from the project root, so imports must be absolute starting from the 'execution' module.
from execution.scrape_instagram import scrape_profile
from execution.generate_titles import generate_titles
from execution.generate_cover import generate_cover_zip

load_dotenv()

# --- Logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- File upload constraints ---
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

app = FastAPI(title="Instagram Profile Extractor")

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

class URLsRequest(BaseModel):
    urls: List[str]

progress_store = {}

@app.get("/progress")
def progress_api(task_id: str):
    return progress_store.get(task_id, {"current": 0, "total": 0})

@app.get("/", response_class=FileResponse)
def serve_frontend():
    return FileResponse("static/index.html")

@app.post("/extract")
async def extract_profiles(request: URLsRequest):
    logger.info("Extract request received for %d URLs", len(request.urls))
    results = []

    for i, url in enumerate(request.urls):
        # 2-second delay between requests as per directive, except for the first one
        if i > 0:
            await asyncio.sleep(2)

        profile_data = await asyncio.to_thread(scrape_profile, url)

        if "error" in profile_data:
            # If error scraping, append error and continue
            logger.warning("Scrape error for '%s': %s", url, profile_data["error"])
            results.append({
                "url": url,
                "error": profile_data["error"],
                "error_type": profile_data.get("error_type", "unknown")
            })
            continue

        # GPT call for titles
        gpt_data = await asyncio.to_thread(generate_titles, profile_data["name"], profile_data["bio"])

        results.append({
            "username": profile_data["username"],
            "name": profile_data["name"],
            "bio": profile_data["bio"],
            "external_link": profile_data["external_link"],
            "formatted_name": gpt_data.get("formatted_name", ""),
            "specialty_line": gpt_data.get("specialty_line", ""),
            "headline": gpt_data.get("headline", "")
        })

    logger.info("Extract completed: %d results", len(results))
    return results

@app.post("/extract-batch")
async def extract_batch(request: URLsRequest, task_id: str = ""):
    logger.info("Batch extract request received for %d URLs (task_id=%s)", len(request.urls), task_id or "none")
    if task_id:
        progress_store[task_id] = {"current": 0, "total": len(request.urls)}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Username", "Nome", "Especialidade", "Headline", "Link Externo"])

    for i, url in enumerate(request.urls):
        if i > 0:
            await asyncio.sleep(2)

        profile_data = await asyncio.to_thread(scrape_profile, url)

        if "error" in profile_data:
            ws.append([profile_data.get("username", url), "ERRO", profile_data["error"], "", ""])
        else:
            gpt_data = await asyncio.to_thread(generate_titles, profile_data["name"], profile_data["bio"])
            ws.append([
                profile_data["username"],
                gpt_data.get("formatted_name", ""),
                gpt_data.get("specialty_line", ""),
                gpt_data.get("headline", ""),
                profile_data["external_link"]
            ])

        if task_id:
            progress_store[task_id]["current"] = i + 1
            
    # Format header row
    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        
    # Auto-fit columns
    for col in ws.columns:
        max_length = 0
        column_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value and len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        ws.column_dimensions[column_letter].width = max_length + 2
            
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    
    # Optional cleanup to avoid memory leak for progress dictionary
    if task_id in progress_store:
        # Give JS a moment to read 100%
        # Ideally, a background task cleans this up, but for this utility keeping it in memory is negligible.
        pass
    
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=resultados.xlsx"}
    )

@app.post("/generate-cover")
async def generate_cover(
    photo: UploadFile = File(...),
    brand_color: str = Form(...),
    instagram_url: str = Form(...)
):
    # --- File upload validation ---
    if photo.content_type and photo.content_type not in ALLOWED_IMAGE_TYPES:
        logger.warning("Rejected upload: invalid content type '%s'", photo.content_type)
        raise HTTPException(status_code=400, detail=f"Invalid file type: {photo.content_type}. Allowed: JPEG, PNG, WebP.")

    photo_bytes = await photo.read()

    if len(photo_bytes) > MAX_UPLOAD_SIZE:
        size_mb = len(photo_bytes) / (1024 * 1024)
        logger.warning("Rejected upload: file too large (%.1f MB)", size_mb)
        raise HTTPException(status_code=400, detail=f"File too large ({size_mb:.1f} MB). Maximum allowed: 10 MB.")

    if len(photo_bytes) < 100:
        raise HTTPException(status_code=400, detail="File appears to be empty or corrupted.")

    try:
        logger.info("Generating cover for '%s'", instagram_url)
        zip_bytes = await asyncio.to_thread(generate_cover_zip, photo_bytes, brand_color, instagram_url)
        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="capa.zip"'}
        )
    except Exception as e:
        logger.error("Cover generation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
