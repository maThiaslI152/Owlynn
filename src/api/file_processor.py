import os
import time
import threading
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure simple logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class FileWatcherHandler(FileSystemEventHandler):
    """
    Handles file system events for the workspace, queuing tasks to process files.
    """
    def __init__(self, workspace_dir, on_processed_callback=None):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.processed_dir = os.path.join(self.workspace_dir, ".processed")
        os.makedirs(self.processed_dir, exist_ok=True)
        self.processing_lock = threading.Lock()
        self.on_processed_callback = on_processed_callback # callback(filename)
    

    def on_created(self, event):
        if event.is_directory:
            return
        logger.info(f"[Watcher] File created: {event.src_path}")
        self._trigger_processing(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        logger.info(f"[Watcher] File modified: {event.src_path}")
        self._trigger_processing(event.src_path)

    def _trigger_processing(self, filepath):
        # Skip hidden files and already processed files to prevent loops
        if os.path.basename(filepath).startswith("."):
            return
        # Skip if within the .processed directory
        if filepath.startswith(self.processed_dir):
            return

        # Run processing in a background thread with slight delay for file locked operations (uploads)
        threading.Thread(target=self._delayed_process, args=(filepath,), daemon=True).start()

    def _delayed_process(self, filepath, delay=1.0):
        """Wait for potential write operations to complete before processing."""
        time.sleep(delay)
        try:
            # Check file still exists after delay
            if not os.path.exists(filepath):
                return
                
            self.process_file(filepath)
        except Exception as e:
            logger.error(f"[Watcher] Error in delayed process for {filepath}: {e}")

    def process_file(self, filepath):
        """Processes the file based on its extension into .processed/"""
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()
        output_name = filename + ".txt" # default extension
        output_path = os.path.join(self.processed_dir, output_name)

        logger.info(f"[Watcher] Processing {filename} ({ext})...")

        try:
            if ext == ".pdf":
                self._process_pdf(filepath, output_path)
            elif ext in [".csv", ".xlsx"]:
                self._process_table(filepath, output_path, ext)
            elif ext == ".docx":
                self._process_word(filepath, output_path)
            else:
                # Other formats can be added here
                logger.info(f"[Watcher] Skipped {filename} (unsupported format for processing)")
                return

            logger.info(f"[Watcher] Successfully processed {filename} -> {output_path}")
            if self.on_processed_callback:
                self.on_processed_callback(filename, "processed")

        except Exception as e:
            logger.error(f"[Watcher] Failed to process {filename}: {e}")
            if self.on_processed_callback:
                self.on_processed_callback(filename, "error")

    def _process_pdf(self, filepath, output_path):
        import fitz # PyMuPDF
        doc = fitz.open(filepath)
        text = ""
        for i, page in enumerate(doc):
            text += f"--- Page {i+1} ---\n"
            text += page.get_text() + "\n\n"
        doc.close()
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

    def _process_table(self, filepath, output_path, ext):
        import pandas as pd
        if ext == ".csv":
            df = pd.read_csv(filepath)
        else: # .xlsx
            df = pd.read_excel(filepath)
            
        # Convert to Markdown for LLM readability
        markdown_text = df.to_markdown(index=False)
        # Using .md extension is better for tables
        output_path_md = output_path.replace(".txt", ".md")
        with open(output_path_md, "w", encoding="utf-8") as f:
            f.write(markdown_text)

    def _process_word(self, filepath, output_path):
        from docx import Document
        doc = Document(filepath)
        text = ""
        for para in doc.paragraphs:
            if para.text.strip():
                text += para.text + "\n"
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

def start_watcher(workspace_dir, on_processed_callback=None):
    """Starts the observer thread in background."""
    workspace_dir = os.path.abspath(workspace_dir)
    event_handler = FileWatcherHandler(workspace_dir, on_processed_callback=on_processed_callback)
    observer = Observer()
    observer.schedule(event_handler, path=workspace_dir, recursive=True)
    observer.start()
    logger.info(f"🚀 Started WorkspaceWatcher on {workspace_dir}")
    return observer

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="./workspace")
    args = parser.parse_args()
    
    observer = start_watcher(args.workspace)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
