#!/usr/bin/env python3
import os
import json
import argparse
import signal
import sys
import subprocess
from pathlib import Path
from videohash import VideoHash

# Global flag to handle interruptions
interrupted = False

# Handle keyboard interruptions (Ctrl+C)
def signal_handler(sig, frame):
    global interrupted
    print("\nInterruption received. Saving progress and exiting gracefully...")
    interrupted = True

# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_video_files(directory):
    """Get all video files from the specified directory."""
    video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg'}
    
    video_files = []
    for path in Path(directory).rglob('*'):
        if path.is_file() and path.suffix.lower() in video_extensions:
            video_files.append(str(path.absolute()))
    
    return video_files

def get_video_duration(file_path):
    """Get the duration of a video file in seconds using ffprobe."""
    try:
        cmd = [
            'ffprobe', 
            '-v', 'error', 
            '-show_entries', 'format=duration', 
            '-of', 'json',
            file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"ffprobe error: {result.stderr}")
        
        # Parse the JSON output
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        
        return duration
    except Exception as e:
        print(f"Error getting video duration for {file_path}: {str(e)}")
        return 0

def calculate_frame_interval(duration, max_frames=63):
    """Calculate the frame interval to use at most max_frames frames."""
    if duration <= 0:
        return 1  # Default if duration is unknown
    
    # Calculate interval to have max_frames evenly distributed
    # Add a small buffer to ensure we don't exceed max_frames
    return duration / (max_frames - 0.5)

def load_existing_data(output_file):
    """Load existing hash data if available."""
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error reading {output_file}. Starting with empty data.")
    return {}

def save_data(data, output_file):
    """Save hash data to JSON file."""
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

def find_moved_file(file_path, hash_data):
    """
    Check if a file has been moved by comparing filename and size with existing entries.
    Returns the existing hash entry if found, None otherwise.
    """
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)
    
    # Look for matching filename and size in existing data
    for existing_path, data in hash_data.items():
        existing_name = os.path.basename(existing_path)
        existing_size = data.get("size_bytes", 0)
        
        if existing_name == file_name and existing_size == file_size:
            # File likely moved from existing_path to file_path
            return existing_path, data
    
    return None, None

def calculate_hashes(directory, output_file):
    """Calculate videohash for all video files and save to JSON."""
    # Get all video files
    video_files = get_video_files(directory)
    total_files = len(video_files)
    print(f"Found {total_files} video files in {directory}")
    
    # Load existing data if available
    hash_data = load_existing_data(output_file)
    
    # Process each video file
    processed = 0
    skipped = 0
    reused = 0
    
    for i, file_path in enumerate(video_files):
        # Check if we should stop due to interruption
        if interrupted:
            break
            
         # Check if path exists in hash data
        if file_path in hash_data:
            # Verify the file size hasn't changed
            current_size = os.path.getsize(file_path)
            stored_size = hash_data[file_path].get("size_bytes", 0)
            
            if current_size == stored_size:
                # File unchanged, skip processing
                skipped += 1
                print(f"[{i+1}/{total_files}] Skipping already processed file: {file_path}")
                continue
            else:
                # File size changed, needs rehashing
                print(f"[{i+1}/{total_files}] File size changed for: {file_path}")
                print(f"  Previous size: {stored_size} bytes, Current size: {current_size} bytes")
                print(f"  Rehashing file...")
                # Continue with processing to recalculate hash
        else:
            # Check if file was moved (same name and size exists in database)
            original_path, existing_data = find_moved_file(file_path, hash_data)
            if original_path and existing_data:
                # File was moved, reuse the hash
                print(f"[{i+1}/{total_files}] File appears to be moved from: {original_path}")
                print(f"  Reusing hash for: {file_path}")
                
                # Get file size in bytes
                file_size = os.path.getsize(file_path)
                
                # Copy existing hash data for the new path
                hash_data[file_path] = {
                    "hash": existing_data["hash"],
                    "size_bytes": file_size,
                }
                reused += 1
                continue
        
        try:
            print(f"[{i+1}/{total_files}] Processing: {file_path}")
            
            # Get video duration
            duration = get_video_duration(file_path)
            
            # Calculate appropriate frame interval for max 10 frames
            frame_interval = calculate_frame_interval(duration, max_frames=63)
            if frame_interval == 0:
                frame_interval = 63
            frame_interval = 1/frame_interval
            
            print(f"  Duration: {duration:.2f}s, Frame interval: {frame_interval:.4f}/s")
            
            # Calculate the video hash with dynamic frame interval
            vh = VideoHash(path=file_path, frame_interval=frame_interval, storage_path="r:\\")
            hash_value = vh.hash_hex
            vh.delete_storage_path()
            #print(f"storage path: {(vh.storage_path)} ")
            
            # Get file size in bytes
            file_size = os.path.getsize(file_path)
            
            # Store result
            hash_data[file_path] = {
                "hash": hash_value,
                "size_bytes": file_size,
            }
            processed += 1
            
            # Save periodically (every 5 files)
            if (processed + reused) % 5 == 0:
                save_data(hash_data, output_file)
                print(f"Progress saved. Processed {processed} files, reused {reused} hashes so far.")
                
        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
    
    # Final save
    save_data(hash_data, output_file)
    
    # Print summary
    print("\nSummary:")
    print(f"Total video files found: {total_files}")
    print(f"Files processed this run: {processed}")
    print(f"Files with reused hashes (moved files): {reused}")
    print(f"Files skipped (already processed): {skipped}")
    print(f"Total hashes in database: {len(hash_data)}")
    
    if interrupted:
        print("Process was interrupted. Progress has been saved.")
        print(f"To continue, run the script again with the same parameters.")
    else:
        print("All video files have been processed successfully.")

def main():
    parser = argparse.ArgumentParser(description='Calculate video hashes for all videos in a directory')
    parser.add_argument('directory', help='Directory containing video files')
    parser.add_argument('--output', '-o', default='video_hashes.json', 
                      help='Output JSON file (default: video_hashes.json)')
    
    args = parser.parse_args()
    
    # Validate directory
    if not os.path.isdir(args.directory):
        print(f"Error: {args.directory} is not a valid directory")
        sys.exit(1)
    
    print(f"Starting video hash calculation...")
    print(f"Directory: {args.directory}")
    print(f"Output file: {args.output}")
    
    calculate_hashes(args.directory, args.output)

if __name__ == "__main__":
    main()