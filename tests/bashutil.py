import shutil
import subprocess


def working_bash():
    """Een bash die echt werkt. Op Windows is `bash` vaak de WSL-starter zonder distributie: die telt niet."""
    candidates = [shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"]
    for candidate in filter(None, candidates):
        try:
            probe = subprocess.run([candidate, "-c", "echo ok"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.stdout.strip() == "ok":
            return candidate
    return None


BASH = working_bash()
