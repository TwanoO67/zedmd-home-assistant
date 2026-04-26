# ZeDMD Home Assistant Integration — Instructions Claude Code

## Workflow Git obligatoire après chaque modification

Après toute modification de fichiers dans `custom_components/zedmd/`, exécuter dans cet ordre :

### 1. Mettre à jour la version dans `manifest.json`
```json
"version": "X.Y.Z"
```
Le numéro de version doit correspondre exactement au tag GitHub (sans le `v`).

### 2. Commiter, tagger et pousser
```bash
git add -A
git commit -m "Description courte de la modification"
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "Description des changements"
```

### Règles importantes
- Le tag GitHub `vX.Y.Z` doit correspondre à `manifest.json` `"version": "X.Y.Z"` (sans le `v`)
- Toujours créer une **release GitHub** (pas juste un tag) pour que HACS détecte la mise à jour
- HACS vérifie automatiquement toutes les 3h — forcer via : HACS → ZeDMD → ⋮ → Vérifier les mises à jour

---

## Contexte du projet

- **Hardware** : LED matrix 128×32 HUB75, ESP32 ZeDMD firmware 5.1.8, WiFi TCP
- **Protocole** : HTTP handshake sur `/handshake` (port 80 défaut) → TCP streaming port 3333
- **Format paquet** : `b"FRAME"(5) + b"ZeDMD"(5) + cmd(1) + size_hi(1) + size_lo(1) + 0x00(1) + payload`
- **Pas d'ACK** en mode WiFi/TCP (ACK uniquement sur série)
- **Pillow** requis pour le rendu texte

## Installation HA
Copier `custom_components/zedmd/` dans `/config/custom_components/zedmd/` puis redémarrer HA.
