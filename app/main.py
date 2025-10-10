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

# ------------------- Main Endpoint -------------------
@app.post("/generate-lipsync/")
async def generate_lipsync(
    audio: UploadFile = File(...),
    video_choice: str = Query("video1", description="Choose predefined video")
):
    if video_choice not in PREDEFINED_VIDEOS:
        raise HTTPException(status_code=400, detail="Invalid video choice")

    video_url = PREDEFINED_VIDEOS[video_choice]
    audio_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_{audio.filename}")

    try:
        # Save audio locally
        with open(audio_path, "wb") as f:
            f.write(await audio.read())

        # Upload audio to Cloudinary (get public URL)
        upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
        public_audio_url = upload_result["secure_url"]

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
        progress_increment = 5 # Increment progress by 5 every 5 seconds

        while status not in ["COMPLETED", "FAILED"]:
            time.sleep(5)
            generation = client.get(job_id)
            status = generation.status
            # Update progress bar only if progress is available and increasing
            if generation.progress is not None:
                new_progress = int(generation.progress)
                progress_bar.update(new_progress - progress_bar.n)
            else:
                progress_bar.update(progress_increment)
            
            progress_bar.set_postfix_str(f"Status: {status}")

        progress_bar.close()

        if status == "COMPLETED":
            # ------------------- MODIFIED LOGIC HERE -------------------
            # Instead of downloading the file, return the generated video URL.
            return JSONResponse(
                content={
                    "message": "Lipsync generation completed successfully.",
                    "video_url": generation.output_url
                }
            )
            # -----------------------------------------------------------
        else:
            # Fetch the final generation status to get detailed error if available
            generation = client.get(job_id) 
            error_detail = generation.error_message if generation.error_message else "Generation failed without a specific message."
            raise HTTPException(status_code=500, detail=f"Generation failed: {error_detail}")

    except ApiError as e:
        raise HTTPException(status_code=e.status_code, detail=e.body)
    
    except Exception as e:
        # Catch any other unexpected errors
        print(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred.")

    finally:
        # Clean up the locally saved audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)
