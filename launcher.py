import os
import sys
import time
import subprocess
import hashlib
import threading
import random
import requests
import zipfile
import signal
from urllib.parse import urlparse
import shlex

VERSION_FILE = "update.ver"
CMD_FILE = "cmd.txt"
UPDATE_INTERVAL_MIN = 1
UPDATE_INTERVAL_MAX = 3

class SolverLauncher:
    def __init__(self):
        self.process = None
        self.cmd, self.solver_exe = self.read_cmd_and_exe()
        self.host = self.extract_host(self.cmd)
        
        # Track applied version (ZIP SHA1)
        self.applied_sha1 = self.read_applied_version()
        
        # Concurrency control
        self.lock = threading.Lock()
        self.is_updating = False
        self.running = True

    def read_applied_version(self):
        if os.path.exists(VERSION_FILE):
            try:
                with open(VERSION_FILE, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception as e:
                print(f"Error reading {VERSION_FILE}: {e}")
        return ""

    def save_applied_version(self, sha1):
        try:
            with open(VERSION_FILE, 'w', encoding='utf-8') as f:
                f.write(sha1)
            self.applied_sha1 = sha1
        except Exception as e:
            print(f"Error saving {VERSION_FILE}: {e}")

    def read_cmd_and_exe(self):
        if not os.path.exists(CMD_FILE):
            print(f"Error: {CMD_FILE} not found. Please create it with the command line.")
            sys.exit(1)
        with open(CMD_FILE, 'r', encoding='utf-8') as f:
            cmd = f.read().strip()
        if not cmd:
            print(f"Error: {CMD_FILE} is empty. Please configure the command line.")
            sys.exit(1)
            
        # Parse the executable name from the first part of the command
        args = shlex.split(cmd, posix=False)
        if not args:
            print(f"Error: Could not parse command from {CMD_FILE}.")
            sys.exit(1)
            
        exe_name = args[0]
        # Auto-add .exe if missing
        if not exe_name.lower().endswith(".exe"):
            print(f"Adding .exe suffix to executable: {exe_name}")
            exe_name += ".exe"
            # Update the first argument in the list
            args[0] = exe_name
            # Reconstruct the command string (approximate, but we'll use args for Popen anyway)
            cmd = " ".join(args)
            
        return cmd, exe_name

    def extract_host(self, cmd):
        # Extract host from --server argument if possible, otherwise use a placeholder or ask
        parts = cmd.split()
        try:
            idx = parts.index("--server")
            return parts[idx + 1]
        except (ValueError, IndexError):
            print("Warning: --server not found in cmd.txt. Update checks might fail if HOST is not determined.")
            return "UNKNOWN_HOST"

    def get_sha1(self, filepath):
        if not os.path.exists(filepath):
            return None
        sha1 = hashlib.sha1()
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha1.update(data)
        return sha1.hexdigest()

    def run_solver(self):
        with self.lock:
            # Use a more robust check for the executable
            if not os.path.exists(self.solver_exe):
                print(f"Error: {self.solver_exe} not found in current directory.")
                return

            print(f"Starting {self.solver_exe} with command: {self.cmd}")
            
            # Determine the absolute path and directory of the solver
            abs_exe_path = os.path.abspath(self.solver_exe)
            solver_dir = os.path.dirname(abs_exe_path)
            
            try:
                # CREATE_NEW_CONSOLE: Starts the process in a new console window.
                # CREATE_NEW_PROCESS_GROUP: Essential for reliable signal handling (Ctrl+Break).
                # close_fds=True: Prevents the child from inheriting the launcher's open handles.
                # stdin=subprocess.DEVNULL: Prevents blocking on parent input.
                creation_flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
                
                self.process = subprocess.Popen(
                    self.cmd, 
                    shell=False, 
                    stdin=subprocess.DEVNULL,
                    stdout=None,
                    stderr=None,
                    cwd=solver_dir,
                    close_fds=True,
                    creationflags=creation_flags
                )
                print(f"Solver started with PID: {self.process.pid} in directory: {solver_dir}")
            except Exception as e:
                print(f"Failed to start solver: {e}")

    def stop_solver(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                pid = self.process.pid
                print(f"Stopping {self.solver_exe} (PID: {pid}) safely (sending CTRL_BREAK_EVENT)...")
                
                # 1. Try CTRL_BREAK_EVENT first
                try:
                    os.kill(pid, signal.CTRL_BREAK_EVENT)
                except Exception as e:
                    print(f"Error sending Ctrl+Break: {e}")
                
                # 2. As a fallback, try taskkill
                try:
                    subprocess.run(["taskkill", "/pid", str(pid)], capture_output=True)
                except Exception as e:
                    print(f"Error running taskkill: {e}")

                try:
                    for i in range(15):
                        if self.process.poll() is not None:
                            break
                        if i == 7:
                             subprocess.run(["taskkill", "/pid", str(pid)], capture_output=True)
                        time.sleep(1)
                    
                    if self.process.poll() is None:
                        print(f"Timeout expired. Force killing {self.solver_exe}...")
                        self.process.kill()
                        self.process.wait()
                    else:
                        print(f"{self.solver_exe} stopped safely.")
                except Exception as e:
                    print(f"Error while waiting for process: {e}")
                    self.process.kill()

    def download_and_update(self, download_url, filename, remote_sha1):
        if os.path.exists(filename):
            local_zip_sha1 = self.get_sha1(filename)
            if local_zip_sha1 != remote_sha1:
                name, ext = os.path.splitext(filename)
                new_name = f"{name}_{local_zip_sha1}{ext}"
                print(f"Existing {filename} found with different SHA1. Renaming to {new_name}")
                try:
                    os.rename(filename, new_name)
                except Exception as e:
                    print(f"Failed to rename existing ZIP: {e}")

        print(f"Downloading update from {download_url}...")
        try:
            response = requests.get(download_url, timeout=60)
            response.raise_for_status()
            with open(filename, 'wb') as f:
                f.write(response.content)
            print(f"Download successful: {filename}")
            
            # Set updating flag to prevent main loop from interfering
            self.is_updating = True
            try:
                self.stop_solver()
                
                print(f"Extracting {filename}...")
                current_dir = os.getcwd()
                with zipfile.ZipFile(filename, 'r') as zip_ref:
                    zip_ref.extractall(current_dir)
                
                print("Update applied successfully.")
                self.save_applied_version(remote_sha1)
                # Keep the ZIP file (it will be renamed as a backup on the next update)
                self.run_solver()
            finally:
                self.is_updating = False
                
        except Exception as e:
            print(f"Update failed: {e}")
            self.is_updating = False

    def check_for_updates(self):
        api_url = f"https://{self.host}/api/download-info"
        print(f"Checking for updates at {api_url}...")
        try:
            response = requests.get(api_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("available"):
                remote_sha1 = data.get("sha1")
                if self.applied_sha1 != remote_sha1:
                    print(f"New update detected. New version: {remote_sha1}")
                    filename = data.get("filename")
                    download_url = f"https://{self.host}/download/{filename}"
                    self.download_and_update(download_url, filename, remote_sha1)
                else:
                    print(f"Already at version {self.applied_sha1}. No update needed.")
        except Exception as e:
            print(f"Error checking for updates: {e}")

    def update_loop(self):
        while self.running:
            wait_time = random.randint(UPDATE_INTERVAL_MIN * 60, UPDATE_INTERVAL_MAX * 60)
            print(f"Next update check in {wait_time // 60} minutes and {wait_time % 60} seconds.")
            time.sleep(wait_time)
            self.check_for_updates()

    def start(self):
        self.run_solver()
        update_thread = threading.Thread(target=self.update_loop, daemon=True)
        update_thread.start()
        
        try:
            while True:
                # Use lock to safely check and restart process
                with self.lock:
                    if not self.is_updating and self.process and self.process.poll() is not None:
                        print(f"{self.solver_exe} exited unexpectedly. Restarting in 15 seconds...")
                        # Release lock briefly to allow sleep and keep launcher responsive
                
                # Check again outside lock for sleep part to avoid holding lock during sleep
                if not self.is_updating and self.process and self.process.poll() is not None:
                    time.sleep(15)
                    # Re-check in case an update started during the sleep
                    if not self.is_updating:
                        self.run_solver()
                
                time.sleep(2)
        except KeyboardInterrupt:
            print("Launcher shutting down...")
            self.running = False
            self.stop_solver()

if __name__ == "__main__":
    launcher = SolverLauncher()
    launcher.start()
