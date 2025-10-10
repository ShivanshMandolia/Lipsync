from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse # <-- Changed to return JSON
from sync import Sync
from sync.common import Audio, Video, GenerationOptions
from sync.core.api_error import ApiError
import os, uuid, time, requests, cloudinary, cloudinary.uploader
from tqdm import tqdm
from dotenv import load_dotenv
from starlette.status import HTTP_202_ACCEPTED # ✅ IMPORT ADDED
from fastapi.middleware.cors import CORSMiddleware
# ------------------- Load Environment -------------------
load_dotenv()

app = FastAPI(title="Sync.so Lip-Sync API")
# --- CORS Middleware (ALLOWS FRONTEND TO CONNECT) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Sync API Key
API_KEY = os.getenv("SYNC_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing SYNC_API_KEY in environment variables")

# Initialize Sync client
client = Sync(base_url="https://api.sync.so", api_key=API_KEY).generations

# Cloudinary Setup
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
if not CLOUDINARY_URL:
    raise RuntimeError("Missing CLOUDINARY_URL in environment variables")

cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# Local folder (for temp save)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Predefined videos
PREDEFINED_VIDEOS = {
    "video1": "https://drive.google.com/uc?export=download&id=1zEQnsgkUrFHGZDRzFPmxYXm0qKNREDFI"
}

# ... (rest of the imports and setup remain the same) ...

# ------------------- Main Endpoint -------------------
@app.post("/generate-lipsync/")
async def generate_lipsync(
    audio: UploadFile = File(...),
    video_choice: str = Query("video1", description="Choose predefined video")
):
    # ... (initial checks and file saving logic remain the same) ...
    # audio_path and public_audio_url are set up here

    try:
        # Save audio locally
        # ... (audio saving logic) ...

        # Upload audio to Cloudinary (get public URL)
        # ... (Cloudinary upload logic) ...

        print(f"🎵 Uploaded audio to Cloudinary: {public_audio_url}")

        # Start Sync.so generation
        response = client.create(
            input=[Video(url=video_url), Audio(url=public_audio_url)],
            model="lipsync-2",
            options=GenerationOptions(sync_mode="cut_off")
        )

        job_id = response.id
        status = "PENDING"
        progress_bar = tqdm(total=100, desc="Processing", position=0)
        progress_increment = 5  # Simple time-based increment

        while status not in ["COMPLETED", "FAILED", "REJECTED"]:
            time.sleep(5)
            generation = client.get(job_id)
            status = generation.status
            
            # ------------------- ERROR FIX: Remove generation.progress -------------------
            # Since 'progress' is not a reliable attribute, we use a simple increment
            # to make the progress bar move while we wait for the status.
            
            # This logic provides *simulated* progress without crashing:
            if status == "PROCESSING" and progress_bar.n < 90:
                progress_bar.update(progress_increment)
            elif status == "COMPLETED" or status == "FAILED":
                progress_bar.n = 100
                
            progress_bar.set_postfix_str(f"Status: {status}")

        progress_bar.close()

        if status == "COMPLETED":
            return JSONResponse(
                content={
                    "message": "Lipsync generation completed successfully.",
                    "video_url": generation.output_url
                }
            )
        else:
            # Handle FAILED or REJECTED status and include error message if available
            error_detail = generation.error_message if generation.error_message else "Generation failed without a specific message."
            raise HTTPException(status_code=500, detail=f"Generation failed. Status: {status}. Detail: {error_detail}")

    except ApiError as e:
        raise HTTPException(status_code=e.status_code, detail=e.body)
    
    except Exception as e:
        # The generic Exception handler will catch the original AttributeError 
        # (if it somehow occurred outside the fixed loop) and handle it gracefully.
        print(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {e}")

    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)
    finally:
        # Clean up the locally saved audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)
