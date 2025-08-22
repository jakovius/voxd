"""
LlamaServerManager: Automatic lifecycle management for llama-server.

This module handles starting and stopping the llama-server process
transparently when the llamacpp_server AIPP provider is used.
"""

import subprocess
import time
import requests
import atexit
import signal
import os
from pathlib import Path
from typing import Optional
from voxt.utils.libw import verbo

class LlamaServerManager:
    """Manages llama-server lifecycle for AIPP integration."""
    
    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._port = 8080
        self._host = "127.0.0.1" 
        self._url = f"http://{self._host}:{self._port}"
        self._startup_timeout = 30
        self._shutdown_timeout = 10
        
        # Register cleanup on exit
        atexit.register(self.stop_server)
        
    def is_server_running(self) -> bool:
        """Check if llama-server is responding to health checks."""
        try:
            response = requests.get(f"{self._url}/health", timeout=2)
            return response.status_code == 200
        except (requests.RequestException, ConnectionError):
            return False
            
    def start_server(self, server_path: str, model_path: str, port: int = 8080, 
                    host: str = "127.0.0.1") -> bool:
        """Start llama-server if not already running.
        
        Args:
            server_path: Path to llama-server binary
            model_path: Path to GGUF model file
            port: Server port (default: 8080)
            host: Server host (default: 127.0.0.1)
            
        Returns:
            True if server is running (started or already running), False on failure
        """
        self._port = port
        self._host = host
        self._url = f"http://{host}:{port}"
        
        # Check if server is already running
        if self.is_server_running():
            verbo(f"[llama-server] Already running on {self._url}")
            return True
            
        # Validate paths
        if not Path(server_path).exists():
            print(f"[llama-server] Error: Server binary not found: {server_path}")
            return False
            
        if not Path(model_path).exists():
            print(f"[llama-server] Error: Model file not found: {model_path}")
            return False
            
        verbo(f"[llama-server] Starting server on {self._url}")
        verbo(f"[llama-server] Using model: {Path(model_path).name}")
        
        try:
            # Start the server process
            self._process = subprocess.Popen([
                server_path,
                "--model", model_path,
                "--port", str(port),
                "--host", host,
                "--log-disable"  # Suppress llama.cpp logs
            ], 
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid  # Create new process group for clean shutdown
            )
            
            # Wait for server to become ready
            start_time = time.time()
            while time.time() - start_time < self._startup_timeout:
                if self.is_server_running():
                    verbo(f"[llama-server] Ready on {self._url}")
                    return True
                    
                # Check if process died
                if self._process.poll() is not None:
                    print(f"[llama-server] Process exited unexpectedly (code: {self._process.returncode})")
                    self._process = None
                    return False
                    
                time.sleep(0.5)
                
            print(f"[llama-server] Timeout waiting for server to start")
            self.stop_server()
            return False
            
        except Exception as e:
            print(f"[llama-server] Failed to start: {e}")
            self._process = None
            return False
            
    def stop_server(self):
        """Stop the llama-server process gracefully."""
        if self._process is None:
            return
            
        verbo("[llama-server] Stopping server...")
        
        try:
            # Send SIGTERM to the process group
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
            
            # Wait for graceful shutdown
            try:
                self._process.wait(timeout=self._shutdown_timeout)
                verbo("[llama-server] Stopped gracefully")
            except subprocess.TimeoutExpired:
                # Force kill if still running
                verbo("[llama-server] Force killing...")
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                self._process.wait()
                verbo("[llama-server] Force killed")
                
        except (ProcessLookupError, OSError):
            # Process already dead
            pass
        except Exception as e:
            print(f"[llama-server] Error during shutdown: {e}")
        finally:
            self._process = None
            
    def get_server_url(self) -> str:
        """Get the server URL."""
        return self._url
        
    def get_server_status(self) -> dict:
        """Get detailed server status information."""
        return {
            "process_running": self._process is not None and self._process.poll() is None,
            "server_responding": self.is_server_running(),
            "url": self._url,
            "pid": self._process.pid if self._process else None
        }

# Global instance
_manager = LlamaServerManager()

def get_server_manager() -> LlamaServerManager:
    """Get the global server manager instance."""
    return _manager

def ensure_server_running(server_path: str, model_path: str, 
                         port: int = 8080, host: str = "127.0.0.1") -> bool:
    """Ensure llama-server is running for the given configuration.
    
    This is the main entry point for AIPP providers.
    """
    return _manager.start_server(server_path, model_path, port, host)
