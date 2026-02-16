@echo off
:: 1. Localisation de Conda
set CONDA_PATH=%USERPROFILE%\anaconda3\Scripts\activate.bat
if not exist "%CONDA_PATH%" set CONDA_PATH=%USERPROFILE%\miniconda3\Scripts\activate.bat

:: 2. Activation de l'environnement
call "%CONDA_PATH%" chromalambic

:: 3. NAVIGATION (L'étape cruciale qui manquait)
:: On se déplace physiquement dans le dossier "Luciole"
:: "%~dp0" signifie "le dossier où se trouve ce fichier .bat"
cd /d "%~dp0\Luciole"

:: 4. Lancement SILENCIEUX
:: Comme on est déjà dans le bon dossier, on appelle juste le nom du fichier
start "" pythonw "luciole_gui.py"

:: 5. Fermeture immédiate de la console
exit