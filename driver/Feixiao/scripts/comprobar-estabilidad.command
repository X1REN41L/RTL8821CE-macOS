#!/bin/zsh
cd "$(dirname "$0")" || exit 1
python3 comprobar_estabilidad.py
printf '\nPresioná Enter para cerrar.\n'
read respuesta
