#!/usr/bin/env python3
import os
import argparse
import signal
import sys
import subprocess
from pathlib import Path
from ffmpeg import FFmpeg, Progress
import datetime
import shutil
import glob
import time

# Global flag to handle interruptions
interrupted = False

# Handle keyboard interruptions (Ctrl+C)
def signal_handler(sig, frame):
    global interrupted
    if not interrupted:
        print("\nInterruption received. Checking state...")
        interrupted = True

# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Get terminal size
#try:
#    columns, rows = shutil.get_terminal_size()
#except:
columns, rows = 118, 24

def get_video_files(directory, sort_largest_first=True):
    """Get all video files from the specified directory, ordered by size (largest first).
       Ignores hidden directories (starting with .) and hidden files."""
    video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg'}
    
    video_files = []
    root_path = Path(directory).resolve()
    
    for path in root_path.rglob('*'):
        try:
            rel_path = path.relative_to(root_path)
        except ValueError:
            continue

        if any(part.startswith('.') for part in rel_path.parts):
            continue
            
        if path.is_file() and path.suffix.lower() in video_extensions:
            try:
                file_size = os.path.getsize(path)
                video_files.append((str(path.absolute()), file_size))
            except OSError:
                continue
    
    video_files.sort(key=lambda x: x[1], reverse=sort_largest_first)
    return [file_path for file_path, _ in video_files]

def get_video_info(file_path):
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-select_streams', 'v:0', 
        '-show_entries', 'stream=codec_name,width,height,r_frame_rate', 
        '-show_entries', 'format=duration,size', 
        '-of', 'csv=p=0:s=|', 
        file_path
    ]
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
         raise Exception("ffprobe not found. Please install ffmpeg.")

    if result.returncode != 0:
        return {"duration": 0, "size": 0, "codec": "unknown", "resolution": "unknown", "framerate": 0}
    
    output = result.stdout.strip()
    output = output.replace('\n', '|')
    parts = output.split('|')
    
    if len(parts) >= 6:
        codec = parts[0]
        width = int(parts[1])
        height = int(parts[2])
        resolution = f"{width}x{height}"
        
        fps_parts = parts[3].split('/')
        if len(fps_parts) == 2:
            framerate = float(fps_parts[0]) / float(fps_parts[1])
        else:
            framerate = float(fps_parts[0])
        
        try:
            duration = float(parts[4])
        except:
            duration = 0.0
            
        size = int(parts[5])
        
        return {
            "codec": codec,
            "resolution": resolution,
            "framerate": framerate,
            "duration": duration,
            "size": size
        }
    else:
        return {"duration": 0, "size": 0, "codec": "unknown", "resolution": "unknown", "framerate": 0}

def split_video(input_path, output_dir, duration, file_size):
    chunk_pattern = os.path.join(output_dir, "chunk_%03d.mp4")
    
    existing_chunks = glob.glob(os.path.join(output_dir, "chunk_*.mp4"))
    if existing_chunks:
        print(f"  Found {len(existing_chunks)} existing source chunks. Skipping split.")
        return

    target_size_bytes = 100 * 1024 * 1024 # 100 MB
    
    if file_size > 0 and duration > 0:
        segment_time = (target_size_bytes / file_size) * duration
        segment_time = max(10, segment_time)
    else:
        segment_time = 300 

    print(f"  Splitting file into ~100MB chunks (Segment time: {segment_time:.2f}s)...")
    
    cmd = [
        'ffmpeg',
        '-y', '-hide_banner', '-loglevel', 'error',
        '-i', input_path,
        '-c', 'copy',
        '-map', '0',
        '-f', 'segment',
        '-segment_format', 'mp4',
        '-segment_time', str(segment_time),
        '-segment_start_number', '1',
        '-reset_timestamps', '1', 
        chunk_pattern
    ]
    subprocess.run(cmd, check=True)

def merge_videos(chunk_list, output_file):
    if not chunk_list:
        raise Exception("No chunks to merge!")

    # 1. Determine the directory where the chunks are located
    chunk_dir = os.path.dirname(os.path.abspath(chunk_list[0]))
    
    # 2. Create the concat file INSIDE that directory
    concat_file_path = os.path.join(chunk_dir, "concat_list.txt")
    
    with open(concat_file_path, 'w', encoding='utf-8') as f:
        for chunk in chunk_list:
            # 3. Use ONLY the filename (relative path)
            filename = os.path.basename(chunk)
            
            # 4. Escape single quotes for FFmpeg syntax (Dad's.mp4 -> Dad'\''s.mp4)
            safe_filename = filename.replace("'", "'\\''")
            
            f.write(f"file '{safe_filename}'\n")
    
    print(f"  Merging {len(chunk_list)} chunks into final video...")
    
    cmd = [
        'ffmpeg',
        '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'concat',
        '-safe', '0',
        '-i', concat_file_path,
        '-c', 'copy',
        output_file
    ]
    
    try:
        # 5. Run subprocess. FFmpeg resolves relative paths in concat files 
        # relative to the location of the concat file itself.
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"  Merge failed: {e}")
        raise e
    finally:
        if os.path.exists(concat_file_path):
            try:
                os.remove(concat_file_path)
            except:
                pass

def convert(directory, outputdir, verbose=False, sort_biggest_first=True, progress_update_interval=1):
    video_files = get_video_files(directory, sort_biggest_first)
    total_files = len(video_files)
    print(f"Found {total_files} video files in {directory}")
    
    processed_count = 0
    ffmpeg_process = None 
    last_file_locked = None

    for i, file_path in enumerate(video_files):
        # Only break outer loop if interrupted AND we aren't in the middle of finishing the last chunk
        if interrupted:
            print("Process stopped by user.")
            break

        lock_file = file_path + ".lock"
        if os.path.exists(lock_file):
            print(f"Skipping (lock exists): {file_path}")
            continue

        if not os.path.exists(file_path):
            continue

        try:
            with open(lock_file, "w") as f:
                last_file_locked = lock_file
        except Exception as e:
            print(f"Could not create lock file: {str(e)}")
            continue

        current_size = os.path.getsize(file_path)    
        try:
            print(f"[{i+1}/{total_files}] Processing: {file_path}")
            
            video_info = get_video_info(file_path)
            print(f"  Duration:{video_info['duration']:.2f}s, Size:{current_size:,} Bytes, Codec:{video_info['codec']}, Resolution:{video_info['resolution']}" )             
            
            basename = os.path.splitext(os.path.basename(file_path))[0]
            final_output_file = os.path.join(outputdir, basename + ".mp4")
            
            input_dir_path = os.path.dirname(file_path)
            input_work_dir = os.path.join(input_dir_path, f".tmp_chunks_{basename}")
            os.makedirs(input_work_dir, exist_ok=True)

            output_work_dir = os.path.join(outputdir, f".tmp_encoded_{basename}")
            os.makedirs(output_work_dir, exist_ok=True)

            # --- 1. SPLIT ---
            split_video(file_path, input_work_dir, video_info['duration'], current_size)
            
            if interrupted: break

            # --- SAFE RESUME CHECK ---
            existing_encoded = sorted(glob.glob(os.path.join(output_work_dir, "*_encoded.mp4")))
            if existing_encoded:
                last_encoded_chunk = existing_encoded[-1]
                print(f"  [Resume Check] Deleting last encoded chunk: {os.path.basename(last_encoded_chunk)}")
                try: os.remove(last_encoded_chunk)
                except OSError: pass
            
            # --- 2. TRANSCODE ---
            source_chunks = sorted(glob.glob(os.path.join(input_work_dir, "chunk_*.mp4")))
            encoded_chunks_list = []
            
            completed_chunks_in_this_loop = True

            for c_idx, chunk_path in enumerate(source_chunks):
                is_last_chunk = (c_idx == len(source_chunks) - 1)
                
                # Handling Interrupts in loop
                if interrupted:
                    if is_last_chunk:
                        print("\n  ! Interrupt received, but this is the LAST chunk. Finishing file processing...")
                    else:
                        completed_chunks_in_this_loop = False
                        break
                
                chunk_name = os.path.basename(chunk_path)
                encoded_chunk_path = os.path.join(output_work_dir, f"{os.path.splitext(chunk_name)[0]}_encoded.mp4")
                encoded_chunks_list.append(encoded_chunk_path)

                if os.path.exists(encoded_chunk_path):
                    if os.path.getsize(encoded_chunk_path) > 1024:
                        print(f"  [Chunk {c_idx+1}/{len(source_chunks)}] Already encoded. Skipping.")
                        continue
                
                chunk_info = get_video_info(chunk_path)
                chunk_duration = chunk_info['duration']

                print(f"  [Chunk {c_idx+1}/{len(source_chunks)}] Encoding...")

                # Define the FFmpeg task
                def run_ffmpeg_task():
                    nonlocal ffmpeg_process
                    ffmpeg = (
                        FFmpeg()
                        .option("y")
                        .option("hide_banner")
                        .option("hwaccel", "auto")
                        .input(chunk_path)
                        .output(
                            encoded_chunk_path,
                            vcodec="libvvenc",
                            preset="fast",
                            acodec="copy",
                        )
                    )

                    progress_counter = [0]
                    lastProgress = None
                    @ffmpeg.on("progress")
                    def on_progress(progress: Progress):
                        progress_counter[0] += 1
                        lastProgress = progress
                        if progress_counter[0] % progress_update_interval != 0:
                            return
                        
                        chunk_eta = 0 if progress.speed == 0 else (chunk_duration-progress.time.seconds)/progress.speed
                        time_obj = datetime.timedelta(seconds=chunk_eta)
                        
                        progress_str = (
                            f"    Chunk ETA:{str(time_obj).split('.')[0]}s | {100 * progress.time.seconds / chunk_duration:.2f}% | "
                            f"size:{progress.size//1024:,}kB | ETA size:{int((chunk_duration*progress.bitrate)/8):,}kB | fps:{progress.fps:.2f} | bps:{progress.bitrate} | speed:{progress.speed:.2f}x"
                        )
                        print('\r' + progress_str.ljust(columns)[:columns], end='', flush=True)
                        
                        # Only terminate if it is NOT the last chunk
                        if interrupted and ffmpeg_process is not None and not is_last_chunk:
                            ffmpeg_process.terminate()

                    ffmpeg_process = ffmpeg
                    ffmpeg.execute()

                    #only for my own peace print one last line
                    outputsize = os.path.getsize(encoded_chunk_path) if os.path.exists(encoded_chunk_path) else 0
                    progress_str = (
                        f"    Chunk ETA:0:00:00s | 100.00% | size:{outputsize//1024:,}kB | ETA size:{outputsize//1024:,}kB | fps:00.00 | bps:00.00 | speed:00.00x      "
                    )
                    print('\r' + progress_str.ljust(columns)[:columns], end='', flush=True)

                # Execution Logic with Retry for Last Chunk
                try:
                    run_ffmpeg_task()
                except Exception as e:
                    # If interrupted during the last chunk, the OS signal likely killed the subprocess.
                    # We catch it, print, and RETRY immediately to finish the job.
                    if interrupted and is_last_chunk:
                         print("\n  ! Interrupted during last chunk execution. Retrying to finalize file...")
                         try:
                             ffmpeg_process = None # Reset
                             run_ffmpeg_task()
                         except Exception as e2:
                             print(f"\n  Failed to finish last chunk despite retry: {e2}")
                             completed_chunks_in_this_loop = False
                             break
                    elif interrupted:
                        # Normal interruption in middle of list
                        print("\nEncoding interrupted.")
                        if os.path.exists(encoded_chunk_path):
                            try: os.remove(encoded_chunk_path)
                            except: pass
                        completed_chunks_in_this_loop = False
                        break
                    else:
                        print(f"\nError encoding chunk {chunk_path}: {e}")
                        raise e
                
                ffmpeg_process = None
                print("") 

            # Break outer loop if we didn't finish the chunks (and weren't saved by the last-chunk logic)
            if interrupted and not completed_chunks_in_this_loop:
                break

            # --- 3. MERGE ---
            if encoded_chunks_list and completed_chunks_in_this_loop:
                merge_videos(encoded_chunks_list, final_output_file)

                # --- 4. CLEANUP & VERIFY ---
                try:
                    orig_duration = get_video_info(file_path)['duration']
                    out_duration = get_video_info(final_output_file)['duration']
                    diff = abs(orig_duration - out_duration)
                    
                    if diff < 10:
                        os.remove(file_path)
                        print(f"Deleted original: {file_path} (diff: {diff:.2f}s)")
                        
                        print("Cleaning up temp directories...")
                        shutil.rmtree(input_work_dir)
                        shutil.rmtree(output_work_dir)
                    else:
                        print(f"\nDuration mismatch! ({orig_duration:.2f}s vs {out_duration:.2f}s) Kept temp files.")
                except Exception as e:
                    print(f"\nError in cleanup: {str(e)}")
            elif not encoded_chunks_list:
                 print("Error: No chunks were encoded.")
            
            processed_count += 1
            
            # If interrupted was set during the last chunk, we finished that file.
            # Now we break the loop to stop processing the *next* file.
            if interrupted:
                print("Finished last file completion. Stopping script now.")
                break

        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            try:
                if os.path.exists(lock_file):
                    os.remove(lock_file)
            except Exception as e:
                print(f"Could not remove lock file: {str(e)}")
    
    print("\nSummary:")
    print(f"Processed: {processed_count}")
   
    if interrupted:
        print("Script finish (Interrupted).")
        if last_file_locked and os.path.exists(last_file_locked):
            try: os.remove(last_file_locked)
            except: pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', help='Directory containing video files')
    parser.add_argument('--output', '-o', default='02', help='Output directory')
    parser.add_argument('--verbose','-v', action='store_true')
    parser.add_argument('--reverse','-r', action='store_false')
    parser.add_argument('--progress-interval', type=int, default=1)
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.directory):
        print(f"Error: {args.directory} is not a valid directory")
        sys.exit(1)

    if not os.path.exists(args.output):
        os.makedirs(args.output)
    
    convert(args.directory, args.output, verbose=args.verbose, sort_biggest_first=args.reverse, progress_update_interval=args.progress_interval)

if __name__ == "__main__":
    main()