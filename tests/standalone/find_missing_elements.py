import re
import os

SCRIPT_PATH = "/Users/tim/AntigravityProject/Owlynn/frontend/script.js"
HTML_PATH = "/Users/tim/AntigravityProject/Owlynn/frontend/index.html"

def main():
    if not os.path.exists(SCRIPT_PATH) or not os.path.exists(HTML_PATH):
        print("Files not found.")
        return

    with open(SCRIPT_PATH, 'r') as f:
        script_content = f.read()

    with open(HTML_PATH, 'r') as f:
        html_content = f.read()

    # Find IDs in script.js
    # Handles: document.getElementById('id') or document.getElementById("id")
    id_pattern = r"document\.getElementById\(['\"]([^'\"]+)['\"]\)"
    ids_in_script = set(re.findall(id_pattern, script_content))

    print(f"Found {len(ids_in_script)} unique IDs referenced in script.js")

    missing = []
    found_count = 0
    for element_id in sorted(ids_in_script):
        # Simplistic check: just look for the ID string in html
        # This might match on random text, but will catch missing ones definitely.
        # Safer: look for id="id" or id='id'
        pattern1 = f'id="{element_id}"'
        pattern2 = f"id='{element_id}'"
        
        if pattern1 in html_content or pattern2 in html_content:
            found_count += 1
        else:
            missing.append(element_id)

    print(f"Found match for {found_count} IDs in index.html")
    print(f"\nMissing IDs ({len(missing)}):")
    for m in missing:
        print(f" - {m}")

if __name__ == "__main__":
    main()
