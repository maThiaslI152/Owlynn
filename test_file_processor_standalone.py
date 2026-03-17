import os
import sys

# Add project root to path
sys.path.append("/Users/tim/Documents/Owlynn")

from src.api.file_processor import FileWatcherHandler
from src.config.settings import WORKSPACE_DIR

def main():
    print("Testing File Processor Standalone...")
    
    # 1. Instantiate the Handler
    handler = FileWatcherHandler(WORKSPACE_DIR)
    
    # 2. Create a dummy CSV file to test table processing
    csv_path = os.path.join(WORKSPACE_DIR, "test_file.csv")
    with open(csv_path, "w") as f:
        f.write("Name,Age,Role\nAlice,30,Engineer\nBob,25,Designer")
    print(f"Created dummy CSV: {csv_path}")
    
    # 3. Process the file manually
    print("Processing file: test_file.csv")
    handler.process_file(csv_path)
    
    # 4. Verify output
    processed_file = os.path.join(WORKSPACE_DIR, ".processed", "test_file.csv.md")
    if os.path.exists(processed_file):
        print("✅ SUCCESS: Processed file created!")
        with open(processed_file, "r") as f:
             print("--- Processed Output ---")
             print(f.read())
             print("------------------------")
    else:
        print("❌ FAILURE: Processed file not found.")

    # 5. Clean up
    try:
        os.remove(csv_path)
        # Leave processed file for inspection if needed, or remove
        os.remove(processed_file)
    except:
        pass

if __name__ == "__main__":
    main()
