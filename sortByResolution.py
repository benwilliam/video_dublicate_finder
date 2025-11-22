import os
import argparse
import signal
import sys
import subprocess
from pathlib import Path
from ffmpeg import FFmpeg, Progress
import datetime
import shutil
import re
import av

def build_file_cache(folders):
    # Common video file extensions
    video_extensions = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', 
        '.flv', '.webm', '.m4v', '.mpg', '.mpeg',
        '.3gp', '.ts', '.mts', '.m2ts'
    }
    
    file_cache = []
    for folder in folders:
        for root, _, files in os.walk(folder):
            for file in files:
                # Check if file extension (lowercase) matches any video extension
                if os.path.splitext(file.lower())[1] in video_extensions:
                    file_cache.append(os.path.join(root, file))
                    
    print(f"Total video files found: {len(file_cache)}")
    return file_cache


def get_video_resolution_av(file_path):
    import av
    try:
        with av.open(file_path) as container:
            stream = container.streams.video[0]
            #return stream.width, stream.height
            return {
            "width":stream.width,
            "height":stream.height,
            "pixels":(stream.width*stream.height),
            "filepath":file_path
        }
    except Exception as e:
        raise Exception(f"Error reading video: {str(e)}")
    
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
            "width":width,
            "height":height,
            "pixels":(width*height),
            "framerate": framerate,
            "duration": duration,
            "size": size,
            "filepath":file_path
        }
    else:
        raise Exception(f"Unexpected output format: {output}")


if __name__ == "__main__":
    # Example usage:
    # folders = ["C:\\Videos", "D:\\Movies"]
    # filter_str = "abcd"
    # find_files_by_name(folders, filter_str)

    # For demonstration, you can modify these values:
    folders = [
        "c:\\sonst",
        #"d:\\jd",
        #"d:\\02",
        #"d:\\done",
        "p:\\sonst"
    ]
    foundFiles = build_file_cache(folders)
    filetable =[]
    for index, filepath in enumerate(foundFiles):
        try:
            fileinfo = get_video_resolution_av(filepath)
            filetable.append(fileinfo)
            print(f" {index + 1} / {len(foundFiles)} \r", end="")
        except Exception as e:
            print(f"\nError in file: {filepath} : {str(e)}")

     # Sort the filetable by pixels (resolution) in descending order
    filetable.sort(key=lambda x: x['pixels'])
    
    with open("orderedbypixels.txt", "w", encoding="utf-8") as f:
        for entry in filetable:
            f.write(f"{entry['filepath']}\n") #| {entry['resolution']} | {entry['framerate']:.2f} fps | {entry['duration']:.2f} sec | {entry['size']//(1024*1024)} MB\n")

    print("File list sorted by resolution written to 'orderedbypixels.txt'")

