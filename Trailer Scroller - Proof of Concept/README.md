Step 1:
- In backend:
  - python -m pip install -r requirements.txt

  - python -m pip install yt-dlp --pre

  - Run setup:
    - python setup.py --token YOUR_IMDB_TOKEN --movies COUNT

    - COUNT: Number of movie trailers to download.

    - python repair_db.py

Step 2:
- In frontend:
  - npm install

Step 3:
 - Go to github.com/BtbN/FFmpeg-Builds/releases
 - Download ffmpeg-master-latest-win64-gpl.zip
 - Extract it, find ffmpeg.exe inside the bin/ folder
 - Copy ffmpeg.exe into your localscroll/backend/ folder

Step 4:
 - In backend:
     # Terminal 1
     - python -m uvicorn main:app --port 8000

 - In frontend
     # Terminal 2
     - npm run dev