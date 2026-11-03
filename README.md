# youtube-downloader

Downloads YouTube videos in the best available quality, several in parallel, with English
captions embedded in the mp4. Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Features

- Best video + best audio, merged into `.mp4`
- Parallel downloads with a live progress table (percentage, speed, caption status per video)
- English captions saved as `.en.srt` and embedded in the mp4
- Resumes partial downloads and retries dropped connections automatically
- Caption failures (YouTube's HTTP 429 rate limit) never stop a video; they are retried at the end
- File names stay valid on NTFS/Windows drives

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) (merging video/audio and embedding captions)
- [Node.js](https://nodejs.org/) (yt-dlp uses it to solve YouTube's JS challenges for the best formats)

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

Put one YouTube URL per line in `urls.txt`, then:

```bash
.venv/bin/python youtube.py
```

Or pass URLs directly:

```bash
.venv/bin/python youtube.py https://youtu.be/VIDEO_ID https://youtu.be/OTHER_ID
```

Videos are saved to `./videos`. Running it in the background:

```bash
PYTHONUNBUFFERED=1 .venv/bin/python youtube.py > download.log 2>&1 &
tail -f download.log
```

Running the script again skips finished videos, resumes partial ones, and retries missing captions.
Settings such as `MAX_PARALLEL` and `DOWNLOAD_ATTEMPTS` are at the top of `youtube.py`.

## Adding captions later

If YouTube keeps rate-limiting captions, `add_captions.py` fetches them through a different
endpoint (youtube-transcript-api) and embeds them into the already downloaded videos:

```bash
.venv/bin/python add_captions.py              # every URL in urls.txt
.venv/bin/python add_captions.py https://youtu.be/VIDEO_ID
```

Videos that already have captions are skipped.
