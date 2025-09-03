#!/usr/bin/env python3
import os
import argparse
import signal
import sys
import subprocess
from pathlib import Path
from ffmpeg import FFmpeg, Progress
import datetime

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

def get_video_files(directory, sort_largest_first=True):
    """Get all video files from the specified directory, ordered by size (largest first)."""
    video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg'}
    
    video_files = []
    for path in Path(directory).rglob('*'):
        if path.is_file() and path.suffix.lower() in video_extensions:
            # Get the file size using os.path.getsize
            file_size = os.path.getsize(path)
            # Store both the path and its size
            video_files.append((str(path.absolute()), file_size))
    
    # Sort by file size in descending order (largest first)
    video_files.sort(key=lambda x: x[1], reverse=sort_largest_first)
    
    # Return just the file paths, without the sizes
    return [file_path for file_path, _ in video_files]

def get_video_info(file_path):
    # Command to get video info in a single line
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-select_streams', 'v:0', 
        '-show_entries', 'stream=codec_name,width,height,r_frame_rate', 
        '-show_entries', 'format=duration,size', 
        '-of', 'csv=p=0:s=|', 
        file_path
    ]
    
    # Run the command and get the output
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Error running ffprobe: {result.stderr}")
    
    # Parse the output
    # Expected format: codec,width,height,fps_numerator/fps_denominator,duration,size
    output = result.stdout.strip()
    output = output.replace('\n', '|')
    parts = output.split('|')
    
    if len(parts) >= 6:
        codec = parts[0]
        width = int(parts[1])
        height = int(parts[2])
        resolution = f"{width}x{height}"
        
        # Parse framerate which is in format "num/den"
        fps_parts = parts[3].split('/')
        if len(fps_parts) == 2:
            framerate = float(fps_parts[0]) / float(fps_parts[1])
        else:
            framerate = float(fps_parts[0])
        
        duration = float(parts[4])
        size = int(parts[5])
        
        return {
            "codec": codec,
            "resolution": resolution,
            "framerate": framerate,
            "duration": duration,
            "size": size
        }
    else:
        raise Exception(f"Unexpected output format: {output}")


def convert(directory, outputdir, verbose=False, sort_biggest_first=True):
    """Calculate videohash for all video files and save to JSON."""
    # Get all video files
    video_files = get_video_files(directory, sort_biggest_first)
    total_files = len(video_files)
    print(f"Found {total_files} video files in {directory}")
    
    # Process each video file
    processed = 0

    ffmpeg_process = None  # temp process variable to check in the progress callback

    
    for i, file_path in enumerate(video_files):
        # Check if we should stop due to interruption
        if interrupted:
            break

        if not os.path.exists(file_path):
            print(f"File not found: {file_path}. Skipping...")
            continue

        current_size = os.path.getsize(file_path)    
        try:
            print(f"[{i+1}/{total_files}] Processing: {file_path}")
            
            # Get video duration
            video_info = get_video_info(file_path)
            duration = video_info['duration']
                        
            print(f"  Duration:{duration:.2f}s, Size:{current_size:,} Bytes, Codec:{video_info['codec']}, Resolution:{video_info['resolution']}, Framerate:{video_info['framerate']}fps" )             
            # To get the filename without extension from file_path:
            basename = os.path.splitext(os.path.basename(file_path))[0]
            output_file = os.path.join(outputdir, basename + ".mp4")

            ffmpeg = (
                FFmpeg()
                .option("y")
                .option("hide_banner")
                .option("hwaccel", "auto")
                .input(file_path)
                #.option("threads", "10")
                .output(
                    output_file,
                    vcodec="libvvenc",
                    preset="fast",
                    acodec="copy",
                )
            )

            @ffmpeg.on("progress")
            def on_progress(progress: Progress):
                eta = 0 if progress.speed == 0 else (duration-progress.time.seconds)/progress.speed
                time = datetime.timedelta(seconds=eta)
                print(f"ETA:{time}s | {100*progress.time.seconds/duration:.2f}% | size:{progress.size:,} | fps:{progress.fps} | bps:{progress.bitrate} | speed:{progress.speed}x", end='\r', flush=True)
                if interrupted and ffmpeg_process is not None:
                    ffmpeg_process.terminate()

            ffmpeg_process = ffmpeg
            ffmpeg.execute()
            ffmpeg_process = None
           

             # Compare durations and delete original if difference < 5 seconds
            try:
                orig_info = get_video_info(file_path)
                out_info = get_video_info(output_file)
                orig_duration = orig_info['duration']
                out_duration = out_info['duration']
                diff = abs(orig_duration - out_duration)
                if diff < 5:
                    os.remove(file_path)
                    print(f"\nDeleted original: {file_path} (duration diff: {diff:.2f}s)")
                else:
                    print(f"\nDuration difference too large: {file_path} ({orig_duration:.2f}s) vs {output_file} ({out_duration:.2f}s)")
            except Exception as e:
                print(f"\nError comparing durations or deleting file: {str(e)}")


            processed += 1


            
           
        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
        
    # Print summary
    print("\nSummary:")
    print(f"Total video files found: {total_files}")
    print(f"Files processed this run: {processed}")
   
    
    if interrupted:
        print("Process was interrupted. Progress has been saved.")
        print(f"To continue, run the script again with the same parameters.")
    else:
        print("All video files have been processed successfully.")

def main():
    parser = argparse.ArgumentParser(description='Calculate video hashes for all videos in a directory')
    parser.add_argument('directory', help='Directory containing video files')
    parser.add_argument('--output', '-o', default='02', 
                      help='Output directory')
    parser.add_argument('--verbose','-v', action='store_true', help="not used yet")
    parser.add_argument('--reverse','-r', action='store_false', help="revers precessing order, now starts with the smallest file first")
    
    args = parser.parse_args()
    
    # Validate directory
    if not os.path.isdir(args.directory):
        print(f"Error: {args.directory} is not a valid directory")
        sys.exit(1)

    # Validate directory
    if not os.path.isdir(args.output):
        print(f"Error: {args.output} is not a valid directory")
        sys.exit(1)
    
    print(f"Starting converting...")
    print(f"input : {args.directory}")
    print(f"output: {args.output}")
    
    convert(args.directory, args.output, verbose=args.verbose, sort_biggest_first=args.reverse)

if __name__ == "__main__":
    main()