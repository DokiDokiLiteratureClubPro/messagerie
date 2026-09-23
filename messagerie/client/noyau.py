"""
Noyau de la messagerie : réseau + chiffrement + appels.
(aucune interface graphique ici, voir app.py)

CHIFFREMENT
-----------
Chaque utilisateur possède une paire de clés X25519 créée au premier lancement
et gardée sur SON ordinateur (dossier ~/.messagerie). Seule la clé publique
est envoyée au serveur.

Pour parler à Bob, Alice combine SA clé privée et la clé publique de Bob
(échange Diffie-Hellman) : les deux obtiennent le même secret sans jamais
l'envoyer sur le réseau. Chaque message / morceau d'audio est chiffré avec
XSalsa20-Poly1305 (bibliothèque libsodium via PyNaCl) :
  - le serveur ne peut pas lire le contenu,
  - toute modification en route est détectée (authentification),
  - un message ne peut venir que du détenteur de la clé privée de l'expéditeur.

Protection contre un serveur menteur : la première clé vue pour un contact est
mémorisée ("confiance au premier usage"). Si elle change plus tard, l'appli
prévient. Le "code de sécurité" permet de vérifier de vive voix que personne
ne s'est glissé au milieu.
"""

import asyncio
import base64
import collections
import hashlib
import json
import os
import threading
import time
from pathlib import Path

from nacl.public import PrivateKey, PublicKey, Box
from nacl.exceptions import CryptoError
from websockets.asyncio.client import connect

DOSSIER = Path.home() / ".messagerie"

# Paramètres audio : 16 kHz mono, paquets de 20 ms
FREQ = 16000
TAILLE_BLOC = 320          # échantillons par paquet (20 ms)
TAMPON_MAX = 12            # au-delà, on jette l'audio en retard (latence)
TAMPON_DEPART = 3          # paquets à accumuler avant de commencer à jouer


def b64(octets: bytes) -> str:
    return base64.b64encode(octets).decode()


def unb64(texte: str) -> bytes:
    return base64.b64decode(texte)


def code_securite(cle_a: bytes, cle_b: bytes) -> str:
    """Code identique chez les deux personnes : à comparer de vive voix."""
    empreinte = hashlib.sha256(b"".join(sorted([cle_a, cle_b]))).digest()
    nombre = int.from_bytes(empreinte[:15], "big")
    chiffres = str(nombre % 10**30).zfill(30)
    return " ".join(chiffres[i:i + 5] for i in range(0, 30, 5))


# --------------------------------------------------------------------------
# Audio (le module sounddevice n'est chargé qu'au moment d'un appel)
# --------------------------------------------------------------------------
class FluxAudio:
    def __init__(self, envoyer_pcm):
        import sounddevice as sd   # import tardif : les messages marchent même sans micro
        self.envoyer_pcm = envoyer_pcm
        self.recus = collections.deque()
        self.pret = False
        self.muet = False
        self.flux = sd.RawStream(samplerate=FREQ, blocksize=TAILLE_BLOC, dtype="int16",
                                 channels=1, callback=self._rappel)
        self.flux.start()

    def _rappel(self, entree, sortie, nb, _temps, _statut):
        # Micro -> réseau
        if not self.muet:
            self.envoyer_pcm(bytes(entree))
        # Réseau -> haut-parleur
        while len(self.recus) > TAMPON_MAX:
            self.recus.popleft()
        if not self.pret and len(self.recus) >= TAMPON_DEPART:
            self.pret = True
        if self.pret and self.recus:
            paquet = self.recus.popleft()
            besoin = len(sortie)
            sortie[:] = paquet[:besoin].ljust(besoin, b"\x00")
        else:
            if not self.recus:
                self.pret = False      # tampon vide : on ré-accumule avant de rejouer
            sortie[:] = b"\x00" * len(sortie)

    def recevoir(self, pcm: bytes):
        self.recus.append(pcm)

    def arreter(self):
        try:
            self.flux.stop()
            self.flux.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Noyau
# --------------------------------------------------------------------------
class Messagerie:
    """
    evenement(dict) est appelé (depuis un autre thread) pour prévenir l'interface.
    Types d'événements : connecte, deconnecte, erreur, fatal, utilisateurs,
    message, cle_changee, appel.
    """

    def __init__(self, url: str, pseudo: str, evenement):
        self.url = url
        self.pseudo = pseudo
        self.evenement = evenement
        DOSSIER.mkdir(parents=True, exist_ok=True)

        # --- Clé privée (créée une seule fois, ne quitte jamais l'ordinateur)
        fichier_cle = DOSSIER / f"{pseudo}.cle"
        if fichier_cle.exists():
            self.cle = PrivateKey(fichier_cle.read_bytes())
        else:
            self.cle = PrivateKey.generate()
            fichier_cle.write_bytes(bytes(self.cle))
            try:
                os.chmod(fichier_cle, 0o600)
            except OSError:
                pass
        self.ma_cle_pub = bytes(self.cle.public_key)

        # --- Clés publiques de confiance des contacts
        self.fichier_contacts = DOSSIER / f"{pseudo}_contacts.json"
        self.contacts: dict[str, str] = {}
        if self.fichier_contacts.exists():
            self.contacts = json.loads(self.fichier_contacts.read_text())
        self.cles_changees: dict[str, str] = {}
        self.annuaire: dict[str, dict] = {}
        self._boites: dict[str, Box] = {}

        self.appel = None          # {"avec": nom, "etat": "sortant|entrant|en_cours", "audio": FluxAudio|None}
        self.ws = None
        self.boucle = None
        self._stop = False

    # ------------------------------------------------------------ outils
    def _sauver_contacts(self):
        self.fichier_contacts.write_text(json.dumps(self.contacts, indent=2))

    def _boite(self, nom: str):
        if nom in self.cles_changees:
            return None          # clé non vérifiée : on refuse de chiffrer/déchiffrer
        if nom not in self._boites:
            cle = self.contacts.get(nom)
            if not cle:
                return None
            self._boites[nom] = Box(self.cle, PublicKey(unb64(cle)))
        return self._boites[nom]

    def _chiffrer(self, nom: str, donnees: bytes):
        boite = self._boite(nom)
        return b64(boite.encrypt(donnees)) if boite else None

    def _dechiffrer(self, nom: str, texte: str):
        boite = self._boite(nom)
        if not boite:
            return None
        try:
            return boite.decrypt(unb64(texte))
        except (CryptoError, ValueError):
            return None

    def code_securite_avec(self, nom: str):
        cle = self.contacts.get(nom)
        return code_securite(self.ma_cle_pub, unb64(cle)) if cle else None

    def accepter_nouvelle_cle(self, nom: str):
        if nom in self.cles_changees:
            self.contacts[nom] = self.cles_changees.pop(nom)
            self._boites.pop(nom, None)
            self._sauver_contacts()

    # ------------------------------------------------------------ réseau
    def demarrer(self):
        threading.Thread(target=lambda: asyncio.run(self._principal()), daemon=True).start()

    def arreter(self):
        self._stop = True
        self.raccrocher()
        if self.boucle and self.ws:
            asyncio.run_coroutine_threadsafe(self.ws.close(), self.boucle)

    def _envoyer(self, paquet: dict):
        ws, boucle = self.ws, self.boucle
        if ws is None or boucle is None:
            return False
        asyncio.run_coroutine_threadsafe(self._envoi_sur(ws, json.dumps(paquet)), boucle)
        return True

    @staticmethod
    async def _envoi_sur(ws, texte):
        try:
            await ws.send(texte)
        except Exception:
            pass

    async def _principal(self):
        self.boucle = asyncio.get_running_loop()
        attente = 2
        while not self._stop:
            try:
                # open_timeout long : un serveur gratuit endormi met ~1 min à se réveiller
                async with connect(self.url, open_timeout=90, max_size=256 * 1024,
                                   ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(json.dumps({"type": "hello", "user": self.pseudo,
                                              "pubkey": b64(self.ma_cle_pub)}))
                    reponse = json.loads(await ws.recv())
                    if reponse.get("type") == "error":
                        self.evenement({"type": "fatal", "msg": reponse.get("msg")})
                        return
                    self.ws = ws
                    attente = 2
                    self.evenement({"type": "connecte"})
                    garde = asyncio.create_task(self._garder_eveille(ws))
                    try:
                        async for brut in ws:
                            self._traiter(json.loads(brut))
                    finally:
                        garde.cancel()
            except Exception as e:
                if self._stop:
                    return
                self.evenement({"type": "deconnecte", "msg": str(e) or type(e).__name__})
            self.ws = None
            if self.appel:
                self._fin_appel("Connexion perdue")
            if not self._stop:
                await asyncio.sleep(attente)
                attente = min(attente * 2, 30)

    async def _garder_eveille(self, ws):
        # Render (gratuit) s'endort après 15 min sans message entrant
        while True:
            await asyncio.sleep(240)
            await ws.send('{"type":"ping"}')

    # ------------------------------------------------------------ réception
    def _traiter(self, p: dict):
        t = p.get("type")
        if t == "users":
            self._maj_annuaire(p["users"])
        elif t == "offline":
            if self.appel and self.appel["avec"] == p.get("user"):
                self._fin_appel(f"{p.get('user')} n'est pas connecté")
        elif t == "recv":
            de, kind, data = p.get("from"), p.get("kind"), p.get("data") or {}
            if kind == "audio":
                if self.appel and self.appel["avec"] == de and self.appel.get("audio"):
                    pcm = self._dechiffrer(de, data.get("c", ""))
                    if pcm:
                        self.appel["audio"].recevoir(pcm)
            elif kind == "msg":
                clair = self._dechiffrer(de, data.get("c", ""))
                if clair is None:
                    self.evenement({"type": "erreur",
                                    "msg": f"Message de {de} impossible à déchiffrer (clé inconnue ou modifiée)."})
                    return
                contenu = json.loads(clair)
                self.evenement({"type": "message", "de": de, "texte": contenu["t"],
                                "ts": contenu.get("ts", time.time())})
            elif kind == "call":
                clair = self._dechiffrer(de, data.get("c", ""))
                if clair is not None:
                    self._signal_appel(de, json.loads(clair).get("action"))

    def _maj_annuaire(self, liste):
        self.annuaire = {u["user"]: u for u in liste if u["user"] != self.pseudo}
        change = False
        for nom, info in self.annuaire.items():
            connu = self.contacts.get(nom)
            if connu is None:
                self.contacts[nom] = info["pubkey"]      # confiance au premier usage
                change = True
            elif connu != info["pubkey"] and self.cles_changees.get(nom) != info["pubkey"]:
                self.cles_changees[nom] = info["pubkey"]
                self.evenement({"type": "cle_changee", "user": nom})
        if change:
            self._sauver_contacts()
        self.evenement({"type": "utilisateurs"})

    # ------------------------------------------------------------ messages
    def envoyer_message(self, nom: str, texte: str) -> bool:
        clair = json.dumps({"t": texte, "ts": time.time()}).encode()
        c = self._chiffrer(nom, clair)
        if c is None:
            return False
        return self._envoyer({"type": "send", "to": nom, "kind": "msg", "data": {"c": c}})

    # ------------------------------------------------------------ appels
    def _signal(self, nom, action):
        c = self._chiffrer(nom, json.dumps({"action": action}).encode())
        if c:
            self._envoyer({"type": "send", "to": nom, "kind": "call", "data": {"c": c}})

    def appeler(self, nom: str):
        if self.appel or self._boite(nom) is None:
            return False
        self.appel = {"avec": nom, "etat": "sortant", "audio": None}
        self._signal(nom, "offre")
        self.evenement({"type": "appel", "etat": "sortant", "avec": nom})
        return True

    def accepter(self):
        if self.appel and self.appel["etat"] == "entrant":
            self._signal(self.appel["avec"], "accepte")
            self._lancer_audio()

    def raccrocher(self):
        if self.appel:
            self._signal(self.appel["avec"], "fin")
            self._fin_appel("Appel terminé")

    def basculer_muet(self) -> bool:
        if self.appel and self.appel.get("audio"):
            self.appel["audio"].muet = not self.appel["audio"].muet
            return self.appel["audio"].muet
        return False

    def _signal_appel(self, de, action):
        if action == "offre":
            if self.appel:
                self._signal(de, "occupe")
                return
            self.appel = {"avec": de, "etat": "entrant", "audio": None}
            self.evenement({"type": "appel", "etat": "entrant", "avec": de})
        elif not self.appel or self.appel["avec"] != de:
            return
        elif action == "accepte" and self.appel["etat"] == "sortant":
            self._lancer_audio()
        elif action == "occupe":
            self._fin_appel(f"{de} est déjà en appel")
        elif action == "fin":
            self._fin_appel("Appel terminé" if self.appel["etat"] == "en_cours" else "Appel refusé / annulé")

    def _lancer_audio(self):
        nom = self.appel["avec"]

        def envoyer_pcm(pcm):
            c = self._chiffrer(nom, pcm)
            if c:
                self._envoyer({"type": "send", "to": nom, "kind": "audio", "data": {"c": c}})
        try:
            self.appel["audio"] = FluxAudio(envoyer_pcm)
        except Exception as e:
            self._signal(nom, "fin")
            self._fin_appel(f"Micro / haut-parleur indisponible : {e}")
            return
        self.appel["etat"] = "en_cours"
        self.evenement({"type": "appel", "etat": "en_cours", "avec": nom})

    def _fin_appel(self, raison):
        appel, self.appel = self.appel, None
        if appel and appel.get("audio"):
            appel["audio"].arreter()
        if appel:
            self.evenement({"type": "appel", "etat": "fini", "avec": appel["avec"], "msg": raison})
