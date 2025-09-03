import json
import sys

def extract_paths_from_json(input_file, output_file):
    """
    Extract file paths from JSON and write them to a text file.
    
    Args:
        input_file (str): Path to the input JSON file
        output_file (str): Path to the output text file
    """
    try:
        # Read the JSON file
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Support for vdf_export.json structure (list of dicts with 'Path' key)
        paths = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and 'Path' in item:
                    paths.append(item['Path'])
                # Also support the old nested group structure
                elif isinstance(item, list):
                    for subitem in item:
                        if isinstance(subitem, dict) and 'Path' in subitem:
                            paths.append(subitem['Path'])
        elif isinstance(data, dict):
            # If vdf_export.json is a dict with a top-level key containing the list
            for value in data.values():
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and 'Path' in item:
                            paths.append(item['Path'])
        
        # Write paths to text file
        with open(output_file, 'w', encoding='utf-8') as f:
            for path in paths:
                f.write(path + '\n')
        
        print(f"Successfully extracted {len(paths)} paths to '{output_file}'")
        
    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found.")
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in '{input_file}'.")
    except Exception as e:
        print(f"Error: {str(e)}")

def main():
    # Default file names
    input_file = "vdf_export.json"  # Now defaults to vdf_export.json
    output_file = "paths.txt"
    
    # Allow command line arguments
    if len(sys.argv) == 3:
        input_file = sys.argv[1]
        output_file = sys.argv[2]
    elif len(sys.argv) == 2:
        input_file = sys.argv[1]
    
    extract_paths_from_json(input_file, output_file)

if __name__ == "__main__":
    main()