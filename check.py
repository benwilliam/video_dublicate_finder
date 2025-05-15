import json
import os
import sys
import pathlib

def check_files(json_path):
    """
    Check if files in the JSON exist and have the correct size.
    
    Args:
        json_path (str): Path to the JSON file containing file information
    
    Returns:
        tuple: Original file data, valid entries dictionary, and statistics
    """
    # Read the JSON file
    try:
        with open(json_path, mode='r', encoding="utf8") as f:
            file_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: JSON file '{json_path}' not found.")
        return None, {}, (0, 0, 0)
    except json.JSONDecodeError:
        print(f"Error: '{json_path}' is not a valid JSON file.")
        return None, {}, (0, 0, 0)
    
    # Create a new dictionary for valid entries
    valid_entries = {}
    
    # Counters for statistics
    matching_count = 0
    missing_count = 0
    size_mismatch_count = 0
    
    # Check each file in the JSON
    for file_path, info in file_data.items():
        # Get the expected size from the JSON data
        expected_size = info.get('size_bytes')
        
        if expected_size is None:
            print(f"Warning: No size information for '{file_path}'")
            continue
        
        # Check if the file exists
        if os.path.exists(file_path):
            # Get the actual file size
            actual_size = os.path.getsize(file_path)
            
            # Compare sizes
            if actual_size == expected_size:
                # Add this entry to the valid entries dictionary
                valid_entries[file_path] = info
                matching_count += 1
            else:
                size_mismatch_count += 1
        else:
            missing_count += 1
    
    return file_data, valid_entries, (matching_count, missing_count, size_mismatch_count)

def save_valid_entries(valid_entries, original_json_path):
    """
    Save valid entries to a new JSON file.
    
    Args:
        valid_entries (dict): Dictionary of valid file entries
        original_json_path (str): Path to the original JSON file
    
    Returns:
        str: Path to the saved JSON file
    """
    # Create output filename based on the input filename
    input_path = pathlib.Path(original_json_path)
    output_path = input_path.with_stem(f"{input_path.stem}_valid")
    
    # Save the valid entries to the new JSON file
    with open(output_path, 'w') as f:
        json.dump(valid_entries, f, indent=2)
    
    return str(output_path)

def print_results(stats, output_path):
    """Print the results of the file check."""
    matching_count, missing_count, size_mismatch_count = stats
    total_count = matching_count + missing_count + size_mismatch_count
    
    print("\n=== FILE CHECK RESULTS ===\n")
    print(f"Total files processed: {total_count}")
    print(f"Files with matching size: {matching_count}")
    print(f"Missing files: {missing_count}")
    print(f"Files with size mismatches: {size_mismatch_count}")
    print(f"\nValid entries saved to: {output_path}")

def main():
    # Check if a JSON file path was provided as an argument
    if len(sys.argv) != 2:
        print("Usage: python file_size_checker.py <path_to_json_file>")
        sys.exit(1)
    
    json_path = sys.argv[1]
    original_data, valid_entries, stats = check_files(json_path)
    
    if original_data is None:
        sys.exit(1)
        
    output_path = save_valid_entries(valid_entries, json_path)
    print_results(stats, output_path)

if __name__ == "__main__":
    main()