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
        # Use a more robust check for the executable
        if not os.path.exists(self.solver_exe):
            print(f"Error: {self.solver_exe} not found in current directory.")
            return

        print(f"Starting {self.solver_exe} with command: {self.cmd}")
        
        # Use shlex.split with posix=False to correctly handle Windows paths and quotes
        args = shlex.split(self.cmd, posix=False)
        # Ensure we use an absolute path for the executable to avoid resolution issues
        args[0] = os.path.abspath(self.solver_exe)
        
        # Use CREATE_NEW_CONSOLE to open the solver in its own window.
        # Explicitly set stdin=subprocess.DEVNULL to prevent the child from blocking 
        # on parent input or unread pipes.
        # stdout and stderr remain None so they show up in the new console window.
        self.process = subprocess.Popen(
            args, 
            shell=False, 
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )

    def stop_solver(self):
        if self.process and self.process.poll() is None:
            pid = self.process.pid
            print(f"Stopping {self.solver_exe} (PID: {pid}) safely (sending CTRL_BREAK_EVENT)...")
            
            # 1. Try CTRL_BREAK_EVENT first, often more reliable for process groups on Windows
            try:
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            except Exception as e:
                print(f"Error sending Ctrl+Break: {e}")
            
            # 2. As a fallback for "safe" exit, try taskkill without /F (force)
            # This sends a WM_CLOSE or similar request to the process.
            try:
                subprocess.run(["taskkill", "/pid", str(pid)], capture_output=True)
            except Exception as e:
                print(f"Error running taskkill: {e}")

            try:
                # Wait for graceful exit (15 seconds total)
                for i in range(15):
                    if self.process.poll() is not None:
                        break
                    if i == 7: # Halfway through, try taskkill again just in case
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
            
            self.stop_solver()
            
            print(f"Extracting {filename}...")
            # Get current directory absolute path for clear logging if needed
            current_dir = os.getcwd()
            with zipfile.ZipFile(filename, 'r') as zip_ref:
                zip_ref.extractall(current_dir)
            
            print("Update applied successfully.")
            # Update the applied version file
            self.save_applied_version(remote_sha1)
            os.remove(filename)
            self.run_solver()
        except Exception as e:
            print(f"Update failed: {e}")

    def check_for_updates(self):
        api_url = f"https://{self.host}/api/download-info"
        print(f"Checking for updates at {api_url}...")
        try:
            response = requests.get(api_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("available"):
                remote_sha1 = data.get("sha1")
                # Compare JSON sha1 (ZIP) with the last successfully applied version
                if self.applied_sha1 != remote_sha1:
                    print(f"New update detected. Applied version: {self.applied_sha1 or 'None'}, New version: {remote_sha1}")
                    filename = data.get("filename")
                    download_url = f"https://{self.host}/download/{filename}"
                    self.download_and_update(download_url, filename, remote_sha1)
                else:
                    print(f"Already at version {self.applied_sha1}. No update needed.")
        except Exception as e:
            print(f"Error checking for updates: {e}")


    def update_loop(self):
        while self.running:
            # Random interval between 1 and 3 minutes
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
                if self.process and self.process.poll() is not None:
                    print(f"{self.solver_exe} exited unexpectedly. Restarting in 5 seconds...")
                    time.sleep(5)
                    self.run_solver()
                time.sleep(1)
        except KeyboardInterrupt:
            print("Launcher shutting down...")
            self.running = False
            self.stop_solver()

if __name__ == "__main__":
    launcher = SolverLauncher()
    launcher.start()
