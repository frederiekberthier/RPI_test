import shutil
import subprocess


def working_bash():
    """Een bash die echt werkt. Op Windows is `bash` vaak de WSL-starter zonder distributie: die telt niet."""
    # Git Bash eerst: `bash` op de PATH is op Windows vaak de WSL-starter, waar C:/-paden niet bestaan
    # usr\bin\bash.exe is de directe MSYS-bash; bin\bash.exe is een starter die zijn eigen map vóór de PATH zet,
    # waardoor de stubs van de installatietests niet meer voorrang hebben.
    candidates = [r"C:\Program Files\Git\usr\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")]
    for candidate in filter(None, candidates):
        try:
            probe = subprocess.run([candidate, "-c", "echo ok"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.stdout.strip() == "ok":
            return candidate
    return None


BASH = working_bash()
