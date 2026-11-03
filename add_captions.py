"""
Adds English captions to videos that are already downloaded.

Uses youtube-transcript-api, which reads captions from a different YouTube endpoint than
yt_dlp, so it often works while yt_dlp's caption downloads are rate-limited (HTTP 429).
Captions are saved as .en.srt next to the video and embedded into the mp4.

Usage:
    .venv/bin/python add_captions.py                 # every URL in urls.txt
    .venv/bin/python add_captions.py URL [URL ...]
"""
import os
import subprocess
import sys
from pathlib import Path

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import SRTFormatter

from youtube import SAVE_PATH, read_urls


def video_path(url):
    """Finds where youtube.py saved this video (same file name template)."""
    opts = {
        'outtmpl': f'{SAVE_PATH}/%(title)s.%(ext)s',
        'merge_output_format': 'mp4',
        'windowsfilenames': True,
        'quiet': True,
        'skip_download': True,
        'js_runtimes': {'node': {}},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info['id'], Path(ydl.prepare_filename(info)).with_suffix('.mp4')


def english_transcript(video_id):
    """English captions if the video has them, otherwise YouTube's translation to English."""
    transcripts = YouTubeTranscriptApi().list(video_id)
    try:
        return transcripts.find_transcript(['en', 'en-US', 'en-GB']).fetch()
    except Exception:
        return next(iter(transcripts)).translate('en').fetch()


def embed(mp4, srt):
    tmp = mp4.with_suffix('.captions.tmp.mp4')
    subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-i', mp4, '-i', srt,
         '-map', '0', '-map', '1', '-c', 'copy', '-c:s', 'mov_text',
         '-metadata:s:s:0', 'language=eng', tmp],
        check=True,
    )
    os.replace(tmp, mp4)


def main():
    for url in read_urls():
        try:
            video_id, mp4 = video_path(url)
            srt = mp4.with_suffix('.en.srt')
            if not mp4.exists():
                print(f"SKIP   {mp4.name}: video not downloaded yet")
                continue
            if srt.exists():
                print(f"OK     {mp4.name}: already has captions")
                continue
            srt.write_text(SRTFormatter().format_transcript(english_transcript(video_id)), encoding='utf-8')
            embed(mp4, srt)
            print(f"ADDED  {mp4.name}")
        except Exception as e:
            print(f"FAILED {url}: {type(e).__name__} {str(e).splitlines()[0] if str(e) else ''}")


if __name__ == '__main__':
    main()
