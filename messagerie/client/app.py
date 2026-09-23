"""
Messagerie chiffrée - interface graphique (CustomTkinter).
Lancement :  python app.py
"""

import json
import queue
import threading
import time
import tkinter as tk

import customtkinter as ctk

import maj
from noyau import DOSSIER, Messagerie
from version import VERSION

FICHIER_CONFIG = DOSSIER / "config.json"

# ------------------------------------------------------------------ thème
FOND = "#0f1115"
PANNEAU = "#161a21"
CARTE = "#1e232c"
SURVOL = "#262c37"
BORD = "#2a303b"
ACCENT = "#5b7cfa"
ACCENT_SURVOL = "#4a69e0"
TEXTE = "#e8eaed"
DISCRET = "#8b93a1"
VERT = "#22c55e"
VERT_SURVOL = "#16a34a"
ROUGE = "#ef4444"
ROUGE_SURVOL = "#dc2626"
BULLE_MOI = "#4f6ef7"
BULLE_LUI = "#262c36"
COULEURS_AVATAR = ["#f97316", "#8b5cf6", "#06b6d4", "#ec4899", "#10b981", "#eab308", "#3b82f6"]

ctk.set_appearance_mode("dark")


def couleur_avatar(nom: str) -> str:
    return COULEURS_AVATAR[sum(map(ord, nom)) % len(COULEURS_AVATAR)]


def normaliser_url(adresse: str) -> str:
    adresse = adresse.strip().rstrip("/")
    if adresse.startswith(("ws://", "wss://")):
        return adresse
    if adresse.startswith("https://"):
        return "wss://" + adresse[8:]
    if adresse.startswith("http://"):
        return "ws://" + adresse[7:]
    if adresse.startswith(("localhost", "127.", "192.168.")):
        return "ws://" + adresse
    return "wss://" + adresse


def lire_config() -> dict:
    try:
        return json.loads(FICHIER_CONFIG.read_text())
    except Exception:
        return {}


def ecrire_config(**valeurs):
    config = lire_config()
    config.update(valeurs)
    DOSSIER.mkdir(parents=True, exist_ok=True)
    FICHIER_CONFIG.write_text(json.dumps(config, indent=2))


def police(taille=13, gras=False):
    return ctk.CTkFont(size=taille, weight="bold" if gras else "normal")


class Avatar(ctk.CTkLabel):
    def __init__(self, parent, nom, taille=38):
        super().__init__(parent, text=nom[:1].upper(), width=taille, height=taille,
                         corner_radius=taille // 2, fg_color=couleur_avatar(nom),
                         text_color="white", font=police(int(taille * 0.42), True))


# ======================================================================
class Dialogue(ctk.CTkToplevel):
    """Petite fenêtre modale : Dialogue(parent, titre, texte, ["Oui", "Non"]).choix"""

    def __init__(self, parent, titre, texte, boutons=("OK",), couleurs=None):
        super().__init__(parent, fg_color=PANNEAU)
        self.title(titre)
        self.resizable(False, False)
        self.choix = None
        ctk.CTkLabel(self, text=titre, font=police(17, True), text_color=TEXTE).pack(
            padx=28, pady=(24, 8), anchor="w")
        ctk.CTkLabel(self, text=texte, font=police(13), text_color=DISCRET, justify="left",
                     wraplength=380).pack(padx=28, anchor="w")
        rangee = ctk.CTkFrame(self, fg_color="transparent")
        rangee.pack(fill="x", padx=28, pady=24)
        couleurs = couleurs or {}
        for i, b in enumerate(reversed(boutons)):
            principal = i == 0
            ctk.CTkButton(rangee, text=b, width=110, height=36, corner_radius=10,
                          fg_color=couleurs.get(b, ACCENT if principal else CARTE),
                          hover_color=ACCENT_SURVOL if principal else SURVOL,
                          command=lambda b=b: self._choisir(b)).pack(side="right", padx=(8, 0))
        self.transient(parent)
        self.after(50, self._premier_plan)
        self.wait_window()

    def _premier_plan(self):
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _choisir(self, b):
        self.choix = b
        self.destroy()


# ======================================================================
class Application:
    def __init__(self, racine: ctk.CTk):
        self.racine = racine
        racine.title("Messagerie")
        racine.geometry("1000x660")
        racine.minsize(760, 500)
        racine.configure(fg_color=FOND)

        self.evenements = queue.Queue()
        self.config = lire_config()
        self.noyau = None
        self.contact = None
        self.historique: dict[str, list] = {}
        self.non_lus: dict[str, int] = {}
        self.maj_dispo = None
        self.debut_appel = None
        self._sauvegarde_audio = None

        maj.nettoyer()
        # Bandeau de mise à jour (caché par défaut), au-dessus de tout
        self.banniere = ctk.CTkFrame(racine, fg_color=ACCENT, corner_radius=0, height=40)
        self.texte_banniere = ctk.CTkLabel(self.banniere, text="", text_color="white", font=police(13, True))
        self.texte_banniere.pack(side="left", padx=16)
        ctk.CTkButton(self.banniere, text="Mettre à jour", width=120, height=28, corner_radius=8,
                      fg_color="white", text_color=ACCENT, hover_color="#e6e9ff",
                      command=self.lancer_maj).pack(side="right", padx=12, pady=6)

        self.contenu = ctk.CTkFrame(racine, fg_color=FOND, corner_radius=0)
        self.contenu.pack(fill="both", expand=True)
        self.ecran_connexion()

        self.racine.after(30, self.lire_evenements)
        self.verifier_maj()

    # ================================================================ mises à jour
    def verifier_maj(self):
        threading.Thread(target=lambda: self.evenements.put({"type": "maj_dispo", "info": maj.verifier()}),
                         daemon=True).start()
        self.racine.after(30 * 60 * 1000, self.verifier_maj)   # toutes les 30 minutes

    def afficher_banniere(self, info):
        self.maj_dispo = info
        if not info:
            return
        self.texte_banniere.configure(text=f"⬆  Nouvelle version disponible ({info['version']})"
                                           + (f" — {info['notes'][:80]}" if info["notes"] else ""))
        if not self.banniere.winfo_ismapped():
            self.banniere.pack(fill="x", before=self.contenu)

    def lancer_maj(self, obligatoire=False):
        if self.noyau and self.noyau.appel:
            if Dialogue(self.racine, "Appel en cours",
                        "La mise à jour va couper l'appel. Continuer ?",
                        ["Annuler", "Continuer"]).choix != "Continuer":
                return
        fen = ctk.CTkToplevel(self.racine, fg_color=PANNEAU)
        fen.title("Mise à jour")
        fen.resizable(False, False)
        fen.transient(self.racine)
        ctk.CTkLabel(fen, text="Mise à jour en cours", font=police(17, True)).pack(padx=30, pady=(24, 10))
        etat = ctk.CTkLabel(fen, text="Recherche de la nouvelle version…", text_color=DISCRET)
        etat.pack(padx=30)
        barre = ctk.CTkProgressBar(fen, width=320, progress_color=ACCENT)
        barre.pack(padx=30, pady=(12, 28))
        barre.configure(mode="indeterminate")
        barre.start()
        self._fenetre_maj = (fen, etat, barre)

        def travail():
            try:
                info = self.maj_dispo or maj.verifier()
                if not info:
                    raise RuntimeError("Aucune nouvelle version trouvée sur GitHub.")
                maj.installer(info, lambda f, t: self.evenements.put({"type": "maj_progression",
                                                                      "frac": f, "texte": t}))
                self.evenements.put({"type": "maj_ok"})
            except Exception as e:
                self.evenements.put({"type": "maj_erreur", "msg": str(e), "obligatoire": obligatoire})
        threading.Thread(target=travail, daemon=True).start()

    def progression_maj(self, ev):
        fen, etat, barre = self._fenetre_maj
        etat.configure(text=ev["texte"])
        if ev["frac"] is None:
            if barre.cget("mode") != "indeterminate":
                barre.configure(mode="indeterminate")
                barre.start()
        else:
            barre.stop()
            barre.configure(mode="determinate")
            barre.set(ev["frac"])

    # ================================================================ connexion
    def ecran_connexion(self):
        cadre = ctk.CTkFrame(self.contenu, fg_color=PANNEAU, corner_radius=20, border_width=1,
                             border_color=BORD)
        cadre.place(relx=0.5, rely=0.5, anchor="center")
        self.cadre_connexion = cadre

        ctk.CTkLabel(cadre, text="🔒", font=police(40)).pack(pady=(34, 0))
        ctk.CTkLabel(cadre, text="Messagerie", font=police(26, True), text_color=TEXTE).pack()
        ctk.CTkLabel(cadre, text="Messages et appels chiffrés de bout en bout",
                     font=police(13), text_color=DISCRET).pack(pady=(2, 24))

        def champ(etiquette, valeur, indice):
            ctk.CTkLabel(cadre, text=etiquette, font=police(12, True), text_color=DISCRET).pack(
                padx=40, anchor="w")
            e = ctk.CTkEntry(cadre, width=330, height=42, corner_radius=10, fg_color=CARTE,
                             border_color=BORD, placeholder_text=indice, font=police(14))
            if valeur:
                e.insert(0, valeur)
            e.pack(padx=40, pady=(4, 14))
            return e

        self.champ_serveur = champ("SERVEUR", self.config.get("serveur", ""), "messagerie-relais.onrender.com")
        self.champ_pseudo = champ("PSEUDO", self.config.get("pseudo", ""), "Ton pseudo")
        self.champ_pseudo.bind("<Return>", lambda e: self.se_connecter())
        self.champ_serveur.bind("<Return>", lambda e: self.se_connecter())

        ctk.CTkButton(cadre, text="Se connecter", width=330, height=44, corner_radius=10,
                      font=police(14, True), fg_color=ACCENT, hover_color=ACCENT_SURVOL,
                      command=self.se_connecter).pack(padx=40, pady=(6, 14))
        ctk.CTkLabel(cadre, text=f"Ta clé secrète reste sur cet ordinateur  ·  v{VERSION}",
                     font=police(11), text_color=DISCRET).pack(pady=(0, 26))
        (self.champ_pseudo if self.champ_serveur.get() else self.champ_serveur).focus()

    def se_connecter(self):
        serveur = self.champ_serveur.get().strip()
        pseudo = self.champ_pseudo.get().strip()
        if not serveur or not pseudo:
            Dialogue(self.racine, "Champs manquants", "Remplis l'adresse du serveur et ton pseudo.")
            return
        ecrire_config(serveur=serveur, pseudo=pseudo)
        self.noyau = Messagerie(normaliser_url(serveur), pseudo, self.evenements.put,
                                gain_micro=self.config.get("gain_micro", 1.0),
                                volume=self.config.get("volume", 1.0))
        self.cadre_connexion.destroy()
        self.ecran_principal()
        self.noyau.demarrer()

    # ================================================================ écran principal
    def ecran_principal(self):
        self.contenu.grid_columnconfigure(1, weight=1)
        self.contenu.grid_rowconfigure(0, weight=1)

        # ---------------- barre latérale
        cote = ctk.CTkFrame(self.contenu, fg_color=PANNEAU, corner_radius=0, width=280)
        cote.grid(row=0, column=0, sticky="nsew")
        cote.grid_propagate(False)
        cote.pack_propagate(False)

        moi = ctk.CTkFrame(cote, fg_color="transparent")
        moi.pack(fill="x", padx=16, pady=(18, 10))
        Avatar(moi, self.noyau.pseudo, 42).pack(side="left")
        infos = ctk.CTkFrame(moi, fg_color="transparent")
        infos.pack(side="left", padx=12)
        ctk.CTkLabel(infos, text=self.noyau.pseudo, font=police(15, True), text_color=TEXTE,
                     anchor="w").pack(anchor="w")
        self.etat = ctk.CTkLabel(infos, text="● Connexion…", font=police(12), text_color=DISCRET, anchor="w")
        self.etat.pack(anchor="w")

        self.recherche = ctk.CTkEntry(cote, height=36, corner_radius=10, fg_color=CARTE, border_width=0,
                                      placeholder_text="🔍  Rechercher un contact")
        self.recherche.pack(fill="x", padx=16, pady=(6, 10))
        self.recherche.bind("<KeyRelease>", lambda e: self.maj_liste())

        ctk.CTkLabel(cote, text="CONTACTS", font=police(11, True), text_color=DISCRET).pack(
            anchor="w", padx=20)
        self.liste = ctk.CTkScrollableFrame(cote, fg_color="transparent")
        self.liste.pack(fill="both", expand=True, padx=6, pady=(4, 0))

        ctk.CTkLabel(cote, text=f"🔒 Chiffré de bout en bout  ·  v{VERSION}", font=police(11),
                     text_color=DISCRET).pack(pady=10)

        # ---------------- zone principale
        droite = ctk.CTkFrame(self.contenu, fg_color=FOND, corner_radius=0)
        droite.grid(row=0, column=1, sticky="nsew")
        self.droite = droite

        self.entete = ctk.CTkFrame(droite, fg_color=FOND, height=70, corner_radius=0)
        self.entete.pack(fill="x", padx=20, pady=(12, 0))
        self.zone_avatar = ctk.CTkFrame(self.entete, fg_color="transparent")
        self.zone_avatar.pack(side="left")
        titres = ctk.CTkFrame(self.entete, fg_color="transparent")
        titres.pack(side="left", padx=12)
        self.titre = ctk.CTkLabel(titres, text="", font=police(17, True), text_color=TEXTE, anchor="w")
        self.titre.pack(anchor="w")
        self.sous_titre = ctk.CTkLabel(titres, text="", font=police(12), text_color=DISCRET, anchor="w")
        self.sous_titre.pack(anchor="w")
        self.bouton_appel = ctk.CTkButton(self.entete, text="📞  Appeler", width=120, height=38,
                                          corner_radius=10, fg_color=VERT, hover_color=VERT_SURVOL,
                                          font=police(13, True), command=self.appeler)
        self.bouton_code = ctk.CTkButton(self.entete, text="🔒  Code de sécurité", width=160, height=38,
                                         corner_radius=10, fg_color=CARTE, hover_color=SURVOL,
                                         command=self.afficher_code)

        self.separateur = ctk.CTkFrame(droite, height=1, fg_color=BORD)
        self.separateur.pack(fill="x", pady=(12, 0))

        self.construire_panneau_appel(droite)

        self.fil = ctk.CTkScrollableFrame(droite, fg_color=FOND)
        self.fil.pack(fill="both", expand=True, padx=8, pady=4)
        self.fil.grid_columnconfigure(0, weight=1)

        self.barre_saisie = ctk.CTkFrame(droite, fg_color=PANNEAU, corner_radius=14)
        self.saisie = ctk.CTkEntry(self.barre_saisie, height=44, corner_radius=12, border_width=0,
                                   fg_color=PANNEAU, font=police(14), placeholder_text="Écris un message…")
        self.saisie.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=6)
        self.saisie.bind("<Return>", lambda e: self.envoyer())
        ctk.CTkButton(self.barre_saisie, text="➤", width=44, height=40, corner_radius=12,
                      font=police(18), fg_color=ACCENT, hover_color=ACCENT_SURVOL,
                      command=self.envoyer).pack(side="right", padx=(0, 8))

        self.afficher_vide()
        self.racine.protocol("WM_DELETE_WINDOW", self.quitter)

    def afficher_vide(self):
        for w in self.fil.winfo_children():
            w.destroy()
        vide = ctk.CTkFrame(self.fil, fg_color="transparent")
        vide.grid(row=0, column=0, pady=160)
        ctk.CTkLabel(vide, text="💬", font=police(44)).pack()
        ctk.CTkLabel(vide, text="Choisis un contact pour commencer", font=police(16, True),
                     text_color=TEXTE).pack(pady=(6, 2))
        ctk.CTkLabel(vide, text="Tes messages et appels sont chiffrés de bout en bout.",
                     font=police(13), text_color=DISCRET).pack()

    # ================================================================ panneau d'appel
    def construire_panneau_appel(self, parent):
        p = ctk.CTkFrame(parent, fg_color=CARTE, corner_radius=16, border_width=1, border_color=BORD)
        self.panneau_appel = p

        haut = ctk.CTkFrame(p, fg_color="transparent")
        haut.pack(fill="x", padx=18, pady=(14, 6))
        self.appel_titre = ctk.CTkLabel(haut, text="", font=police(15, True), text_color=TEXTE)
        self.appel_titre.pack(side="left")
        self.appel_duree = ctk.CTkLabel(haut, text="", font=police(13), text_color=DISCRET)
        self.appel_duree.pack(side="left", padx=10)

        self.bouton_raccrocher = ctk.CTkButton(haut, text="Raccrocher", width=110, height=34,
                                               corner_radius=10, fg_color=ROUGE, hover_color=ROUGE_SURVOL,
                                               font=police(13, True), command=lambda: self.noyau.raccrocher())
        self.bouton_raccrocher.pack(side="right")
        self.bouton_decrocher = ctk.CTkButton(haut, text="📞  Décrocher", width=120, height=34,
                                              corner_radius=10, fg_color=VERT, hover_color=VERT_SURVOL,
                                              font=police(13, True), command=lambda: self.noyau.accepter())
        self.bouton_muet = ctk.CTkButton(haut, text="🎤  Micro activé", width=140, height=34,
                                         corner_radius=10, fg_color=SURVOL, hover_color=BORD,
                                         command=self.muet)

        # Réglages audio
        self.reglages = ctk.CTkFrame(p, fg_color="transparent")
        self.reglages.grid_columnconfigure((1, 4), weight=1)

        def reglage(ligne, icone, texte, valeur, commande):
            ctk.CTkLabel(self.reglages, text=icone, font=police(16)).grid(row=ligne, column=0, padx=(0, 8))
            etiquette = ctk.CTkLabel(self.reglages, text=texte, font=police(12), text_color=DISCRET,
                                     width=150, anchor="w")
            etiquette.grid(row=ligne, column=1, sticky="w")
            curseur = ctk.CTkSlider(self.reglages, from_=0, to=200, number_of_steps=40, width=200,
                                    progress_color=ACCENT, button_color=TEXTE, button_hover_color="white",
                                    command=commande)
            curseur.set(valeur * 100)
            curseur.grid(row=ligne, column=2, padx=8)
            pourcent = ctk.CTkLabel(self.reglages, text=f"{int(valeur * 100)} %", width=48,
                                    font=police(12, True), text_color=TEXTE)
            pourcent.grid(row=ligne, column=3)
            vumetre = ctk.CTkProgressBar(self.reglages, height=6, progress_color=VERT, fg_color=BORD)
            vumetre.set(0)
            vumetre.grid(row=ligne, column=4, sticky="ew", padx=(12, 0))
            return etiquette, pourcent, vumetre

        _, self.pct_micro, self.vu_micro = reglage(
            0, "🎤", "Mon micro (gain)", self.config.get("gain_micro", 1.0), self.changer_gain)
        self.etiquette_volume, self.pct_volume, self.vu_contact = reglage(
            1, "🔊", "Volume du contact", self.config.get("volume", 1.0), self.changer_volume)
        for w in self.reglages.grid_slaves(row=0):
            w.grid_configure(pady=(0, 6))

    def changer_gain(self, valeur):
        self.pct_micro.configure(text=f"{int(valeur)} %")
        self.noyau.regler_gain_micro(valeur / 100)
        self._sauver_audio()

    def changer_volume(self, valeur):
        self.pct_volume.configure(text=f"{int(valeur)} %")
        self.noyau.regler_volume(valeur / 100)
        self._sauver_audio()

    def _sauver_audio(self):
        if self._sauvegarde_audio:
            self.racine.after_cancel(self._sauvegarde_audio)
        self._sauvegarde_audio = self.racine.after(
            600, lambda: ecrire_config(gain_micro=self.noyau.gain_micro, volume=self.noyau.volume))

    def animer_appel(self):
        if not (self.noyau and self.noyau.appel and self.noyau.appel["etat"] == "en_cours"):
            return
        micro, contact = self.noyau.niveaux()
        # lissage pour un vu-mètre agréable à l'œil
        self.vu_micro.set(max(micro, self.vu_micro.get() * 0.75))
        self.vu_contact.set(max(contact, self.vu_contact.get() * 0.75))
        s = int(time.time() - self.debut_appel)
        self.appel_duree.configure(text=f"{s // 60:02d}:{s % 60:02d}")
        self.racine.after(60, self.animer_appel)

    def muet(self):
        coupe = self.noyau.basculer_muet()
        self.bouton_muet.configure(text="🔇  Micro coupé" if coupe else "🎤  Micro activé",
                                   fg_color=ROUGE if coupe else SURVOL,
                                   hover_color=ROUGE_SURVOL if coupe else BORD)

    def maj_appel(self, ev):
        etat, avec = ev["etat"], ev["avec"]
        p = self.panneau_appel
        self.bouton_decrocher.pack_forget()
        self.bouton_muet.pack_forget()
        self.reglages.pack_forget()
        if etat == "fini":
            p.pack_forget()
            self.debut_appel = None
            self.ajouter_info(avec, f"📞 {ev.get('msg', 'Appel terminé')}")
            self.maj_entete()
            return
        if not p.winfo_ismapped():
            p.pack(fill="x", padx=20, pady=(12, 4), after=self.separateur)
        self.appel_duree.configure(text="")
        if etat == "sortant":
            self.appel_titre.configure(text=f"📞  Appel de {avec}…")
            self.bouton_raccrocher.configure(text="Annuler")
        elif etat == "entrant":
            self.appel_titre.configure(text=f"📞  {avec} t'appelle")
            self.bouton_raccrocher.configure(text="Refuser")
            self.bouton_decrocher.pack(side="right", padx=8)
            self.racine.deiconify()
            self.racine.lift()
            self.racine.bell()
            if self.contact != avec:
                self.choisir_contact(avec)
        elif etat == "en_cours":
            self.appel_titre.configure(text=f"🔒  En appel avec {avec}")
            self.bouton_raccrocher.configure(text="Raccrocher")
            self.bouton_muet.configure(text="🎤  Micro activé", fg_color=SURVOL, hover_color=BORD)
            self.bouton_muet.pack(side="right", padx=8)
            self.etiquette_volume.configure(text=f"Volume de {avec}")
            self.reglages.pack(fill="x", padx=18, pady=(4, 14))
            self.debut_appel = time.time()
            self.ajouter_info(avec, "📞 Appel démarré")
            self.animer_appel()
        self.maj_entete()

    # ================================================================ événements du noyau
    def lire_evenements(self):
        try:
            while True:
                self.traiter(self.evenements.get_nowait())
        except queue.Empty:
            pass
        self.racine.after(30, self.lire_evenements)

    def traiter(self, ev):
        t = ev["type"]
        if t == "maj_dispo":
            self.afficher_banniere(ev["info"])
        elif t == "maj_progression":
            self.progression_maj(ev)
        elif t == "maj_ok":
            if self.noyau:
                self.noyau.arreter()
            maj.redemarrer()
        elif t == "maj_erreur":
            self._fenetre_maj[0].destroy()
            Dialogue(self.racine, "Mise à jour impossible", ev["msg"])
            if ev.get("obligatoire"):
                self.quitter()
        elif t == "connecte":
            self.etat.configure(text="● En ligne", text_color=VERT)
        elif t == "deconnecte":
            self.etat.configure(text="● Reconnexion…", text_color="#f59e0b")
        elif t == "fatal":
            if ev.get("maj"):
                choix = Dialogue(self.racine, "Mise à jour obligatoire", ev["msg"],
                                 ["Quitter", "Mettre à jour"]).choix
                if choix == "Mettre à jour":
                    self.lancer_maj(obligatoire=True)
                else:
                    self.quitter()
            else:
                Dialogue(self.racine, "Connexion refusée", ev["msg"])
                self.quitter()
        elif t == "erreur":
            if self.contact:
                self.ajouter_info(self.contact, "⚠ " + ev["msg"])
            else:
                Dialogue(self.racine, "Attention", ev["msg"])
        elif t == "utilisateurs":
            self.maj_liste()
            self.maj_entete()
        elif t == "cle_changee":
            self.cle_changee(ev["user"])
        elif t == "message":
            self.historique.setdefault(ev["de"], []).append((ev["de"], ev["texte"], ev["ts"]))
            if ev["de"] == self.contact:
                self.ajouter_bulle(ev["de"], ev["texte"], ev["ts"])
            else:
                self.non_lus[ev["de"]] = self.non_lus.get(ev["de"], 0) + 1
                self.maj_liste()
                self.racine.bell()
        elif t == "appel":
            self.maj_appel(ev)

    # ================================================================ contacts
    def maj_liste(self):
        for w in self.liste.winfo_children():
            w.destroy()
        annuaire = self.noyau.annuaire
        filtre = self.recherche.get().strip().lower()
        noms = sorted((n for n in set(annuaire) | set(self.historique) if filtre in n.lower()),
                      key=lambda n: (not annuaire.get(n, {}).get("online"), n.lower()))
        if not noms:
            ctk.CTkLabel(self.liste, text="Personne pour l'instant…\nDonne l'adresse du serveur à tes amis !",
                         text_color=DISCRET, font=police(12)).pack(pady=30)
        for nom in noms:
            self.ligne_contact(nom, annuaire.get(nom, {}).get("online", False))

    def ligne_contact(self, nom, en_ligne):
        choisi = nom == self.contact
        ligne = ctk.CTkFrame(self.liste, fg_color=SURVOL if choisi else "transparent", corner_radius=12,
                             height=58)
        ligne.pack(fill="x", pady=2)
        ligne.pack_propagate(False)
        avatar = ctk.CTkFrame(ligne, fg_color="transparent", width=44, height=44)
        avatar.pack(side="left", padx=(10, 8))
        Avatar(avatar, nom, 40).place(x=0, y=2)
        ctk.CTkFrame(avatar, width=15, height=15, corner_radius=8, border_width=3,
                     border_color=SURVOL if choisi else PANNEAU,
                     fg_color=VERT if en_ligne else "#4b5563").place(x=28, y=29)
        textes = ctk.CTkFrame(ligne, fg_color="transparent")
        textes.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(textes, text=nom, font=police(14, True), text_color=TEXTE, anchor="w").pack(
            anchor="w", pady=(8, 0))
        dernier = self.historique.get(nom, [])
        apercu = next((txt for aut, txt, _ in reversed(dernier) if aut), None)
        sous = (apercu[:28] + "…" if apercu and len(apercu) > 28 else apercu) or \
               ("En ligne" if en_ligne else "Hors ligne")
        ctk.CTkLabel(textes, text=sous, font=police(12), text_color=DISCRET, anchor="w").pack(anchor="w")
        n = self.non_lus.get(nom)
        if n:
            ctk.CTkLabel(ligne, text=str(n), width=22, height=22, corner_radius=11, fg_color=ACCENT,
                         text_color="white", font=police(11, True)).pack(side="right", padx=12)

        def clic(_e, nom=nom):
            self.choisir_contact(nom)

        def survol(_e, actif):
            if nom != self.contact:
                ligne.configure(fg_color=CARTE if actif else "transparent")
        for w in [ligne, textes, avatar, *textes.winfo_children(), *avatar.winfo_children(),
                  *ligne.winfo_children()]:
            w.bind("<Button-1>", clic)
            w.bind("<Enter>", lambda e: survol(e, True))
            w.bind("<Leave>", lambda e: survol(e, False))

    def choisir_contact(self, nom):
        self.contact = nom
        self.non_lus.pop(nom, None)
        self.maj_entete()
        self.maj_liste()
        if not self.barre_saisie.winfo_ismapped():
            self.barre_saisie.pack(fill="x", padx=20, pady=(4, 18))
        self.afficher_fil()
        self.saisie.focus()

    def maj_entete(self):
        if not self.contact:
            return
        for w in self.zone_avatar.winfo_children():
            w.destroy()
        Avatar(self.zone_avatar, self.contact, 44).pack()
        en_ligne = self.noyau.annuaire.get(self.contact, {}).get("online")
        self.titre.configure(text=self.contact)
        self.sous_titre.configure(text="● En ligne" if en_ligne else "○ Hors ligne",
                                  text_color=VERT if en_ligne else DISCRET)
        self.bouton_appel.pack(side="right")
        self.bouton_code.pack(side="right", padx=8)
        occupe = bool(self.noyau.appel)
        self.bouton_appel.configure(state="disabled" if occupe else "normal",
                                    fg_color=CARTE if occupe else VERT)

    def afficher_code(self):
        code = self.noyau.code_securite_avec(self.contact)
        Dialogue(self.racine, "Code de sécurité",
                 f"Avec {self.contact} :\n\n{code}\n\n"
                 "Comparez ce code de vive voix. S'il est identique chez vous deux, "
                 "personne ne peut intercepter vos échanges.")

    def cle_changee(self, nom):
        choix = Dialogue(
            self.racine, "⚠ Clé de sécurité modifiée",
            f"La clé de chiffrement de « {nom} » a changé.\n\n"
            "C'est normal s'il/elle a réinstallé l'application ou changé d'ordinateur. "
            "Sinon, quelqu'un essaie peut-être de se faire passer pour lui/elle.\n\n"
            "Vérifie ensuite le code de sécurité avec cette personne.",
            ["Refuser", "Accepter"]).choix
        if choix == "Accepter":
            self.noyau.accepter_nouvelle_cle(nom)
        self.ajouter_info(nom, "Clé de sécurité modifiée" + (" (acceptée)" if choix == "Accepter" else " (refusée)"))

    # ================================================================ messages
    def afficher_fil(self):
        for w in self.fil.winfo_children():
            w.destroy()
        self._ligne_fil = 0
        messages = self.historique.get(self.contact, [])
        if not messages:
            ctk.CTkLabel(self.fil, text=f"🔒 Début de ta conversation chiffrée avec {self.contact}",
                         text_color=DISCRET, font=police(12)).grid(row=0, column=0, pady=20)
            self._ligne_fil = 1
        for auteur, texte, ts in messages:
            self.ajouter_bulle(auteur, texte, ts, defiler=False)
        self.defiler_bas()

    def ajouter_bulle(self, auteur, texte, ts, defiler=True):
        ligne = self._ligne_fil
        self._ligne_fil += 1
        if auteur is None:
            ctk.CTkLabel(self.fil, text=texte, text_color=DISCRET, font=police(12),
                         fg_color=PANNEAU, corner_radius=10).grid(row=ligne, column=0, pady=8, ipadx=10)
        else:
            moi = auteur == self.noyau.pseudo
            bulle = ctk.CTkFrame(self.fil, fg_color=BULLE_MOI if moi else BULLE_LUI, corner_radius=16)
            bulle.grid(row=ligne, column=0, sticky="e" if moi else "w",
                       padx=(120, 12) if moi else (12, 120), pady=3)
            ctk.CTkLabel(bulle, text=texte, font=police(14), text_color="white" if moi else TEXTE,
                         wraplength=420, justify="left", anchor="w").pack(padx=14, pady=(8, 0), anchor="w")
            ctk.CTkLabel(bulle, text=time.strftime("%H:%M", time.localtime(ts)), font=police(10),
                         text_color="#c7d2fe" if moi else DISCRET).pack(padx=12, pady=(0, 6), anchor="e")
        if defiler:
            self.defiler_bas()

    def defiler_bas(self):
        self.fil.after(30, lambda: self.fil._parent_canvas.yview_moveto(1.0))

    def ajouter_info(self, nom, texte):
        if not nom:
            return
        self.historique.setdefault(nom, []).append((None, texte, time.time()))
        if nom == self.contact:
            self.ajouter_bulle(None, texte, time.time())

    def envoyer(self):
        texte = self.saisie.get().strip()
        if not texte or not self.contact:
            return
        if not self.noyau.envoyer_message(self.contact, texte):
            Dialogue(self.racine, "Envoi impossible",
                     "Tu n'es pas connecté, ou la clé de ce contact n'a pas été acceptée.")
            return
        self.saisie.delete(0, "end")
        ts = time.time()
        self.historique.setdefault(self.contact, []).append((self.noyau.pseudo, texte, ts))
        self.ajouter_bulle(self.noyau.pseudo, texte, ts)
        self.maj_liste()

    # ================================================================ appels
    def appeler(self):
        if self.contact and not self.noyau.appeler(self.contact):
            Dialogue(self.racine, "Appel impossible",
                     "Tu n'es pas connecté, ou la clé de ce contact n'a pas été acceptée.")

    def quitter(self):
        if self.noyau:
            self.noyau.arreter()
        self.racine.after(200, self.racine.destroy)


if __name__ == "__main__":
    racine = ctk.CTk()
    Application(racine)
    racine.mainloop()
