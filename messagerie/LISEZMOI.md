# Messagerie chiffrée (messages + appels)

Petite messagerie en Python : messages texte et appels audio, **chiffrés de bout en bout**.
Un serveur relais gratuit (Render) permet de discuter avec quelqu'un dans une autre ville.

```
 Toi (app.py)  ── données chiffrées ──►  Serveur relais (Render)  ── données chiffrées ──►  Ton ami (app.py)
   clé privée                            ne voit rien du contenu                              clé privée
```

## Contenu

| Fichier | Rôle |
|---|---|
| `serveur/server.py` | Le relais, à héberger sur Render (gratuit) |
| `render.yaml` | Configuration automatique pour Render |
| `client/app.py` | L'application (fenêtre Tkinter) |
| `client/noyau.py` | Réseau, chiffrement et appels |
| `client/creer_exe.bat` | Crée `Messagerie.exe` sous Windows |

---

## Étape 1 : mettre le serveur en ligne (une seule fois, gratuit, sans carte bancaire)

1. Crée un compte sur **github.com**, puis un nouveau dépôt (ex. `messagerie`).
   Envoie dedans tout le dossier du projet (bouton *Add file → Upload files*).
2. Crée un compte sur **render.com** (connexion avec GitHub).
3. Clique **New → Blueprint**, choisis ton dépôt, puis **Deploy**.
   *(Sinon : New → Web Service → ton dépôt, Root Directory `serveur`,
   Build `pip install -r requirements.txt`, Start `python server.py`, Instance **Free**.)*
4. Render te donne une adresse du type `messagerie-relais-abcd.onrender.com`.
   Ouvre-la dans un navigateur : tu dois voir « Serveur de messagerie en ligne. »

C'est cette adresse que toi et ton ami mettrez dans l'application.

> **Serveur gratuit :** il s'endort après 15 min sans activité. La première connexion
> ensuite prend environ 1 minute (l'appli patiente toute seule). Il oublie aussi les
> pseudos et les messages en attente quand il redémarre : ce n'est pas grave, les clés
> restent sur vos ordinateurs.

## Étape 2 : lancer l'application

Il faut Python 3.10 ou plus récent (python.org, coche « Add Python to PATH »).

```bash
cd client
pip install -r requirements.txt
python app.py
```

Entre l'adresse du serveur et un pseudo → **Se connecter**. Ton ami fait pareil avec
un autre pseudo : vous apparaissez dans la liste des contacts l'un de l'autre.

- **Message** : clique sur le contact, écris, Entrée.
- **Appel** : bouton 📞 Appeler. **Prends un casque ou des écouteurs** (sinon écho).
- **Hors ligne** : un message envoyé à quelqu'un de déconnecté lui est remis à sa reconnexion
  (tant que le serveur n'a pas redémarré).

## Étape 3 (facultatif) : créer un .exe

Sous Windows, double-clique sur `client/creer_exe.bat` → `client/dist/Messagerie.exe`.
Ton ami peut lancer cet exe **sans installer Python**.
(Sur Mac/Linux : `pip install pyinstaller` puis `pyinstaller --onefile --windowed --name Messagerie app.py`.)

---

## Comment marche la sécurité

- Au premier lancement, l'appli crée une **paire de clés** (X25519) dans le dossier
  `.messagerie` de ton compte utilisateur. La clé **privée ne quitte jamais ton ordinateur** ;
  seule la clé publique est envoyée au serveur.
- Chaque message et chaque morceau d'audio (20 ms) est chiffré et authentifié avec
  **libsodium** (XSalsa20-Poly1305, via PyNaCl) : le serveur ne voit que du charabia, et
  toute modification en route est détectée.
- **Code de sécurité** (bouton 🔒) : un code de 30 chiffres, identique chez vous deux.
  Comparez-le une fois de vive voix ; s'il correspond, personne (pas même le serveur)
  ne peut se glisser entre vous.
- Si la clé d'un contact change, l'appli **te prévient** et bloque les échanges tant que
  tu n'as pas accepté.

**Limites honnêtes** (c'est un projet perso, pas Signal) :
- pas de « confidentialité persistante » : si quelqu'un vole ta clé privée *et* avait enregistré
  tout le trafic, il pourrait relire les anciens échanges ;
- le serveur voit les pseudos, qui parle à qui et quand (pas le contenu) ;
- l'historique n'est pas sauvegardé : il disparaît quand on ferme l'appli ;
- si tu perds ton dossier `.messagerie`, tu perds ta clé : tes contacts verront
  l'alerte « clé modifiée ».

## Idées pour la suite

Sauvegarde chiffrée de l'historique, envoi de fichiers, groupes, compression audio (Opus)
pour consommer moins de données, notifications Windows.
