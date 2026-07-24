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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.progress import (
    Progress as RichProgress,
    BarColumn,
    TextColumn,
    TaskProgressColumn,
    SpinnerColumn,
    TimeElapsedColumn,
)
from rich.console import Console
from rich.text import Text

_console = Console()

# Global flag to handle interruptions
interrupted = False

# Thread-safe registry of all active ffmpeg processes
_active_ffmpeg_lock = threading.Lock()
_active_ffmpeg_processes = set()

def _register_ffmpeg(proc):
    with _active_ffmpeg_lock:
        _active_ffmpeg_processes.add(proc)

def _unregister_ffmpeg(proc):
    with _active_ffmpeg_lock:
        _active_ffmpeg_processes.discard(proc)

def _terminate_all_ffmpeg():
    with _active_ffmpeg_lock:
        procs = list(_active_ffmpeg_processes)
    for proc in procs:
        try:
            proc.terminate()
        except Exception:
            pass

# Handle keyboard interruptions (Ctrl+C)
def signal_handler(sig, frame):
    global interrupted
    if not interrupted:
        _console.print("\n[bold red]Interruption received. Stopping active encoders...[/bold red]")
        interrupted = True
        _terminate_all_ffmpeg()

# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

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

def convert(directory, outputdir, verbose=False, sort_biggest_first=True, progress_update_interval=1, parallel=1, nochunks=False):
    video_files = get_video_files(directory, sort_biggest_first)
    total_files = len(video_files)
    _console.print(f"Found [bold]{total_files}[/bold] video files in [dim]{directory}[/dim]")
    if nochunks:
        _console.print("[cyan]Mode: whole-file transcoding (--nochunks)[/cyan]")
    elif parallel > 1:
        _console.print(f"[cyan]Mode: chunk transcoding, up to [bold]{parallel}[/bold] parallel[/cyan]")
    
    processed_count = 0
    last_file_locked = None

    for i, file_path in enumerate(video_files):
        # Only break outer loop if interrupted AND we aren't in the middle of finishing the last chunk
        if interrupted:
            _console.print("[yellow]Process stopped by user.[/yellow]")
            break

        lock_file = file_path + ".lock"
        if os.path.exists(lock_file):
            _console.print(f"[dim]Skipping (lock exists): {file_path}[/dim]")
            continue

        if not os.path.exists(file_path):
            continue

        try:
            with open(lock_file, "w") as f:
                last_file_locked = lock_file
        except Exception as e:
            _console.print(f"[red]Could not create lock file: {str(e)}[/red]")
            continue

        current_size = os.path.getsize(file_path)    
        try:
            _console.print(f"\n[bold][{i+1}/{total_files}][/bold] {file_path}")
            
            video_info = get_video_info(file_path)
            _console.print(
                f"  [dim]Duration:[/dim]{video_info['duration']:.2f}s  "
                f"[dim]Size:[/dim]{current_size//1048576:,}MB  "
                f"[dim]Codec:[/dim]{video_info['codec']}  "
                f"[dim]Resolution:[/dim]{video_info['resolution']}  "
                f"[dim]FPS:[/dim]{video_info['framerate']:.2f}"
            )
            
            basename = os.path.splitext(os.path.basename(file_path))[0]
            final_output_file = os.path.join(outputdir, basename + ".mp4")
            
            input_dir_path = os.path.dirname(file_path)
            input_work_dir = os.path.join(input_dir_path, f".tmp_chunks_{basename}")
            output_work_dir = os.path.join(outputdir, f".tmp_encoded_{basename}")

            # ── Build rich progress bar (shared by both modes) ──────────────
            file_progress = RichProgress(
                SpinnerColumn(spinner_name="dots", finished_text="[green]●[/green]"),
                TextColumn("[bold]{task.description}[/bold]", justify="right"),
                BarColumn(bar_width=28, complete_style="green", pulse_style="cyan"),
                TaskProgressColumn(),
                TextColumn("[cyan]ETA {task.fields[eta]}[/cyan]"),
                TextColumn("[yellow]{task.fields[speed]}x[/yellow]"),
                TextColumn("[magenta]{task.fields[fps]} fps[/magenta]"),
                TextColumn("[dim]{task.fields[size]}[/dim]"),
                console=_console,
                transient=False,
            )

            def make_ffmpeg(input_path, output_path):
                return (
                    FFmpeg()
                    .option("y")
                    .option("hide_banner")
                    .option("hwaccel", "auto")
                    .input(input_path)
                    .output(
                        output_path,
                        vf="fps=fps=24:round=up",
                        vcodec="libvvenc",
                        preset="fast",
                        acodec="copy",
                    )
                )

            def transcode_one(label, input_path, output_path, total_dur, rich_progress):
                """Generic transcoder for one input → one output. Returns True on success."""
                task_id = rich_progress.add_task(
                    label, total=max(total_dur, 1),
                    eta="--:--:--", speed="-.--", fps="-.--", size="-"
                )
                ffmpeg_ref = [None]

                def run():
                    ffmpeg = make_ffmpeg(input_path, output_path)
                    progress_counter = [0]

                    @ffmpeg.on("progress")
                    def on_progress(progress: Progress):
                        progress_counter[0] += 1
                        if progress_counter[0] % progress_update_interval != 0:
                            return
                        elapsed_s = progress.time.seconds
                        remaining_s = (
                            0 if progress.speed == 0 or total_dur == 0
                            else (total_dur - elapsed_s) / progress.speed
                        )
                        rich_progress.update(
                            task_id,
                            completed=elapsed_s,
                            eta=str(datetime.timedelta(seconds=int(remaining_s))),
                            speed=f"{progress.speed:.2f}",
                            fps=f"{progress.fps:.1f}",
                            size=f"{progress.size // 1024:,} kB",
                        )
                        if interrupted and ffmpeg_ref[0] is not None:
                            ffmpeg_ref[0].terminate()

                    ffmpeg_ref[0] = ffmpeg
                    _register_ffmpeg(ffmpeg)
                    try:
                        ffmpeg.execute()
                    finally:
                        _unregister_ffmpeg(ffmpeg)

                try:
                    run()
                except Exception as e:
                    if interrupted:
                        rich_progress.update(task_id, description=f"[red]✗ {label} interrupted[/red]")
                        rich_progress.stop_task(task_id)
                        if os.path.exists(output_path):
                            try:
                                os.remove(output_path)
                            except Exception:
                                pass
                        return False
                    else:
                        rich_progress.update(task_id, description=f"[red]✗ {label} ERROR[/red]")
                        rich_progress.stop_task(task_id)
                        raise

                out_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                rich_progress.update(
                    task_id,
                    completed=max(total_dur, 1),
                    description=f"[green]✓ {label}[/green]",
                    eta="0:00:00", speed="done", fps="",
                    size=f"{out_size // 1024:,} kB",
                )
                return True

            # ── MODE: --nochunks  (transcode whole file directly) ───────────
            if nochunks:
                completed_chunks_in_this_loop = True
                with file_progress:
                    ok = transcode_one(
                        "Full file", file_path, final_output_file,
                        video_info['duration'], file_progress
                    )
                if not ok:
                    completed_chunks_in_this_loop = False

                if completed_chunks_in_this_loop:
                    try:
                        orig_duration = video_info['duration']
                        out_duration = get_video_info(final_output_file)['duration']
                        diff = abs(orig_duration - out_duration)
                        if diff < 10:
                            os.remove(file_path)
                            _console.print(f"[dim]  Deleted original:[/dim] {file_path} [dim](diff: {diff:.2f}s)[/dim]")
                        else:
                            _console.print(f"[bold red]  Duration mismatch! ({orig_duration:.2f}s vs {out_duration:.2f}s) Kept original.[/bold red]")
                    except Exception as e:
                        _console.print(f"[red]  Error in cleanup: {str(e)}[/red]")

                processed_count += 1
                if interrupted:
                    _console.print("[yellow]  Finished current file. Stopping script now.[/yellow]")
                    break
                continue  # skip the chunk-based code below

            # ── MODE: chunk-based (split → transcode → merge) ───────────────
            os.makedirs(input_work_dir, exist_ok=True)
            os.makedirs(output_work_dir, exist_ok=True)

            # --- 1. SPLIT ---
            split_video(file_path, input_work_dir, video_info['duration'], current_size)

            if interrupted: break

            # --- 2. TRANSCODE ---
            source_chunks = sorted(glob.glob(os.path.join(input_work_dir, "chunk_*.mp4")))
            encoded_chunks_list = []
            completed_chunks_in_this_loop = True

            # Build work list, skipping already-encoded chunks
            work_items = []
            for c_idx, chunk_path in enumerate(source_chunks):
                chunk_name = os.path.basename(chunk_path)
                encoded_chunk_path = os.path.join(output_work_dir, f"{os.path.splitext(chunk_name)[0]}_encoded.mp4")
                encoded_chunks_list.append(encoded_chunk_path)

                if os.path.exists(encoded_chunk_path):
                    src_duration = get_video_info(chunk_path)['duration']
                    dst_duration = get_video_info(encoded_chunk_path)['duration']
                    duration_diff = abs(src_duration - dst_duration)
                    if src_duration > 0 and duration_diff <= 1.0:
                        _console.print(f"  [dim][Chunk {c_idx+1}/{len(source_chunks)}] Already encoded (duration match: {src_duration:.2f}s ≈ {dst_duration:.2f}s). Skipping.[/dim]")
                        continue
                    else:
                        _console.print(f"  [yellow][Chunk {c_idx+1}/{len(source_chunks)}] Duration mismatch (src:{src_duration:.2f}s vs dst:{dst_duration:.2f}s). Re-encoding...[/yellow]")

                work_items.append((c_idx, chunk_path, encoded_chunk_path))

            def transcode_chunk(c_idx, chunk_path, encoded_chunk_path, rich_progress):
                """Transcode a single chunk. Returns True on success, False on failure/interrupt."""
                total_chunks = len(source_chunks)
                chunk_info = get_video_info(chunk_path)
                label = f"Chunk {c_idx+1:>{len(str(total_chunks))}}/{total_chunks}"
                return transcode_one(label, chunk_path, encoded_chunk_path, chunk_info['duration'], rich_progress)

            # --- Run chunks: parallel or sequential ---
            with file_progress:
                if parallel <= 1 or len(work_items) <= 1:
                    for c_idx, chunk_path, encoded_chunk_path in work_items:
                        if interrupted:
                            completed_chunks_in_this_loop = False
                            break
                        ok = transcode_chunk(c_idx, chunk_path, encoded_chunk_path, file_progress)
                        if not ok:
                            completed_chunks_in_this_loop = False
                            break
                else:
                    with ThreadPoolExecutor(max_workers=parallel) as executor:
                        futures = {
                            executor.submit(transcode_chunk, c_idx, chunk_path, encoded_chunk_path, file_progress): (c_idx, chunk_path)
                            for c_idx, chunk_path, encoded_chunk_path in work_items
                            if not interrupted
                        }
                        for future in as_completed(futures):
                            c_idx, chunk_path = futures[future]
                            try:
                                ok = future.result()
                            except Exception as e:
                                _console.print(f"[red]  [Chunk {c_idx+1}/{len(source_chunks)}] Unhandled error: {e}[/red]")
                                ok = False
                            if not ok:
                                completed_chunks_in_this_loop = False
                                for f in futures:
                                    f.cancel()
                                _terminate_all_ffmpeg()

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
                        _console.print(f"[dim]  Deleted original:[/dim] {file_path} [dim](diff: {diff:.2f}s)[/dim]")
                        _console.print("  [dim]Cleaning up temp directories...[/dim]")
                        shutil.rmtree(input_work_dir)
                        shutil.rmtree(output_work_dir)
                    else:
                        _console.print(f"[bold red]  Duration mismatch! ({orig_duration:.2f}s vs {out_duration:.2f}s) Kept temp files.[/bold red]")
                except Exception as e:
                    _console.print(f"[red]  Error in cleanup: {str(e)}[/red]")
            elif not encoded_chunks_list:
                _console.print("[red]  Error: No chunks were encoded.[/red]")
            
            processed_count += 1
            
            if interrupted:
                _console.print("[yellow]  Finished current file. Stopping script now.[/yellow]")
                break

        except Exception as e:
            _console.print(f"[bold red]Error processing {file_path}: {str(e)}[/bold red]")
            import traceback
            traceback.print_exc()
        finally:
            try:
                if os.path.exists(lock_file):
                    os.remove(lock_file)
            except Exception as e:
                _console.print(f"[red]Could not remove lock file: {str(e)}[/red]")
    
    _console.print(f"\n[bold]Summary:[/bold] Processed [green]{processed_count}[/green] file(s).")
   
    if interrupted:
        _console.print("[yellow]Script finished (interrupted).[/yellow]")
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
    parser.add_argument('--parallel', '-p', type=int, default=1, metavar='N',
                        help='Number of chunks to transcode simultaneously (default: 1)')
    parser.add_argument('--nochunks', action='store_true',
                        help='Transcode each file as a whole instead of splitting into chunks')
    
    args = parser.parse_args()

    if args.parallel < 1:
        _console.print("[red]Error: --parallel must be at least 1[/red]")
        sys.exit(1)

    if args.nochunks and args.parallel > 1:
        _console.print("[yellow]Warning: --parallel has no effect when --nochunks is set (only one file is transcoded at a time).[/yellow]")
    
    if not os.path.isdir(args.directory):
        _console.print(f"[red]Error: {args.directory} is not a valid directory[/red]")
        sys.exit(1)

    if not os.path.exists(args.output):
        os.makedirs(args.output)
    
    convert(args.directory, args.output, verbose=args.verbose, sort_biggest_first=args.reverse,
            progress_update_interval=args.progress_interval, parallel=args.parallel,
            nochunks=args.nochunks)

if __name__ == "__main__":
    main()