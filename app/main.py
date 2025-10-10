import os
import uuid
import time
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware # ✅ IMPORT ADDED
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
# This is crucial for your React/JavaScript frontend to be able to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# --- Initialize API Clients & Constants ---
client = Sync(base_url="https://api.sync.so", api_key=SYNC_API_KEY).generations
cloudinary.config(cloudinary_url=CLOUDINARY_URL)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PREDEFINED_VIDEOS = {
    "video1": "https://res.cloudinary.com/dazwg6em3/video/upload/v1727710328/morgan_freeman_hbhs1g.mp4" # A reliable, directly hosted video
}

# ------------------- Main API Endpoint -------------------
@app.post("/generate-lipsync/")
async def generate_lipsync(
    audio: UploadFile = File(...),
    video_choice: str = Query("video1", description="Choose a predefined video")
):
    if video_choice not in PREDEFINED_VIDEOS:
        raise HTTPException(status_code=400, detail="Invalid video choice.")

    # Use a secure, unique filename for the temporary audio file
    temp_audio_filename = f"{uuid.uuid4().hex}.wav"
    audio_path = os.path.join(UPLOAD_FOLDER, temp_audio_filename)

    try:
        # 1. Save the uploaded audio file temporarily
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)

        # 2. Upload the audio to Cloudinary to get a public URL
        # The resource_type 'video' works for audio files as well on Cloudinary
        upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
        public_audio_url = upload_result["secure_url"]

        # 3. 🚀 Start the lip-sync generation job with Sync.so
        video_url = PREDEFINED_VIDEOS[video_choice]
        response = client.create(
            input=[Video(url=video_url), Audio(url=public_audio_url)],
            model="lipsync-2",
            options=GenerationOptions(sync_mode="cut_off")
        )
        job_id = response.id

        # 4. Poll for the result (with a timeout to prevent server hanging)
        start_time = time.time()
        while time.time() - start_time < 300: # 5-minute timeout
            generation = client.get(job_id)
            if generation.status == "COMPLETED":
                break
            if generation.status == "FAILED":
                # Provide a more detailed error if the job fails
                error_detail = generation.error or "Lip-sync generation failed at the provider."
                raise HTTPException(status_code=500, detail=error_detail)
            time.sleep(5) # Wait 5 seconds before checking again
        else:
            raise HTTPException(status_code=504, detail="Generation timed out after 5 minutes.")

        # 5. ✅ IMPROVEMENT: Upload the final video directly from its URL to Cloudinary
        # This avoids saving the file to our server, making it faster and more efficient.
        final_video_url = generation.output_url
        video_upload = cloudinary.uploader.upload(final_video_url, resource_type="video")
        
        return {"video_url": video_upload["secure_url"]}

    except ApiError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e.body))
    except HTTPException as e:
        # Re-raise HTTP exceptions to send proper responses to the client
        raise e
    except Exception as e:
        # Catch any other unexpected errors
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
    finally:
        # 6. Clean up the temporary local audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)
