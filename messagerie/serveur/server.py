"""
Serveur relais de la messagerie.

Le serveur ne fait que TRANSMETTRE des paquets entre utilisateurs.
Tous les messages et l'audio sont chiffrés de bout en bout par les clients :
le serveur ne voit que des données chiffrées et ne possède aucune clé privée.

Ce qu'il connaît : les pseudos, les clés PUBLIQUES, qui parle à qui et quand.

Lancement local :   python server.py          (écoute sur le port 8765)
Sur Render :        le port est donné par la variable d'environnement PORT.
"""

import asyncio
import json
import os
import re
import time
from http import HTTPStatus

from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosed

PORT = int(os.environ.get("PORT", "8765"))
NOM_VALIDE = re.compile(r"^[A-Za-z0-9_\-]{2,20}$")
MAX_EN_ATTENTE = 200          # messages gardés pour un utilisateur hors ligne
TYPES_MEMORISABLES = {"msg"}  # l'audio et les appels ne sont jamais mis en attente

# pseudo -> {"pubkey": str, "ws": ServerConnection | None}
utilisateurs: dict[str, dict] = {}
# pseudo -> liste de paquets en attente (chiffrés)
en_attente: dict[str, list] = {}


def liste_utilisateurs() -> str:
    return json.dumps({
        "type": "users",
        "users": [
            {"user": nom, "pubkey": info["pubkey"], "online": info["ws"] is not None}
            for nom, info in sorted(utilisateurs.items())
        ],
    })


async def diffuser_liste():
    paquet = liste_utilisateurs()
    for info in list(utilisateurs.values()):
        ws = info["ws"]
        if ws is not None:
            try:
                await ws.send(paquet)
            except ConnectionClosed:
                pass


async def gerer_client(ws: ServerConnection):
    nom = None
    try:
        # 1) Présentation : {"type":"hello","user":..., "pubkey":...}
        premier = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
        if premier.get("type") != "hello":
            await ws.send(json.dumps({"type": "error", "msg": "Présentation attendue."}))
            return
        nom = str(premier.get("user", ""))
        pubkey = str(premier.get("pubkey", ""))
        if not NOM_VALIDE.match(nom) or len(pubkey) != 44:
            await ws.send(json.dumps({"type": "error",
                                      "msg": "Pseudo invalide (2 à 20 caractères : lettres, chiffres, _ ou -)."}))
            nom = None
            return

        existant = utilisateurs.get(nom)
        if existant and existant["pubkey"] != pubkey:
            await ws.send(json.dumps({"type": "error",
                                      "msg": "Ce pseudo est déjà utilisé par quelqu'un d'autre."}))
            nom = None
            return
        if existant and existant["ws"] is not None:
            # même personne qui se reconnecte : on ferme l'ancienne connexion
            try:
                await existant["ws"].close()
            except Exception:
                pass

        utilisateurs[nom] = {"pubkey": pubkey, "ws": ws}
        await ws.send(json.dumps({"type": "welcome", "user": nom}))
        print(f"[+] {nom} connecté")
        await diffuser_liste()

        # Messages reçus pendant l'absence
        for paquet in en_attente.pop(nom, []):
            await ws.send(json.dumps(paquet))

        # 2) Boucle de relais
        async for brut in ws:
            try:
                paquet = json.loads(brut)
            except (ValueError, TypeError):
                continue
            t = paquet.get("type")

            if t == "ping":
                await ws.send('{"type":"pong"}')

            elif t == "send":
                dest = str(paquet.get("to", ""))
                kind = str(paquet.get("kind", ""))
                sortie = {"type": "recv", "from": nom, "kind": kind,
                          "data": paquet.get("data"), "ts": time.time()}
                cible = utilisateurs.get(dest)
                if cible and cible["ws"] is not None:
                    try:
                        await cible["ws"].send(json.dumps(sortie))
                    except ConnectionClosed:
                        pass
                elif cible and kind in TYPES_MEMORISABLES:
                    file = en_attente.setdefault(dest, [])
                    file.append(sortie)
                    del file[:-MAX_EN_ATTENTE]
                elif kind == "call":
                    await ws.send(json.dumps({"type": "offline", "user": dest}))

    except (ConnectionClosed, asyncio.TimeoutError, ValueError):
        pass
    finally:
        if nom and nom in utilisateurs and utilisateurs[nom]["ws"] is ws:
            utilisateurs[nom]["ws"] = None
            print(f"[-] {nom} déconnecté")
            await diffuser_liste()


def requete_http(connection, request):
    """Répond 'OK' aux simples visites HTTP (utile pour réveiller le serveur sur Render)."""
    if request.headers.get("Upgrade", "").lower() != "websocket":
        return connection.respond(HTTPStatus.OK, "Serveur de messagerie en ligne.\n")
    return None


async def main():
    async with serve(gerer_client, "0.0.0.0", PORT,
                     process_request=requete_http,
                     max_size=256 * 1024,
                     ping_interval=30, ping_timeout=30) as serveur:
        print(f"Serveur relais en écoute sur le port {PORT}")
        await serveur.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
