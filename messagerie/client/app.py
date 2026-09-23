"""
Messagerie chiffrée - interface graphique (Tkinter).
Lancement :  python app.py
"""

import json
import queue
import time
import tkinter as tk
from tkinter import messagebox, ttk

from noyau import DOSSIER, Messagerie

FICHIER_CONFIG = DOSSIER / "config.json"


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


class Application:
    def __init__(self, racine: tk.Tk):
        self.racine = racine
        self.racine.title("Messagerie chiffrée")
        self.racine.geometry("760x520")
        self.racine.minsize(600, 400)
        self.evenements = queue.Queue()
        self.noyau = None
        self.contact = None                      # contact sélectionné
        self.historique: dict[str, list] = {}    # nom -> [(auteur, texte, ts)]
        self.non_lus: dict[str, int] = {}
        self.noms_liste: list[str] = []
        self.ecran_connexion()

    # ================================================================ connexion
    def ecran_connexion(self):
        self.cadre_connexion = ttk.Frame(self.racine, padding=30)
        self.cadre_connexion.pack(expand=True)
        config = {}
        if FICHIER_CONFIG.exists():
            config = json.loads(FICHIER_CONFIG.read_text())

        ttk.Label(self.cadre_connexion, text="🔒 Messagerie chiffrée",
                  font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 20))
        ttk.Label(self.cadre_connexion, text="Adresse du serveur :").grid(row=1, column=0, sticky="w")
        self.champ_serveur = ttk.Entry(self.cadre_connexion, width=38)
        self.champ_serveur.insert(0, config.get("serveur", "ton-serveur.onrender.com"))
        self.champ_serveur.grid(row=1, column=1, pady=5)
        ttk.Label(self.cadre_connexion, text="Ton pseudo :").grid(row=2, column=0, sticky="w")
        self.champ_pseudo = ttk.Entry(self.cadre_connexion, width=38)
        self.champ_pseudo.insert(0, config.get("pseudo", ""))
        self.champ_pseudo.grid(row=2, column=1, pady=5)
        self.champ_pseudo.bind("<Return>", lambda e: self.se_connecter())
        ttk.Button(self.cadre_connexion, text="Se connecter",
                   command=self.se_connecter).grid(row=3, column=0, columnspan=2, pady=15)
        ttk.Label(self.cadre_connexion, foreground="gray",
                  text="Ta clé secrète est créée et gardée sur cet ordinateur.").grid(row=4, column=0, columnspan=2)

    def se_connecter(self):
        serveur = self.champ_serveur.get().strip()
        pseudo = self.champ_pseudo.get().strip()
        if not serveur or not pseudo:
            messagebox.showwarning("Messagerie", "Remplis l'adresse du serveur et ton pseudo.")
            return
        DOSSIER.mkdir(parents=True, exist_ok=True)
        FICHIER_CONFIG.write_text(json.dumps({"serveur": serveur, "pseudo": pseudo}))
        self.noyau = Messagerie(normaliser_url(serveur), pseudo, self.evenements.put)
        self.cadre_connexion.destroy()
        self.ecran_principal()
        self.noyau.demarrer()
        self.racine.after(30, self.lire_evenements)

    # ================================================================ écran principal
    def ecran_principal(self):
        self.etat = ttk.Label(self.racine, text="Connexion au serveur… (jusqu'à 1 min s'il était endormi)",
                              padding=(8, 4), foreground="gray")
        self.etat.pack(fill="x")

        corps = ttk.Frame(self.racine)
        corps.pack(fill="both", expand=True)

        # --- Liste des contacts
        gauche = ttk.Frame(corps, padding=6)
        gauche.pack(side="left", fill="y")
        ttk.Label(gauche, text="Contacts", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.liste = tk.Listbox(gauche, width=24, activestyle="none", font=("Segoe UI", 10))
        self.liste.pack(fill="y", expand=True)
        self.liste.bind("<<ListboxSelect>>", self.choisir_contact)

        # --- Zone de conversation
        droite = ttk.Frame(corps, padding=6)
        droite.pack(side="left", fill="both", expand=True)

        entete = ttk.Frame(droite)
        entete.pack(fill="x")
        self.titre = ttk.Label(entete, text="Choisis un contact", font=("Segoe UI", 12, "bold"))
        self.titre.pack(side="left")
        self.bouton_appel = ttk.Button(entete, text="📞 Appeler", command=self.appeler, state="disabled")
        self.bouton_appel.pack(side="right")
        self.bouton_code = ttk.Button(entete, text="🔒 Code de sécurité",
                                      command=self.afficher_code, state="disabled")
        self.bouton_code.pack(side="right", padx=4)

        # Barre d'appel (visible seulement pendant un appel)
        self.barre_appel = tk.Frame(droite, bg="#e8f5e9", padx=8, pady=6)
        self.texte_appel = tk.Label(self.barre_appel, bg="#e8f5e9", font=("Segoe UI", 10, "bold"))
        self.texte_appel.pack(side="left")
        self.bouton_raccrocher = ttk.Button(self.barre_appel, text="Raccrocher", command=self.raccrocher)
        self.bouton_raccrocher.pack(side="right")
        self.bouton_muet = ttk.Button(self.barre_appel, text="🎤 Couper le micro", command=self.muet)
        self.bouton_accepter = ttk.Button(self.barre_appel, text="✅ Décrocher", command=self.accepter)

        self.fil = tk.Text(droite, wrap="word", state="disabled", font=("Segoe UI", 10),
                           padx=8, pady=8, relief="flat", bg="#fafafa")
        self.fil.pack(fill="both", expand=True, pady=6)
        self.fil.tag_configure("moi", justify="right", foreground="#0b57d0", rmargin=4)
        self.fil.tag_configure("lui", justify="left", foreground="#1f1f1f", lmargin1=4)
        self.fil.tag_configure("info", justify="center", foreground="gray",
                               font=("Segoe UI", 9, "italic"))
        self.fil.tag_configure("heure", foreground="gray", font=("Segoe UI", 8))

        bas = ttk.Frame(droite)
        bas.pack(fill="x")
        self.saisie = ttk.Entry(bas, font=("Segoe UI", 10))
        self.saisie.pack(side="left", fill="x", expand=True)
        self.saisie.bind("<Return>", lambda e: self.envoyer())
        ttk.Button(bas, text="Envoyer", command=self.envoyer).pack(side="left", padx=(6, 0))

        self.racine.protocol("WM_DELETE_WINDOW", self.quitter)

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
        if t == "connecte":
            self.etat.config(text=f"🔒 Connecté en tant que {self.noyau.pseudo} — chiffrement de bout en bout",
                             foreground="green")
        elif t == "deconnecte":
            self.etat.config(text="⚠ Déconnecté, nouvelle tentative…", foreground="#b3261e")
        elif t == "fatal":
            messagebox.showerror("Messagerie", ev["msg"])
            self.quitter()
        elif t == "erreur":
            self.ajouter_info(self.contact, ev["msg"]) if self.contact else messagebox.showwarning("Messagerie", ev["msg"])
        elif t == "utilisateurs":
            self.maj_liste()
        elif t == "cle_changee":
            self.cle_changee(ev["user"])
        elif t == "message":
            self.historique.setdefault(ev["de"], []).append((ev["de"], ev["texte"], ev["ts"]))
            if ev["de"] == self.contact:
                self.afficher_fil()
            else:
                self.non_lus[ev["de"]] = self.non_lus.get(ev["de"], 0) + 1
                self.maj_liste()
            self.racine.bell()
        elif t == "appel":
            self.maj_appel(ev)

    # ================================================================ contacts
    def maj_liste(self):
        annuaire = self.noyau.annuaire
        noms = sorted(set(annuaire) | set(self.historique),
                      key=lambda n: (not annuaire.get(n, {}).get("online"), n.lower()))
        self.noms_liste = noms
        self.liste.delete(0, "end")
        for nom in noms:
            en_ligne = annuaire.get(nom, {}).get("online")
            badge = f"  ({self.non_lus[nom]})" if self.non_lus.get(nom) else ""
            self.liste.insert("end", f"{'🟢' if en_ligne else '⚪'} {nom}{badge}")
            if nom == self.contact:
                self.liste.selection_set("end")

    def choisir_contact(self, _e=None):
        sel = self.liste.curselection()
        if not sel:
            return
        self.contact = self.noms_liste[sel[0]]
        self.non_lus.pop(self.contact, None)
        self.titre.config(text=self.contact)
        self.bouton_code.config(state="normal")
        self.bouton_appel.config(state="disabled" if self.noyau.appel else "normal")
        self.afficher_fil()
        self.maj_liste()
        self.saisie.focus()

    def afficher_code(self):
        code = self.noyau.code_securite_avec(self.contact)
        messagebox.showinfo(
            "Code de sécurité",
            f"Code de sécurité avec {self.contact} :\n\n{code}\n\n"
            "Comparez ce code de vive voix (en appel ou en vrai). "
            "S'il est identique chez vous deux, personne ne peut intercepter vos échanges.")

    def cle_changee(self, nom):
        ok = messagebox.askyesno(
            "⚠ Clé de sécurité modifiée",
            f"La clé de chiffrement de « {nom} » a changé.\n\n"
            "C'est normal s'il/elle a réinstallé l'application ou changé d'ordinateur. "
            "Sinon, quelqu'un essaie peut-être de se faire passer pour lui/elle.\n\n"
            "Accepter la nouvelle clé ? (vérifie ensuite le code de sécurité avec cette personne)")
        if ok:
            self.noyau.accepter_nouvelle_cle(nom)
        self.ajouter_info(nom, "Clé de sécurité modifiée" + (" (acceptée)" if ok else " (refusée)"))

    # ================================================================ messages
    def afficher_fil(self):
        self.fil.config(state="normal")
        self.fil.delete("1.0", "end")
        for auteur, texte, ts in self.historique.get(self.contact, []):
            heure = time.strftime("%H:%M", time.localtime(ts))
            if auteur is None:
                self.fil.insert("end", f"{texte}\n\n", "info")
            else:
                tag = "moi" if auteur == self.noyau.pseudo else "lui"
                self.fil.insert("end", f"{texte}\n", tag)
                self.fil.insert("end", f"{heure}\n\n", (tag, "heure"))
        self.fil.config(state="disabled")
        self.fil.see("end")

    def ajouter_info(self, nom, texte):
        if not nom:
            return
        self.historique.setdefault(nom, []).append((None, texte, time.time()))
        if nom == self.contact:
            self.afficher_fil()

    def envoyer(self):
        texte = self.saisie.get().strip()
        if not texte or not self.contact:
            return
        if not self.noyau.envoyer_message(self.contact, texte):
            messagebox.showwarning("Messagerie", "Envoi impossible (pas connecté, ou clé du contact non validée).")
            return
        self.saisie.delete(0, "end")
        self.historique.setdefault(self.contact, []).append((self.noyau.pseudo, texte, time.time()))
        self.afficher_fil()

    # ================================================================ appels
    def appeler(self):
        if self.contact and not self.noyau.appeler(self.contact):
            messagebox.showwarning("Messagerie", "Appel impossible pour le moment.")

    def accepter(self):
        self.noyau.accepter()

    def raccrocher(self):
        self.noyau.raccrocher()

    def muet(self):
        coupe = self.noyau.basculer_muet()
        self.bouton_muet.config(text="🔇 Réactiver le micro" if coupe else "🎤 Couper le micro")

    def maj_appel(self, ev):
        etat, avec = ev["etat"], ev["avec"]
        self.bouton_accepter.pack_forget()
        self.bouton_muet.pack_forget()
        if etat == "fini":
            self.barre_appel.pack_forget()
            self.bouton_appel.config(state="normal" if self.contact else "disabled")
            self.ajouter_info(avec, f"📞 {ev.get('msg', 'Appel terminé')}")
            return
        self.bouton_appel.config(state="disabled")
        self.barre_appel.pack(fill="x", pady=(6, 0), after=self.titre.master)
        if etat == "sortant":
            self.texte_appel.config(text=f"📞 Appel de {avec} en cours… (sonnerie)")
            self.bouton_raccrocher.config(text="Annuler")
        elif etat == "entrant":
            self.texte_appel.config(text=f"📞 {avec} t'appelle !")
            self.bouton_raccrocher.config(text="Refuser")
            self.bouton_accepter.pack(side="right", padx=4)
            self.racine.deiconify()
            self.racine.lift()
            self.racine.bell()
        elif etat == "en_cours":
            self.texte_appel.config(text=f"🔒 En appel chiffré avec {avec}")
            self.bouton_raccrocher.config(text="Raccrocher")
            self.bouton_muet.config(text="🎤 Couper le micro")
            self.bouton_muet.pack(side="right", padx=4)
            self.ajouter_info(avec, "📞 Appel démarré")

    def quitter(self):
        if self.noyau:
            self.noyau.arreter()
        self.racine.after(200, self.racine.destroy)


if __name__ == "__main__":
    racine = tk.Tk()
    try:
        ttk.Style().theme_use("vista")      # Windows
    except tk.TclError:
        pass
    Application(racine)
    racine.mainloop()
