"""
Project Manager for the Local Cowork Agent.

Manages projects, including their custom instructions, workspace, and 
knowledge base association. Similar to Anthropic's 'Projects' feature.
"""

import json
import os
import time
from pathlib import Path
from typing import List, Dict, Optional
from src.config.settings import DATA_DIR, WORKSPACE_DIR
from src.memory.long_term import memory

_PROJECTS_PATH = DATA_DIR / "projects.json"

_DEFAULT_PROJECT = {
    "id": "default",
    "name": "General Workspace",
    "instructions": "You are a helpful AI assistant in a local-first workspace. Help the user with coding, research, and data analysis tasks.",
    "files": [], # list of {name, path, type, chroma_id}
    "chats": []  # list of {id, name, created_at}
}

class ProjectManager:
    def __init__(self):
        self.projects: Dict[str, dict] = {}
        self._load_projects()

    def _load_projects(self):
        if not _PROJECTS_PATH.exists():
            self.projects = {"default": _DEFAULT_PROJECT.copy()}
            self._save_projects()
            return

        try:
            with open(_PROJECTS_PATH, "r", encoding="utf-8") as f:
                self.projects = json.load(f)
                # Migration: ensure all projects have chats and files keys
                for pid in self.projects:
                    if "chats" not in self.projects[pid]:
                        self.projects[pid]["chats"] = []
                    if "files" not in self.projects[pid]:
                        self.projects[pid]["files"] = []
        except Exception as e:
            print(f"Error loading projects: {e}")
            self.projects = {"default": _DEFAULT_PROJECT.copy()}

    def _save_projects(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_PROJECTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.projects, f, ensure_ascii=False, indent=2)

    def create_project(self, name: str, instructions: Optional[str] = None) -> dict:
        import uuid
        project_id = str(uuid.uuid4())[:8]
        new_project = {
            "id": project_id,
            "name": name,
            "instructions": instructions or _DEFAULT_PROJECT["instructions"],
            "files": [],
            "chats": []
        }
        self.projects[project_id] = new_project
        self._save_projects()
        
        # Create a workspace folder for this project
        (WORKSPACE_DIR / project_id).mkdir(parents=True, exist_ok=True)
        
        return new_project

    def get_project(self, project_id: str) -> Optional[dict]:
        return self.projects.get(project_id)

    def list_projects(self) -> List[dict]:
        return list(self.projects.values())

    def update_project(self, project_id: str, **kwargs) -> Optional[dict]:
        if project_id not in self.projects:
            return None
        
        project = self.projects[project_id]
        for key, value in kwargs.items():
            if key in project:
                project[key] = value
        
        self._save_projects()
        return project

    def add_file_to_project(self, project_id: str, file_info: dict):
        if project_id in self.projects:
            self.projects[project_id]["files"].append(file_info)
            self._save_projects()

    def add_chat_to_project(self, project_id: str, chat_info: dict):
        if project_id in self.projects:
            if "chats" not in self.projects[project_id]:
                self.projects[project_id]["chats"] = []
            
            # Avoid duplicates
            if not any(c["id"] == chat_info["id"] for c in self.projects[project_id]["chats"]):
                self.projects[project_id]["chats"].append(chat_info)
                self._save_projects()

    def delete_chat_from_project(self, project_id: str, chat_id: str):
        """Removes a chat from the project's list."""
        if project_id in self.projects:
            self.projects[project_id]["chats"] = [
                c for c in self.projects[project_id]["chats"] if c["id"] != chat_id
            ]
            self._save_projects()

    def update_chat_in_project(self, project_id: str, chat_id: str, **kwargs):
        """Updates fields (e.g., name) of a chat in the project."""
        if project_id in self.projects:
            for chat in self.projects[project_id].get("chats", []):
                if chat["id"] == chat_id:
                    for k, v in kwargs.items():
                        if k in chat:
                            chat[k] = v
                    break
            self._save_projects()

    def delete_project(self, project_id: str):
        """Deletes a project and its associated workspace folder."""
        # Do not allow deleting the default project
        if project_id == "default":
             return False
             
        if project_id in self.projects:
            del self.projects[project_id]
            self._save_projects()
            
            # Delete workspace folder
            workspace_path = self.get_workspace_path(project_id)
            if workspace_path.exists():
                import shutil
                try:
                    shutil.rmtree(workspace_path)
                except Exception as e:
                    print(f"Failed to delete workspace path {workspace_path}: {e}")
            return True
        return False

    async def add_knowledge(self, project_id: str, name: str, content: str):
        """
        Adds a piece of knowledge to the project's long-term memory (ChromaDB).
        """
        if project_id not in self.projects:
            return
            
        # Store in Mem0/ChromaDB using project_id as user_id for isolation
        memory.add(content, user_id=project_id, metadata={"filename": name}, infer=False)
        
        # Track in project files list
        file_info = {
            "name": name,
            "type": "knowledge",
            "added_at": time.time()
        }
        self.add_file_to_project(project_id, file_info)

    def get_workspace_path(self, project_id: str) -> Path:
        path = WORKSPACE_DIR / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

# Global manager
project_manager = ProjectManager()
