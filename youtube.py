import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import yt_dlp
from yt_dlp.postprocessor import PostProcessor

SAVE_PATH = "./videos"
URLS_FILE = "urls.txt"
MAX_PARALLEL = 6
DOWNLOAD_ATTEMPTS = 5
REFRESH_SECONDS = 2 if sys.stdout.isatty() else 10

lock = threading.Lock()
state = {}  # index -> {'url', 'title', 'status', 'streams': {format_id: [downloaded, total]}, 'speed'}


class SilentLogger:
    """Keeps yt_dlp quiet so the progress table stays readable; remembers the last error."""

    def __init__(self, index):
        self.index = index

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        if 'Unable to download video subtitles' in msg:
            with lock:
                state[self.index]['captions'] = 'failed'

    def error(self, msg):
        with lock:
            state[self.index]['error'] = msg


class RecordSizes(PostProcessor):
    """Runs right before the download starts and records the expected size of each stream
    (video + audio), so the percentage covers the whole video instead of one stream at a time."""

    def __init__(self, index):
        super().__init__()
        self.index = index

    def run(self, info):
        formats = info.get('requested_formats') or [info]
        with lock:
            s = state[self.index]
            s['title'] = info.get('title') or s['title']
            s['status'] = 'downloading'
            if s['captions'] is None:
                s['captions'] = 'ok' if info.get('requested_subtitles') else 'none available'
            for f in formats:
                size = f.get('filesize') or f.get('filesize_approx') or 0
                s['streams'].setdefault(f.get('format_id'), [0, size])
        return [], info


def make_progress_hook(index):
    def hook(d):
        fid = d.get('info_dict', {}).get('format_id')
        with lock:
            streams = state[index]['streams']
            if fid not in streams:  # subtitle downloads etc.
                return
            stream = streams[fid]
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or stream[1]
            if d['status'] == 'downloading':
                stream[0] = d.get('downloaded_bytes') or 0
                stream[1] = total
                state[index]['speed'] = d.get('speed')
            elif d['status'] == 'finished':
                stream[0] = stream[1] = d.get('total_bytes') or d.get('downloaded_bytes') or total
                state[index]['speed'] = None
    return hook


def make_postprocessor_hook(index):
    labels = {'Merger': 'merging video+audio', 'FFmpegEmbedSubtitle': 'embedding captions',
              'FFmpegSubtitlesConvertor': 'converting captions'}

    def hook(d):
        if d['status'] == 'started' and d['postprocessor'] in labels:
            with lock:
                state[index]['status'] = labels[d['postprocessor']]
    return hook


def download_youtube_video(index, url, save_path=SAVE_PATH):
    """
    Downloads the highest quality YouTube video with English captions using yt_dlp.
    Captions are saved as .srt files next to the video and embedded in the mp4.
    """
    ydl_opts = {
        'outtmpl': f'{save_path}/%(title)s.%(ext)s',
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'quiet': True,
        'noprogress': True,
        # Keep file names valid on NTFS/Windows drives (no : ? " * etc.)
        'windowsfilenames': True,
        # A caption failure (e.g. YouTube rate-limiting with HTTP 429) becomes a warning
        # instead of stopping the video download; captions are retried afterwards.
        'ignoreerrors': True,
        'socket_timeout': 30,
        'retries': 20,
        'fragment_retries': 20,
        'logger': SilentLogger(index),
        'progress_hooks': [make_progress_hook(index)],
        'postprocessor_hooks': [make_postprocessor_hook(index)],
        # Use Node.js to solve YouTube's JS challenges (needed for the best formats)
        'js_runtimes': {'node': {}},
        # Captions: uploaded subtitles if available, otherwise auto-generated ones
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'postprocessors': [
            {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'},
            {'key': 'FFmpegEmbedSubtitle', 'already_have_subtitle': True},
        ],
    }
    # Dropped connections are common on long downloads; retry the whole video a few times.
    # yt_dlp resumes from the partial .part file, so no progress is lost between attempts.
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        failed = True
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.add_post_processor(RecordSizes(index), when='before_dl')
                failed = ydl.download([url])
        except Exception as e:
            with lock:
                state[index].setdefault('error', str(e))
        if not failed:
            with lock:
                state[index]['status'] = 'done'
                state[index].pop('error', None)
            return
        if attempt < DOWNLOAD_ATTEMPTS:
            wait = 30 * attempt
            with lock:
                state[index]['status'] = f'connection error, retry {attempt}/{DOWNLOAD_ATTEMPTS - 1} in {wait}s'
                state[index].pop('error', None)
            time.sleep(wait)
    with lock:
        state[index]['status'] = 'error'


def percent(s):
    downloaded = sum(dl for dl, _ in s['streams'].values())
    total = sum(t for _, t in s['streams'].values())
    if s['status'] == 'done':
        return 100.0
    return min(100.0, 100 * downloaded / total) if total else 0.0


def render():
    lines = []
    with lock:
        for i, s in sorted(state.items()):
            pct = percent(s)
            bar = '#' * int(pct // 5) + '-' * (20 - int(pct // 5))
            speed = f"{s['speed'] / 1024 / 1024:5.1f} MB/s" if s.get('speed') else ' ' * 10
            title = (s['title'] or s['url'])[:45].ljust(45)
            status = s['status'] if s['status'] != 'error' else f"error: {s.get('error', '')[:60]}"
            captions = f"captions: {s['captions']}" if s['captions'] else ''
            lines.append(f"[{i}] {title} [{bar}] {pct:5.1f}% {speed}  {status}  {captions}")
    return lines


def show_progress(stop):
    printed = 0
    while True:
        lines = render()
        if sys.stdout.isatty():
            sys.stdout.write('\033[F' * printed + ''.join(f'\033[K{line}\n' for line in lines))
            printed = len(lines)
        else:
            print(time.strftime('--- %H:%M:%S ---'))
            print('\n'.join(lines))
        sys.stdout.flush()
        if stop.wait(REFRESH_SECONDS):
            break
    if not sys.stdout.isatty():
        print(time.strftime('--- %H:%M:%S (final) ---'))
        print('\n'.join(render()))


def retry_captions():
    """Retries captions that failed (usually YouTube's HTTP 429 rate limit), one video at a time
    with growing waits. The video is already downloaded, so yt_dlp only fetches the captions
    and embeds them into the existing mp4."""
    for wait in (60, 120, 240, 480):
        with lock:
            pending = [i for i, s in state.items() if s['status'] == 'done' and s['captions'] == 'failed']
            for i in pending:
                state[i]['status'] = f'done, retrying captions in {wait}s'
        if not pending:
            return
        time.sleep(wait)
        for i in pending:
            with lock:
                state[i]['captions'] = None
            download_youtube_video(i, state[i]['url'])
            time.sleep(5)


def read_urls():
    if len(sys.argv) > 1:
        return sys.argv[1:]
    with open(URLS_FILE) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]


def main():
    urls = read_urls()
    for i, url in enumerate(urls, 1):
        state[i] = {'url': url, 'title': None, 'status': 'queued', 'streams': {}, 'speed': None,
                    'captions': None}

    stop = threading.Event()
    printer = threading.Thread(target=show_progress, args=(stop,))
    printer.start()

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        for i, url in enumerate(urls, 1):
            pool.submit(download_youtube_video, i, url)
    retry_captions()

    stop.set()
    printer.join()
    failed = [i for i, s in state.items() if s['status'] == 'error']
    no_captions = [i for i, s in state.items() if s['captions'] == 'failed']
    print(f"\nFinished: {len(urls) - len(failed)} done, {len(failed)} failed.")
    if no_captions:
        print(f"Captions still rate-limited for {no_captions}. Run the script again later to add them.")
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
