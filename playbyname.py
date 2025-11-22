import os
import subprocess
import re

def build_file_cache(folders):
    file_cache = []
    for folder in folders:
        for root, _, files in os.walk(folder):
            for file in files:
                file_cache.append(os.path.join(root, file))
    print(f"Total files found: {len(file_cache)}")  # Print total amount of files
    return file_cache

def find_files_by_name_cached(file_cache, filter_str):
    filter_str = filter_str.lower()
    def clean_filename(path):
        # Remove all non-alphanumeric characters
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

def recursive_filter(file_cache, charset, max_files, backup_file, filter_str="", resume=False, backup_str=None):
    skip = resume and backup_str is not None
    resume_reached = False
    for ch in charset:
        current_str = filter_str + ch
        # Resume logic: skip until backup_str is reached, then continue normally
        if skip:
            if not backup_str.startswith(current_str):
                continue
            if backup_str == current_str:
                skip = False
                resume_reached = True
        matches = find_files_by_name_cached(file_cache, current_str)
        if len(matches) > max_files:
            # Go deeper recursively, propagate resume_reached
            child_resume_reached = recursive_filter(
                file_cache, charset, max_files, backup_file,
                current_str, skip, backup_str
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

def auto_filter(folders, charset=None, max_files=50, backup_file="backupplaybyname.txt"):
    if charset is None:
        charset = list('abcdefghijklmnopqrstuvwxyz0123456789')
    file_cache = build_file_cache(folders)
    backup_str = read_backup(backup_file)
    try:
        recursive_filter(file_cache, charset, max_files, backup_file, "", resume=bool(backup_str), backup_str=backup_str)
    except KeyboardInterrupt:
        print("Interrupted by user. Exiting gracefully.")

if __name__ == "__main__":
    # Example usage:
    # folders = ["C:\\Videos", "D:\\Movies"]
    # filter_str = "abcd"
    # find_files_by_name(folders, filter_str)

    # For demonstration, you can modify these values:
    folders = [
        "p:\\sonst",
        "d:\\jd",
        "d:\\02",
        "d:\\done",
        "d:\\01",
        "c:\\sonst"
    ]
    auto_filter(folders)