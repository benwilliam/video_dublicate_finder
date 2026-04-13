import os
import subprocess
import re
import concurrent.futures
import threading
import time

# --- PRE-CACHING CONFIGURATION ---
CHUNK_SIZE_MB = 10       # Amount of data to read per file to trigger the cache
MAX_CONCURRENT_READS = 1 # Lowered slightly so background caching doesn't starve mpv's bandwidth
ENABLE_PRE_CACHING = True 

def pre_cache_chunk(filepath, chunk_size_mb):
    """Reads the first chunk of a file to force rclone to cache it."""
    bytes_to_read = chunk_size_mb * 1024 * 1024
    try:
        if not os.path.exists(filepath):
            return f"❌ Not found: {os.path.basename(filepath)}"
        with open(filepath, 'rb') as f:
            f.read(bytes_to_read)
        return f"✅ Background Cached {chunk_size_mb}MB: {os.path.basename(filepath)}"
    except Exception as e:
        return f"⚠️ Error caching {os.path.basename(filepath)}: {e}"

def background_cache_worker(file_paths):
    """The logic that runs in the background while mpv is open."""
    # We skip the first file because mpv is already opening it and needs the priority bandwidth
    if len(file_paths) <= 1:
        return
    
    other_files = file_paths[1:]
    
    # Optional: Wait a few seconds so mpv can buffer the first video's start smoothly
    time.sleep(2) 
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_READS) as executor:
        futures = {executor.submit(pre_cache_chunk, path, CHUNK_SIZE_MB): path for path in other_files}
        for future in concurrent.futures.as_completed(futures):
            # Using print here might mix with mpv output, but it's good for debugging
            #print(f"\n[Cache] {future.result()}")
            future.result()

def start_async_caching(file_paths):
    """Starts the caching process in a separate thread so mpv can start immediately."""
    cache_thread = threading.Thread(target=background_cache_worker, args=(file_paths,), daemon=True)
    cache_thread.start()

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
                dirs[:] = [d for d in dirs if not d.startswith('.') and not os.path.islink(os.path.join(root, d))]
                for file in files:
                    if os.path.splitext(file.lower())[1] in video_extensions:
                        file_cache.append(os.path.join(root, file))
                        folder_count += 1
            print(f"  Found {folder_count} video files in: {folder}")
        else:
            print(f"Folder does not exist: {folder}")
    return file_cache

def find_files_by_name_cached(file_cache, filter_str):
    filter_str = filter_str.lower()
    def clean_filename(path):
        return re.sub(r'[^a-zA-Z0-9]', '', os.path.basename(path).lower())
    return sorted(
        [path for path in file_cache if filter_str in clean_filename(path)],
        key=lambda path: clean_filename(path)
    )

def read_backup(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

def write_backup(filename, filter_str):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(filter_str)

def recursive_filter(file_cache, charset, max_files, backup_file, filter_str="", resume=False, backup_str=None, pre_cache=False):
    skip = resume and backup_str is not None
    resume_reached = False
    for ch in charset:
        current_str = filter_str + ch
        if skip:
            if not backup_str.startswith(current_str):
                continue
            if backup_str == current_str:
                skip = False
                resume_reached = True
        matches = find_files_by_name_cached(file_cache, current_str)
        if len(matches) > max_files:
            child_resume_reached = recursive_filter(
                file_cache, charset, max_files, backup_file,
                current_str, skip, backup_str, pre_cache
            )
            if child_resume_reached:
                skip = False
                resume_reached = True
        elif 1 < len(matches) <= max_files:
            print(f"Filter: '{current_str}' found {len(matches)} files.")
            
            with open("playbyname.txt", "w", encoding="utf-8") as f:
                for path in matches:
                    f.write(path + "\n")
            write_backup(backup_file, current_str)
            
            # --- START ASYNC CACHING HERE ---
            if pre_cache:
                start_async_caching(matches)
            
            # This is a blocking call, but because we used a Thread above, 
            # the caching continues while mpv is open.
            subprocess.run([
                r"d:\mpv\mpv.exe",
                "--playlist=playbyname.txt",
                "--playlist-start=0",
                "--fullscreen",
                "--script-opts-append=osc-visibility=always"
            ])
        else:
            print(f"skipping: {current_str}")
    return resume_reached

def auto_filter(folders, charset=None, max_files=30, backup_file="backupplaybyname.txt", pre_cache=False):
    if charset is None:
        charset = list('abcdefghijklmnopqrstuvwxyz0123456789')
    file_cache = build_file_cache(folders)
    backup_str = read_backup(backup_file)
    try:
        recursive_filter(file_cache, charset, max_files, backup_file, "", resume=bool(backup_str), backup_str=backup_str, pre_cache=pre_cache)
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")

if __name__ == "__main__":
    folders = [
        "c:\\sonst",
        "d:\\jd",
        "d:\\02",
        "d:\\done",
        "p:\\Untitled",
        "p:\\Untitled 1"
    ]
    auto_filter(folders, pre_cache=ENABLE_PRE_CACHING)