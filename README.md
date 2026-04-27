# ZeDMD — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Intégration Home Assistant pour l'afficheur LED matriciel **ZeDMD** (128×32 HUB75, firmware ESP32 ZeDMDWiFi).

## Matériel supporté

- Matrice LED 128×32 HUB75
- Firmware ESP32 ZeDMD ≥ 5.x (WiFi TCP)
- Connexion : HTTP handshake sur le port 80 → streaming TCP sur le port 3333

## Installation via HACS

1. Ajouter ce dépôt comme dépôt personnalisé dans HACS (catégorie **Intégration**).
2. Installer **ZeDMD** depuis HACS.
3. Redémarrer Home Assistant.
4. Ajouter l'intégration via **Paramètres → Appareils et services → Ajouter une intégration → ZeDMD**.

## Installation manuelle

Copier le dossier `custom_components/zedmd/` dans `/config/custom_components/zedmd/` puis redémarrer HA.

## Configuration

| Champ | Description | Défaut |
|---|---|---|
| Host | Adresse IP ou nom d'hôte du ZeDMD | — |
| HTTP Port | Port du handshake HTTP | 80 |
| Stream Port | Port TCP du flux d'affichage | 3333 |

## Services disponibles

| Service | Description |
|---|---|
| `zedmd.display_text` | Affiche un texte (statique ou défilant) |
| `zedmd.clear_screen` | Efface l'écran |
| `zedmd.set_brightness` | Règle la luminosité (0–100 %) |
| `zedmd.test_pattern` | Envoie un cadre de couleur unie |
| `zedmd.play_gif` | Joue un GIF animé depuis une URL (avec ou sans boucle) |

## Bibliothèque GIF locale (Media Browser)

À partir de la **v1.2.0**, vous pouvez parcourir et lancer des GIFs locaux directement depuis la carte média de Home Assistant, avec aperçu.

### 1. Créer le dossier de la bibliothèque

Créez le dossier suivant dans votre installation Home Assistant :

```
/config/www/zedmd_gifs/
```

> Le dossier `/config/www/` est servi automatiquement par HA sous `/local/`. C'est ce qui permet d'afficher les vignettes dans le navigateur multimédia.

Méthodes pour créer ce dossier :
- **File Editor** (add-on) : naviguer dans `config` → créer `www/zedmd_gifs`
- **Samba** (add-on) : depuis l'explorateur Windows/macOS, dans `\\<HA>\config\`
- **SSH / Terminal** (add-on) : `mkdir -p /config/www/zedmd_gifs`

### 2. Déposer des fichiers GIF

Copiez vos fichiers `.gif` dans `/config/www/zedmd_gifs/`. Le nom du fichier (sans extension) sera affiché dans le navigateur multimédia.

```
/config/www/zedmd_gifs/
├── pacman.gif
├── mario.gif
└── space-invader.gif
```

> Le redimensionnement vers 128×32 est automatique. Pour un meilleur rendu, préférez des GIFs déjà adaptés au ratio 4:1 (ex. 256×64 ou 512×128).

### 3. Jouer un GIF depuis Lovelace

1. Ajouter une carte **Media Control** ciblant l'entité `media_player.zedmd`
2. Cliquer sur l'icône **Parcourir le média** (📁)
3. Choisir **ZeDMD GIFs** → cliquer sur le GIF de votre choix → il se joue immédiatement en boucle

> Aucun redémarrage de HA n'est nécessaire pour ajouter un nouveau GIF — il suffit de rafraîchir le navigateur multimédia (le dossier est rescaná à chaque ouverture).

### Alternative : URL externe

Pour un GIF hébergé en ligne (sans le copier dans `/config/www/`), utilisez le service `zedmd.play_gif` :

```yaml
service: zedmd.play_gif
data:
  url: https://example.com/animated.gif
  loop: true
```

---

## Outil de test local (`zedmd_test.py`)

Script Python standalone pour envoyer des commandes au ZeDMD **directement depuis votre poste**, sans passer par Home Assistant. Utile pour déboguer le protocole ou tester l'afficheur indépendamment de HA.

### Installation from scratch (Python uniquement)

> Prérequis : **Python 3.11+** installé. Vérifier avec `python --version`.

**1. Récupérer le script**

```bash
# Option A — cloner le dépôt
git clone https://github.com/PPUC/zedmd-home-assistant.git
cd zedmd-home-assistant

# Option B — télécharger uniquement le script
curl -O https://raw.githubusercontent.com/PPUC/zedmd-home-assistant/main/zedmd_test.py
# ou sous Windows (PowerShell) :
Invoke-WebRequest -Uri https://raw.githubusercontent.com/PPUC/zedmd-home-assistant/main/zedmd_test.py -OutFile zedmd_test.py
```

**2. Créer un environnement virtuel** *(recommandé)*

```bash
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (cmd)
.venv\Scripts\activate.bat

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

**3. Installer les dépendances**

```bash
# Linux / macOS
pip install aiohttp Pillow

# Windows — si pip n'est pas dans le PATH, utiliser py -m pip
py -m pip install aiohttp Pillow
```

**4. Tester**

```bash
# Linux / macOS
python zedmd_test.py --host <IP_DU_ZEDMD> text "Hello ZeDMD"

# Windows
py zedmd_test.py --host <IP_DU_ZEDMD> text "Hello ZeDMD"
```

Pour quitter l'environnement virtuel : `deactivate`.

### Utilisation

```
python zedmd_test.py --host <IP> <commande> [options]
```

### Commandes

#### `text` — Afficher un message

```bash
# Texte défilant (défaut si le texte dépasse 128 px)
python zedmd_test.py --host 192.168.1.50 text "Hello World"

# Défilement pendant 10 secondes puis arrêt
python zedmd_test.py --host 192.168.1.50 text "Hello World" --duration 10

# Texte statique forcé
python zedmd_test.py --host 192.168.1.50 text "Hello" --no-scroll

# Couleur de texte et fond personnalisés
python zedmd_test.py --host 192.168.1.50 text "Alerte" --color "#FF4400" --bg-color "#000033"

# Vitesse et FPS du défilement
python zedmd_test.py --host 192.168.1.50 text "Lent..." --scroll-speed 1 --fps 10
```

| Option | Description | Défaut |
|---|---|---|
| `--color` | Couleur du texte (`#RRGGBB`) | `#FFFFFF` |
| `--bg-color` | Couleur de fond (`#RRGGBB`) | `#000000` |
| `--no-scroll` | Force l'affichage statique | — |
| `--scroll-speed` | Pixels par frame | `2` |
| `--fps` | Frames par seconde | `20` |
| `--duration` | Durée du défilement en secondes (0 = Ctrl-C) | `0` |

#### `clear` — Effacer l'écran

```bash
python zedmd_test.py --host 192.168.1.50 clear
```

#### `brightness` — Régler la luminosité

```bash
# Luminosité à 50 %
python zedmd_test.py --host 192.168.1.50 brightness 50
```

#### `test-pattern` — Cadre de couleur unie

```bash
# Rouge (défaut)
python zedmd_test.py --host 192.168.1.50 test-pattern

# Vert
python zedmd_test.py --host 192.168.1.50 test-pattern --r 0 --g 255 --b 0

# Blanc
python zedmd_test.py --host 192.168.1.50 test-pattern --r 255 --g 255 --b 255
```

### Options globales

| Option | Description | Défaut |
|---|---|---|
| `--host` | Adresse IP ou hostname du ZeDMD | *(obligatoire)* |
| `--http-port` | Port du handshake HTTP | `80` |
| `--stream-port` | Port TCP (surchargé par le handshake) | `3333` |
