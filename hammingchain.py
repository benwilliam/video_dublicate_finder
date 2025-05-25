import json
import argparse
import random

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
    parser.add_argument('--output', '-o', default=None, help='outputs to a file instead std output')
    
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

        chain = []
        startindex = random.randint(0, len(path_hash_list)-1)
        firstelement = path_hash_list.pop(startindex)
        print(f"Starting index: {startindex} | path: {firstelement[0]}")

        # Process until list is empty or has only one element
        while len(path_hash_list) > 1:
            
            first_path, first_hash = firstelement
            
            # Calculate distances between first element and all others
            distances = []
            for other_path, other_hash in path_hash_list[1:]:
                distance = hamming_distance(first_hash, other_hash)
                if distance < args.threshold:
                    distances.append((distance, other_path))

            index = 0
            distance = 99
            if len(distances) > 0:
                # Sort by distance
                distances.sort()
                # Get the first element
                distance = distances[0][0]
                # Find the index of the item with matching path
                index = next(i for i, item in enumerate(path_hash_list) if item[0] == distances[0][1])

                chain.append((first_path, distance))
            # Remove the item at that index
            firstelement = path_hash_list.pop(index)

        if args.output != None:
            with open(args.output, "w", encoding="utf-8") as f:
                if args.verbose:
                    for (path, distance) in chain: 
                        f.write(f"{path} ({distance})\n")
                else:
                    for (path, distance) in chain: 
                        f.write(f"{path}\n")
        else:
            if args.verbose:
                for (path, distance) in chain: 
                    print(f"{path} ({distance})")
            else:
                for (path, distance) in chain: 
                    print(f"{path}")
            
            # if args.verbose:
            #     # Print the first element and the top 3 closest matches (or fewer if less available)
            #     print(f"Reference: {first_path}")
            #     print("Top 3 closest matches:")
            #     for i, (distance, path) in enumerate(distances[:10], 1):
            #         print(f"{i}. Distance: {distance}, Path: {path}")
            #     print("-" * 80)
            # else:
            #     print(f"{first_path}")
            #     for i, (distance, path) in enumerate(distances[:10], 1):
            #         print(f"{path}")
            #     print(f"---")
            
    except FileNotFoundError:
        print(f"Error: File '{args.input}' not found.")
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in file '{args.input}'.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()