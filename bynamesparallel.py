import os
import subprocess
import re
import threading
import queue
import time

# ---------------------------------------------------------------------------
# MPV process pool
# ---------------------------------------------------------------------------

class MpvPool:
    """Manages a pool of MPV instances running in parallel, each started paused."""

    def __init__(self, max_parallel: int = 1):
        self.max_parallel = max_parallel
        self._queue: queue.Queue = queue.Queue()
        self._sem = threading.Semaphore(max_parallel)  # one permit per running MPV slot
        self._procs: list[subprocess.Popen] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, playlist_path: str, label: str = ""):
        """Block until a running slot is free, then enqueue the playlist."""
        self._sem.acquire()          # blocks here when max_parallel processes are running
        self._queue.put((playlist_path, label))

    def wait_all(self):
        """Block until the queue is drained and every MPV window is closed."""
        self._queue.join()          # wait for all submitted items to be processed
        self._stop.set()
        self._thread.join()
        with self._lock:
            for proc, playlist_path in self._procs:
                proc.wait()
                self._sem.release()
                try:
                    os.remove(playlist_path)
                    print(f"  [mpv] deleted playlist: {playlist_path}")
                except OSError as e:
                    print(f"  [mpv] could not delete playlist {playlist_path}: {e}")

    # ------------------------------------------------------------------
    def _launch(self, playlist_path: str):
        return subprocess.Popen([
            r"d:\mpv\mpv.exe",
            "--playlist=" + playlist_path,
            "--playlist-start=0",
            "--fullscreen",
            "--pause",                                    # start paused
            "--script-opts-append=osc-visibility=always"
        ])

    def _run(self):
        # _procs holds (Popen, playlist_path) pairs
        while not self._stop.is_set() or not self._queue.empty():
            # Reap finished processes and delete their playlist files
            with self._lock:
                still_running = []
                for proc, playlist_path in self._procs:
                    if proc.poll() is None:
                        still_running.append((proc, playlist_path))
                    else:
                        self._sem.release()          # free the slot
                        try:
                            os.remove(playlist_path)
                            print(f"  [mpv] deleted playlist: {playlist_path}")
                        except OSError as e:
                            print(f"  [mpv] could not delete playlist {playlist_path}: {e}")
                self._procs = still_running
                free_slots = self.max_parallel - len(self._procs)

            # Fill free slots from the queue
            for _ in range(free_slots):
                try:
                    playlist_path, label = self._queue.get_nowait()
                except queue.Empty:
                    break
                print(f"  [mpv] launching{(' (' + label + ')') if label else ''}: {playlist_path}")
                with self._lock:
                    self._procs.append((self._launch(playlist_path), playlist_path))
                self._queue.task_done()

            time.sleep(0.4)   # short poll interval


# ---------------------------------------------------------------------------
# File cache & search
# ---------------------------------------------------------------------------

def build_file_cache(folders):
    video_extensions = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv',
        '.flv', '.webm', '.m4v', '.mpg', '.mpeg',
        '.3gp', '.ts', '.mts', '.m2ts'
    }
    file_cache = []
    for folder in folders:
        if os.path.exists(folder):
            print(f"Scanning folder: {folder}")
            folder_count = 0
            for root, dirs, files in os.walk(folder):
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith('.') and not os.path.islink(os.path.join(root, d))
                ]
                for file in files:
                    if os.path.splitext(file.lower())[1] in video_extensions:
                        file_cache.append(os.path.join(root, file))
                        folder_count += 1
            print(f"  Found {folder_count} video files in: {folder}")
        else:
            print(f"Folder does not exist: {folder}")
    print(f"Total video files found: {len(file_cache)}")
    return file_cache


def find_files_by_name_cached(file_cache, filter_str):
    filter_str = filter_str.lower()

    def clean_filename(path):
        return re.sub(r'[^a-zA-Z0-9]', '', os.path.basename(path).lower())

    return sorted(
        [path for path in file_cache if filter_str in clean_filename(path)],
        key=lambda path: clean_filename(path)
    )


# ---------------------------------------------------------------------------
# Backup helpers
# ---------------------------------------------------------------------------

def read_backup(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def write_backup(filename, filter_str):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(filter_str)


# ---------------------------------------------------------------------------
# Recursive filter + pool submission
# ---------------------------------------------------------------------------

def recursive_filter(
    file_cache, charset, max_files, backup_file, pool: MpvPool,
    filter_str="", resume=False, backup_str=None
):
    skip = resume and backup_str is not None
    resume_reached = False

    for ch in charset:
        current_str = filter_str + ch

        # Resume logic: skip until backup_str prefix is matched
        if skip:
            if not backup_str.startswith(current_str):
                continue
            if backup_str == current_str:
                skip = False
                resume_reached = True

        matches = find_files_by_name_cached(file_cache, current_str)

        if len(matches) > max_files:
            child_resume_reached = recursive_filter(
                file_cache, charset, max_files, backup_file, pool,
                current_str, skip, backup_str
            )
            if child_resume_reached:
                skip = False
                resume_reached = True

        elif 1 < len(matches) <= max_files:
            print(f"Filter: '{current_str}' found {len(matches)} files.")
            playlist_path = f"playbyname_{current_str}.txt"
            with open(playlist_path, "w", encoding="utf-8") as f:
                for path in matches:
                    f.write(path + "\n")
            write_backup(backup_file, current_str)
            pool.submit(playlist_path, label=current_str)

        else:
            print(f"skipping: {current_str}")

    return resume_reached


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def auto_filter(
    folders,
    charset=None,
    max_files: int = 10,
    backup_file: str = "backupplaybyname.txt",
    max_parallel: int = 1,          # ← configurable parallel MPV instances
):
    if charset is None:
        charset = list('abcdefghijklmnopqrstuvwxyz0123456789')

    file_cache = build_file_cache(folders)
    backup_str = read_backup(backup_file)

    pool = MpvPool(max_parallel=max_parallel)
    try:
        recursive_filter(
            file_cache, charset, max_files, backup_file, pool,
            "", resume=bool(backup_str), backup_str=backup_str
        )
        print("All playlists submitted – waiting for MPV windows to close …")
        pool.wait_all()
    except KeyboardInterrupt:
        print("Interrupted by user. Exiting gracefully.")


if __name__ == "__main__":
    folders = [
        "c:\\sonst",
        "d:\\jd",
        "d:\\02",
        "d:\\done",
        #"d:\\01",
        #"t:\\",
        "p:\\Untitled",
        "p:\\Untitled 1",
    ]

    auto_filter(
        folders,
        max_parallel=5,     # ← change this to run more/fewer MPV instances at once
    )