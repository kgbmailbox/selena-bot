#!/bin/bash
echo "=== Установка шрифтов ==="
apt-get update -qq && apt-get install -y -qq fonts-dejavu-core fonts-dejavu
fc-cache -f -v
echo "=== Шрифты установлены ==="
find /usr/share/fonts -name "DejaVu*.ttf" 2>/dev/null
echo "=== Запуск бота ==="
python bot.py
