@echo off
chcp 65001 >nul
echo ================================================
echo   YouTube Multilingual Auto Fill (v2 - waits for Google verification)
echo ================================================
echo.
echo Enter the Video ID.
echo Example page: https://studio.youtube.com/video/OYwuL0_lvBE/edit
echo Just the part between /video/ and /edit  (example: OYwuL0_lvBE)
echo.
set /p VIDEOID=Video ID:
echo.
python "C:\Users\lg\Desktop\yt_automation\youtube_auto_translate_v2.py" "C:\Users\lg\Desktop\yt_automation\youtube_multilingual_data.csv" "%VIDEOID%"
echo.
echo ================================================
echo   Done. You can close this window.
echo ================================================
pause
