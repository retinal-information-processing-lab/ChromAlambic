@echo off
title Lampion - LED Control System

:: 1. Localisation de Conda
set CONDA_PATH=%USERPROFILE%\anaconda3\Scripts\activate.bat
if not exist "%CONDA_PATH%" set CONDA_PATH=%USERPROFILE%\miniconda3\Scripts\activate.bat

:: 2. Activation de l'environnement (Silencieux)
call "%CONDA_PATH%" chromalambic

:: 3. Navigation vers le dossier du script
:: "%~dp0" est le chemin du dossier où se trouve ce .bat
cd /d "%~dp0"

:: 4. Lancement DETACHÉ (Le secret est ici)
:: start "" : Lance une nouvelle tâche indépendante
:: pythonw  : Version de Python qui n'ouvre pas de console noire
:: "lampion_gui.py" : Ton script
start "" pythonw "lampion_gui.py"

:: 5. Fermeture immediate de la console
exit