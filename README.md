# yt-dlp GUI

Interface graphique pour **yt-dlp** permettant de télécharger des vidéos et audio depuis YouTube et autres sites supportés.

## Prérequis (Debian / Ubuntu)

Pour utiliser ce script, plusieurs dépendances système sont nécessaires.

### 1. Python 3 et Tkinter

Le script est écrit en Python 3 et utilise Tkinter pour l'interface graphique.

```bash
sudo apt update
sudo apt install python3 python3-tk python3-pip
```

### 2. yt-dlp

Le moteur de téléchargement. Installation via pip recommandée.

```bash
python3 -m pip install --upgrade yt-dlp
```

### 3. ffmpeg

Permet la conversion audio/vidéo et l'extraction des métadonnées. Nécessaire pour :

* La conversion forcée d'audio (`-x --audio-format mp3`)
* L'ajout d'images miniatures et métadonnées

```bash
sudo apt install ffmpeg
```

### 4. Codecs supplémentaires (optionnel, pour certains formats audio)

Pour produire des fichiers MP3 ou AAC correctement :

```bash
sudo apt install libmp3lame0 libfdk-aac2
```

### 5. ffprobe (fourni avec ffmpeg)

Utilisé par le script pour détecter le codec audio avant renommage sans ré-encodage.

```bash
sudo apt install ffmpeg  # ffprobe est inclus
```

### 6. Notify-send (optionnel)

Pour les notifications desktop quand le téléchargement est terminé.

```bash
sudo apt install libnotify-bin
```

## Installation du script

Clonez le projet ou copiez le script dans un dossier :

```bash
git clone <url_du_repo>
cd yt-dlp-gui
chmod +x youtube-download-gui.py
```

## Usage

```bash
./youtube-download-gui.py
```

* Sélectionnez l'URL ou ajoutez plusieurs liens à la queue.
* Choisissez le format vidéo ou audio.
* Configurez les options avancées (recode, métadonnées, thumbnail).
* Cliquez sur **Télécharger**.

## Notes

* Si vous voulez forcer la conversion audio vers MP3 ou un autre format, assurez-vous que `ffmpeg` et le codec correspondant sont installés.
* Le script tente de renommer les fichiers sans ré-encodage lorsque c'est possible pour éviter les erreurs "Encoder not found".
* Sur Debian/Ubuntu, `python3-tk` est indispensable pour Tkinter.

## Licence

MIT
