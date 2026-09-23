# Messagerie chiffrée (messages + appels)

Petite messagerie en Python : messages texte et appels audio, **chiffrés de bout en bout**,
avec une interface moderne (CustomTkinter) et des **mises à jour automatiques**.

```
 Toi (Messagerie.exe) ── données chiffrées ──► Serveur relais (Render) ── données chiffrées ──► Ton ami
     clé privée                               ne voit rien du contenu                         clé privée
```

## Organisation du dépôt GitHub

```
.github/workflows/publier.yml   ← construit l'exe et publie les mises à jour (GitHub Actions)
messagerie/
  render.yaml                   ← configuration du serveur sur Render
  serveur/server.py             ← le relais
  client/app.py                 ← l'interface
  client/noyau.py               ← réseau, chiffrement, appels, réglages audio
  client/maj.py                 ← mises à jour automatiques
  client/version.py             ← numéro de version (géré automatiquement)
```

⚠ Le dossier `.github` doit être **à la racine** du dépôt (à côté du dossier `messagerie`),
pas dedans.

---

## Mises à jour : comment ça marche

1. Tu modifies un fichier de `messagerie/client/` et tu fais un commit sur GitHub.
2. **GitHub Actions** construit automatiquement `Messagerie.exe` sous Windows (≈ 3 min) et
   publie une **Release** numérotée (v1, v2, v3…). Tu peux suivre ça dans l'onglet **Actions**.
3. Chaque appli installée vérifie GitHub **au lancement puis toutes les 30 min**. S'il y a une
   nouvelle version, un **bandeau bleu « Mettre à jour »** apparaît : un clic, l'appli
   télécharge, se remplace et redémarre toute seule.

**Mise à jour obligatoire** : pour les changements qui cassent la compatibilité (nouveau
format de message, etc.), augmente `PROTOCOLE` de 1 dans `client/noyau.py` **et** dans
`serveur/server.py`. Le serveur refusera alors les anciennes applis avec une fenêtre
« Mise à jour obligatoire → Mettre à jour ».
Pour une petite correction (couleur, texte…), ne touche pas à `PROTOCOLE` : la mise à jour
reste proposée sans couper personne en plein appel.

**Première installation pour un ami** : il télécharge `Messagerie.exe` dans la page
**Releases** du dépôt (colonne de droite sur GitHub). Ensuite, il n'aura plus jamais besoin
d'y retourner. Windows peut afficher « Windows a protégé votre ordinateur » (exe non signé) :
*Informations complémentaires → Exécuter quand même*.

---

## Réglages du son pendant un appel

Pendant un appel, le panneau d'appel affiche :
- **🎤 Mon micro (gain)** 0 à 200 % : ce que l'autre entend de toi (monte-le si on t'entend mal) ;
- **🔊 Volume de <contact>** 0 à 200 % : le volume de l'autre dans tes oreilles ;
- un **vu-mètre** vert à côté de chaque curseur pour voir le son passer ;
- **Couper le micro** et **Raccrocher**.

Les réglages sont mémorisés pour les prochains appels. Au-delà de 100 %, le son peut saturer
si la source est déjà forte. **Prends un casque** pour éviter l'écho.

---

## Lancer depuis le code (pour développer)

Python 3.10+ :
```bash
cd messagerie/client
pip install -r requirements.txt
python app.py
```
La version « code source » se met aussi à jour avec le bandeau (elle remplace ses fichiers `.py`).
`creer_exe.bat` permet de construire l'exe à la main si besoin.

## Serveur (Render)

Déjà en place. Chaque commit qui modifie `messagerie/serveur/` le redéploie automatiquement.
Serveur gratuit : il s'endort après 15 min sans activité et met ~1 min à se réveiller
(l'appli patiente toute seule).

---

## Sécurité

- Au premier lancement, l'appli crée une **paire de clés** X25519 dans le dossier `.messagerie`
  de ton compte. La clé **privée ne quitte jamais ton ordinateur**.
- Messages et audio sont chiffrés et authentifiés avec **libsodium** (XSalsa20-Poly1305) :
  le serveur ne voit que du charabia, et toute modification en route est détectée.
- **Code de sécurité** : à comparer une fois de vive voix ; s'il est identique chez vous deux,
  personne ne peut se glisser entre vous. L'appli prévient si la clé d'un contact change.
- Les mises à jour viennent uniquement de **ton** dépôt GitHub (en HTTPS). Protège bien ton
  compte GitHub (active la double authentification) : quelqu'un qui en prendrait le contrôle
  pourrait publier une fausse mise à jour.

**Limites** : pas de confidentialité persistante (forward secrecy) ; le serveur voit qui parle à
qui et quand ; l'historique n'est pas sauvegardé à la fermeture.
