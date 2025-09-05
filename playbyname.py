import os
import itertools
import subprocess

def find_files_by_name(folders, filter_str):
    filter_str = filter_str.lower()
    matches = []
    for folder in folders:
        for root, _, files in os.walk(folder):
            for file in files:
                if filter_str in file.lower():
                    matches.append(os.path.join(root, file))
    return matches

def read_backup(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

def write_backup(filename, filter_str):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(filter_str)

def auto_filter(folders, charset='abcdefghijklmnopqrstuvwxyz0123456789_-,!', max_files=100, backup_file="backupplaybyname.txt"):
    backup_str = read_backup(backup_file)
    length = len(backup_str) if backup_str else 1
    try:
        while True:
            found_any = False
            combos = itertools.product(charset, repeat=length)
            skip = True if backup_str else False
            for combo in combos:
                filter_str = ''.join(combo)
                if skip:
                    if filter_str != backup_str:
                        continue
                    else:
                        skip = False  # Found the backup, start processing from here
                matches = find_files_by_name(folders, filter_str)
                if len(matches) > max_files:
                    length += 1
                    backup_str = None  # Reset skip for next length
                    break  # Go deeper with longer filter_str
                elif 1 < len(matches) <= max_files:
                    print(f"Filter: '{filter_str}' found {len(matches)} files.")
                    with open("playbyname.txt", "w", encoding="utf-8") as f:
                        for path in matches:
                            f.write(path + "\n")
                    write_backup(backup_file, filter_str)
                    subprocess.run([
                        r"d:\mpv\mpv.exe",
                        "--playlist=playbyname.txt"
                    ])
                    found_any = True
                    # Continue with next combination
                # If no files found or only one file found, just continue to next combination
            else:
                if not found_any:
                    length += 1
                backup_str = None  # Only skip on first loop after resume
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
        "c:\\sonst"
    ]
    auto_filter(folders)