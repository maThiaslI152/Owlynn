"""
Podman Sandbox Execution Environment.

This module manages execution of shell commands and scripts inside a
secure, short-lived Podman container representing the agent's workspace.
"""

import subprocess
import os
import json

class PodmanSandbox:
    """
    Manages a short-lived Podman container for sandboxed tool execution.
    Mounts the local `workspace` folder into the container so the agent can write/read files securely.
    """
    
    def __init__(self, workspace_path: str, image: str = "cowork-sandbox"):
        # Ensure workspace exists
        self.host_workspace = os.path.abspath(workspace_path)
        os.makedirs(self.host_workspace, exist_ok=True)
        self.container_workspace = "/workspace"
        self.image = image
    
    def execute_shell(self, command: str, timeout: int = 30) -> str:
        """
        Executes an arbitrary shell command *inside* the Podman sandbox.

        Args:
            command (str): The bash command to execute.
            timeout (int, optional): Timeout in seconds. Defaults to 30.

        Returns:
            str: Standard output of the command if successful, or an error message.
        """
        # Run a detached, ephemeral container that mounts the workspace
        # and executes the provided command.
        
        sandbox_cmd = [
            "podman", "run", "--rm",
            "-v", f"{self.host_workspace}:{self.container_workspace}",
            "-w", self.container_workspace,
            self.image,
            "/bin/bash", "-c", command
        ]
        
        try:
            result = subprocess.run(
                sandbox_cmd, 
                capture_output=True, 
                text=True, 
                timeout=timeout
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"Execution Error (Exit code {result.returncode}):\n{result.stderr.strip()}"
                
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds."
        except Exception as e:
            return f"Sandbox Error: {str(e)}"
