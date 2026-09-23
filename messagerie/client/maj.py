"""
Mises à jour automatiques depuis GitHub.

Fonctionnement :
  1. À chaque commit qui touche messagerie/client/, GitHub Actions construit
     Messagerie.exe et publie une "Release" numérotée (v1, v2, v3…).
  2. Au lancement (puis toutes les 30 min), l'appli demande à GitHub
     quelle est la dernière Release. Si elle est plus récente, un bandeau propose
     la mise à jour en un clic.
  3. La mise à jour :
       - version .exe  : télécharge le nouvel exe, remplace l'ancien, redémarre ;
       - version .py   : télécharge le code source, remplace les fichiers,
                         installe les éventuelles nouvelles dépendances, redémarre.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from version import VERSION

DEPOT = "DokiDokiLiteratureClubPro/messagerie"   # propriétaire/nom du dépôt GitHub
SOUS_DOSSIER = "messagerie/client"                 # où se trouve l'appli dans le dépôt
NOM_EXE = "Messagerie.exe"

EST_EXE = getattr(sys, "frozen", False)
DOSSIER_APPLI = Path(sys.executable).parent if EST_EXE else Path(__file__).resolve().parent


def numero(version: str) -> int:
    try:
        return int(str(version).lstrip("vV"))
    except ValueError:
        return 0


def _get(url: str, timeout=15) -> bytes:
    requete = urllib.request.Request(url, headers={"User-Agent": "messagerie-maj",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(requete, timeout=timeout) as r:
        return r.read()


def verifier():
    """Renvoie les infos de la nouvelle version, ou None si on est à jour / hors ligne."""
    try:
        info = json.loads(_get(f"https://api.github.com/repos/{DEPOT}/releases/latest"))
    except Exception:
        return None
    tag = info.get("tag_name", "")
    if numero(tag) <= numero(VERSION):
        return None
    exe = next((a["browser_download_url"] for a in info.get("assets", [])
                if a.get("name") == NOM_EXE), None)
    return {"version": tag, "notes": (info.get("body") or "").strip(),
            "exe": exe, "source": info.get("zipball_url")}


def _telecharger(url: str, destination: Path, progression):
    requete = urllib.request.Request(url, headers={"User-Agent": "messagerie-maj"})
    with urllib.request.urlopen(requete, timeout=60) as r, open(destination, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        recu = 0
        while bloc := r.read(64 * 1024):
            f.write(bloc)
            recu += len(bloc)
            progression(recu / total if total else None, "Téléchargement…")


def installer(info: dict, progression=lambda frac, texte: None):
    """Télécharge et installe la nouvelle version. Lève une exception en cas d'échec."""
    if EST_EXE:
        if not info.get("exe"):
            raise RuntimeError("Cette version n'a pas encore d'exécutable (construction en cours ?). "
                               "Réessaie dans quelques minutes.")
        actuel = Path(sys.executable)
        nouveau = actuel.with_name("Messagerie.nouveau.exe")
        ancien = actuel.with_name("Messagerie.ancien.exe")
        _telecharger(info["exe"], nouveau, progression)
        progression(1.0, "Installation…")
        if ancien.exists():
            ancien.unlink()
        actuel.rename(ancien)          # Windows autorise à renommer un exe en cours d'exécution
        nouveau.rename(actuel)
    else:
        progression(None, "Téléchargement du code…")
        archive = zipfile.ZipFile(io.BytesIO(_get(info["source"], timeout=60)))
        prefixe = None
        for nom in archive.namelist():
            # l'archive contient "<depot>-<commit>/messagerie/client/..."
            morceaux = nom.split("/", 1)
            if len(morceaux) == 2 and morceaux[1].startswith(SOUS_DOSSIER + "/"):
                prefixe = morceaux[0] + "/" + SOUS_DOSSIER + "/"
                break
        if not prefixe:
            raise RuntimeError("Fichiers de l'appli introuvables dans la mise à jour.")
        progression(0.6, "Remplacement des fichiers…")
        for nom in archive.namelist():
            if nom.startswith(prefixe) and not nom.endswith("/"):
                cible = DOSSIER_APPLI / nom[len(prefixe):]
                cible.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(nom) as src, open(cible, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        (DOSSIER_APPLI / "version.py").write_text(
            f'# Écrit par la mise à jour automatique\nVERSION = "{info["version"].lstrip("vV")}"\n',
            encoding="utf-8")
        progression(0.8, "Installation des dépendances…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                        str(DOSSIER_APPLI / "requirements.txt")],
                       capture_output=True, **_sans_console())
    progression(1.0, "Terminé, redémarrage…")


def redemarrer():
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    if EST_EXE:
        subprocess.Popen([sys.executable], env=env, cwd=DOSSIER_APPLI)
    else:
        subprocess.Popen([sys.executable, str(DOSSIER_APPLI / "app.py")], cwd=DOSSIER_APPLI)
    os._exit(0)


def nettoyer():
    """Supprime l'ancien exe laissé par la dernière mise à jour."""
    if EST_EXE:
        try:
            (Path(sys.executable).with_name("Messagerie.ancien.exe")).unlink(missing_ok=True)
        except OSError:
            pass


def _sans_console():
    if os.name == "nt":
        return {"creationflags": 0x08000000}   # CREATE_NO_WINDOW
    return {}
