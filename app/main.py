import os
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from starlette.status import HTTP_202_ACCEPTED # ✅ IMPORT ADDED
from fastapi.middleware.cors import CORSMiddleware
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from sync import Sync
from sync.common import Audio, Video, GenerationOptions
from sync.core.api_error import ApiError

# ------------------- Load Environment & Configuration -------------------
load_dotenv()
app = FastAPI(title="Lip-Sync Generation API")

# --- Environment Variables ---
SYNC_API_KEY = os.getenv("SYNC_API_KEY")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
if not SYNC_API_KEY or not CLOUDINARY_URL:
    raise RuntimeError("Missing SYNC_API_KEY or CLOUDINARY_URL in environment variables")

# --- CORS Middleware (ALLOWS FRONTEND TO CONNECT) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Initialize API Clients & Constants ---
client = Sync(base_url="https://api.sync.so", api_key=SYNC_API_KEY).generations
cloudinary.config(cloudinary_url=CLOUDINARY_URL)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PREDEFINED_VIDEOS = {
    "video1": "https://res.cloudinary.com/dazwg6em3/video/upload/v1727710328/morgan_freeman_hbhs1g.mp4" # A reliable, directly hosted video
}

# ------------------- 🚀 Step 1: Start Generation Endpoint -------------------

@app.post("/generate", status_code=HTTP_202_ACCEPTED) # ✅ RENAMED and status code changed
async def start_generation(
    audio: UploadFile = File(...),
    video_choice: str = Query("video1", description="Choose a predefined video")):
    """
    Starts the lip-sync generation job and immediately returns a job_id.
    This avoids the Gateway Timeout error by not waiting for the long-running task.
    """
    if video_choice not in PREDEFINED_VIDEOS:
        raise HTTPException(status_code=400, detail="Invalid video choice.")

    # Use a secure, unique filename for the temporary audio file
    temp_audio_filename = f"{uuid.uuid4().hex}.wav"
    audio_path = os.path.join(UPLOAD_FOLDER, temp_audio_filename)

    try:
        # 1. Save and upload audio to Cloudinary (this part is fast)
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)
        
        upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
        public_audio_url = upload_result["secure_url"]

        # 2. 🚀 Start the lip-sync job (DO NOT WAIT)
        video_url = PREDEFINED_VIDEOS[video_choice]
        response = client.create(
            input=[Video(url=video_url), Audio(url=public_audio_url)],
            model="lipsync-2",
            options=GenerationOptions(sync_mode="cut_off")
        )
        
        # 3. ✅ Immediately return the job ID to the client
        return {"job_id": response.id}

    except ApiError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e.body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
    finally:
        # 4. Clean up the local audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)

# ------------------- 🔄 Step 2: Status Check Endpoint -------------------

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """
    Checks the status of a long-running generation job using its job_id.
    This is what the client will "poll" every few seconds.
    """
    try:
        # 1. Get the latest status from the Sync.so API
        generation = client.get(job_id)

        # 2. If completed, upload the result to Cloudinary and return the final URL
        if generation.status == "COMPLETED":
            final_video_url = generation.output_url
            # We upload to our own Cloudinary to have a permanent link
            video_upload = cloudinary.uploader.upload(final_video_url, resource_type="video")
            return {
                "status": generation.status,
                "video_url": video_upload["secure_url"]
            }
        
        # 3. If failed, return the error
        if generation.status == "FAILED":
            return {
                "status": generation.status,
                "error": generation.error or "Lip-sync generation failed."
            }

        # 4. If still processing, just return the current status
        return {"status": generation.status} # e.g., "PROCESSING"

    except ApiError as e:
        # This can happen if the job_id is invalid
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="Job ID not found.")
        raise HTTPException(status_code=e.status_code, detail=str(e.body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
