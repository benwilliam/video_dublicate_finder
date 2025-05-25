import json
import argparse

def hamming_distance(hex1, hex2):
    """Calculate Hamming distance between two hexadecimal strings."""
    x = int(hex1, 16) ^ int(hex2, 16)
    return bin(x).count('1')

def main():
    parser = argparse.ArgumentParser(description='Calculate hamming distance between hashes for all videos in a JSON file')
    parser.add_argument('--input', '-i', default='video_hashes.json', 
                      help='Input JSON file (default: video_hashes.json)')
    parser.add_argument('--threshold', '-t', type=int, default=5, 
                      help='Threshold for hamming distance (default: 5)')
    parser.add_argument('--verbose','-v', action='store_true')
    
    args = parser.parse_args()

    try:
        # Read JSON file
        with open(args.input, mode='r', encoding="utf8") as file:
            data = json.load(file)
        
        # Convert to list of (path, hash) tuples for easier manipulation
        # Extract hashes from the nested structure
        path_hash_list = []
        for path, details in data.items():
            if 'hash' in details:
                path_hash_list.append((path, details['hash']))
        
        # Process until list is empty or has only one element
        while len(path_hash_list) > 1:
            # Get the first element
            first_path, first_hash = path_hash_list[0]
            
            # Calculate distances between first element and all others
            distances = []
            for other_path, other_hash in path_hash_list[1:]:
                distance = hamming_distance(first_hash, other_hash)
                if distance < args.threshold:
                    distances.append((distance, other_path))
            
            # Remove the first element from the list
            path_hash_list.pop(0)

            if len(distances) == 0:
                continue

            # Sort by distance
            distances.sort()
            
            if args.verbose:
                # Print the first element and the top 3 closest matches (or fewer if less available)
                print(f"Reference: {first_path}")
                print("Top 3 closest matches:")
                for i, (distance, path) in enumerate(distances[:10], 1):
                    print(f"{i}. Distance: {distance}, Path: {path}")
                print("-" * 80)
            else:
                print(f"{first_path}")
                for i, (distance, path) in enumerate(distances[:10], 1):
                    print(f"{path}")
                print(f"---")
            
    except FileNotFoundError:
        print(f"Error: File '{args.input}' not found.")
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in file '{args.input}'.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()