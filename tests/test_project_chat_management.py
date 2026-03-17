import unittest
import os
import sys

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.memory.project import ProjectManager, _PROJECTS_PATH

class TestProjectChatManagement(unittest.TestCase):
    def setUp(self):
        self.pm = ProjectManager()
        # Create a test project
        self.project = self.pm.create_project("Test Project")
        self.chat_info = {"id": "test-chat-1", "name": "Test Chat", "created_at": 1234567890}
        self.pm.add_chat_to_project(self.project["id"], self.chat_info)

    def tearDown(self):
        # Clean up
        if hasattr(self, 'project') and self.project:
             self.pm.delete_project(self.project["id"])

    def test_update_chat(self):
        self.pm.update_chat_in_project(self.project["id"], "test-chat-1", name="Updated Chat")
        project = self.pm.get_project(self.project["id"])
        chat = next(c for c in project["chats"] if c["id"] == "test-chat-1")
        self.assertEqual(chat["name"], "Updated Chat")

    def test_delete_chat(self):
        self.pm.delete_chat_from_project(self.project["id"], "test-chat-1")
        project = self.pm.get_project(self.project["id"])
        self.assertEqual(len(project["chats"]), 0)

    def test_delete_project(self):
        pid = self.project["id"]
        res = self.pm.delete_project(pid)
        self.assertTrue(res)
        self.assertIsNone(self.pm.get_project(pid))

if __name__ == '__main__':
    unittest.main()
